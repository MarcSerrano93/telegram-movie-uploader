import os
import subprocess
from queue import Queue

import pytest

import file_splitter
from conftest import error_reasons
from constants import FileStatus, PROJECT_ROOT
from file_splitter import FileSplitter

MB = 1024 * 1024
REAL_SEVEN_ZIP = os.path.join(PROJECT_ROOT, "7z.exe")

@pytest.fixture
def destination(tmp_path):
    path = tmp_path / "destination"
    path.mkdir()
    return path

@pytest.fixture
def fake_seven_zip(tmp_path, monkeypatch):
    """
    Replaces 7z with a fake one. Set fake.exit_codes to make the first calls fail; it creates 2 parts when it works.
    """
    seven_zip = tmp_path / "7z.exe"
    seven_zip.write_bytes(b"")
    monkeypatch.setattr(file_splitter, "SEVEN_ZIP_PATH", str(seven_zip))

    class FakeSevenZip:
        exit_codes = []
        calls = []
        def run(self, command, **kwargs):
            self.calls.append(command)
            if self.exit_codes:
                error = "\r\nERROR: The system cannot find the file specified.\r\nC:\\movie.mkv\r\n"
                return subprocess.CompletedProcess(command, self.exit_codes.pop(0), stderr=error)
            archive_path = command[-2]
            for part in (1, 2):
                with open(f"{archive_path}.{part:03d}", "wb") as f:
                    f.write(b"part")
            return subprocess.CompletedProcess(command, 0)

    fake = FakeSevenZip()
    monkeypatch.setattr(file_splitter.subprocess, "run", fake.run)
    return fake

def run_splitter(movies, destination, limit_mb=1):
    """
    Runs the FileSplitter thread with the movies and returns the ones it passed to the next stage.
    """
    input_queue, output_queue = Queue(), Queue()
    for movie in movies:
        input_queue.put(movie)
    input_queue.put(None)
    splitter = FileSplitter(input_queue, output_queue, str(destination), limit_mb)
    splitter.start()
    splitter.join(timeout=60)
    assert not splitter.is_alive()
    return list(iter(output_queue.get, None))

def test_small_file_is_moved(make_movie, destination):
    movie = make_movie("Small (2024) {tmdb-1}.mkv", size=1000)

    assert run_splitter([movie], destination) == [movie]

    folder = destination / "Small (2024) {tmdb-1}"
    assert os.listdir(folder) == ["Small (2024) {tmdb-1}.mkv"]
    assert not os.path.exists(movie.file_full_path)
    assert movie.destination_path == str(folder)
    assert movie.status == FileStatus.SPLIT

def test_file_of_exactly_the_limit_is_moved(make_movie, destination, fake_seven_zip):
    movie = make_movie(size=MB)
    run_splitter([movie], destination)
    assert fake_seven_zip.calls == []

def test_big_file_is_split_and_original_kept(make_movie, destination, fake_seven_zip):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1, title="Big: Movie?")

    assert run_splitter([movie], destination, limit_mb=1) == [movie]

    command = fake_seven_zip.calls[0]
    assert command[:7] == [file_splitter.SEVEN_ZIP_PATH, "a", "-tzip", "-mx0", "-bso0", "-bsp0", "-v1m"]
    folder = destination / "Big (2024) {tmdb-1}"
    # Characters not allowed in file names are replaced
    assert sorted(os.listdir(folder)) == ["Big. Movie. (2024).zip.001", "Big. Movie. (2024).zip.002"]
    assert os.path.exists(movie.file_full_path)
    assert not os.path.exists(f"{folder}.partial")

def test_already_split_file_is_not_split_again(make_movie, destination, fake_seven_zip):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    (destination / "Big (2024) {tmdb-1}").mkdir()

    assert run_splitter([movie], destination) == [movie]
    assert fake_seven_zip.calls == []

def test_failed_split_is_retried(make_movie, destination, fake_seven_zip):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    fake_seven_zip.exit_codes = [2]

    assert run_splitter([movie], destination) == [movie]
    assert len(fake_seven_zip.calls) == 2
    assert len(os.listdir(destination / "Big (2024) {tmdb-1}")) == 2

def test_split_failing_3_times_is_reported(make_movie, destination, fake_seven_zip):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    fake_seven_zip.exit_codes = [2, 2, 2]

    assert run_splitter([movie], destination) == []
    # Only the first line of 7z's error output, so the summary stays on one line
    expected = "7z failed (exit code 2): ERROR: The system cannot find the file specified. (failed after 3 attempts)"
    assert error_reasons() == [("SPLIT", movie.file_name, expected)]
    # Only the temporary folder is left, so the next run splits it again
    assert not os.path.exists(destination / "Big (2024) {tmdb-1}")
    assert movie.status == FileStatus.ERROR

def test_missing_7z_is_reported(make_movie, destination, monkeypatch, tmp_path):
    monkeypatch.setattr(file_splitter, "SEVEN_ZIP_PATH", str(tmp_path / "missing" / "7z.exe"))
    movie = make_movie(size=MB + 1)

    assert run_splitter([movie], destination) == []
    assert error_reasons()[0][2].startswith("7z.exe not found")

def test_missing_source_file_is_reported(make_movie, destination):
    movie = make_movie()
    os.remove(movie.file_full_path)

    assert run_splitter([movie], destination) == []
    assert error_reasons()[0][2].startswith("Source file not found")

def test_one_failure_does_not_stop_the_others(make_movie, destination):
    missing = make_movie("Missing (2024) {tmdb-1}.mkv")
    os.remove(missing.file_full_path)
    good = make_movie("Good (2024) {tmdb-2}.mkv")

    assert run_splitter([missing, good], destination) == [good]

def test_split_logs_start_and_end(make_movie, destination, fake_seven_zip, capsys):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)

    run_splitter([movie], destination)

    output = capsys.readouterr().out
    assert "Splitting \"Big (2024) {tmdb-1}.mkv\" (1.0 MB)..." in output
    assert "\"Big (2024) {tmdb-1}.mkv\" split into 2 parts in 0m 0s" in output

@pytest.mark.skipif(not os.path.isfile(REAL_SEVEN_ZIP), reason="7z.exe not in the project root")
def test_split_with_real_7z(make_movie, destination, capfd):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=2 * MB + MB // 2, title="Big")

    assert run_splitter([movie], destination, limit_mb=1) == [movie]

    parts = sorted(os.listdir(destination / "Big (2024) {tmdb-1}"))
    assert parts == ["Big (2024).zip.001", "Big (2024).zip.002", "Big (2024).zip.003"]
    assert all(os.path.getsize(destination / "Big (2024) {tmdb-1}" / part) <= MB for part in parts)
    # 7z itself prints nothing, only our own log lines
    output = capfd.readouterr().out
    assert all(line.startswith("\033[95m[FileSplitter]") for line in output.splitlines() if line.strip())

@pytest.mark.skipif(not os.path.isfile(REAL_SEVEN_ZIP), reason="7z.exe not in the project root")
def test_real_7z_error_is_in_the_message(make_movie, destination, monkeypatch):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    # Locked file: 7z cannot read it, like a movie still being copied
    real_run = subprocess.run
    def run_with_locked_file(command, **kwargs):
        with open(movie.file_full_path, "r+b") as f:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, os.path.getsize(movie.file_full_path))
            try:
                return real_run(command, **kwargs)
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, os.path.getsize(movie.file_full_path))
    monkeypatch.setattr(file_splitter.subprocess, "run", run_with_locked_file)

    assert run_splitter([movie], destination) == []
    reason = error_reasons()[0][2]
    assert reason.startswith("7z failed (exit code ")
    assert "): " in reason
