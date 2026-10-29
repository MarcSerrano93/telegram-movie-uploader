import os
import zipfile
from pathlib import Path
from queue import Queue

import pytest

from conftest import error_reasons
from core.constants import FileStatus
from movies import file_splitter
from movies.file_splitter import FileSplitter

MB = 1024 * 1024

@pytest.fixture
def destination(tmp_path):
    path = tmp_path / "destination"
    path.mkdir()
    return path

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

def failing_split(errors):
    """
    Returns a create_split_zip that raises the given errors one per call, then splits for real.
    """
    real_split = file_splitter.create_split_zip
    def split(*args):
        if errors:
            raise errors.pop(0)
        return real_split(*args)
    return split

def test_small_file_is_moved(make_movie, destination):
    movie = make_movie("Small (2024) {tmdb-1}.mkv", size=1000)

    assert run_splitter([movie], destination) == [movie]

    folder = destination / "Small (2024) {tmdb-1}"
    assert os.listdir(folder) == ["Small (2024) {tmdb-1}.mkv"]
    assert not os.path.exists(movie.file_full_path)
    assert movie.destination_path == str(folder)
    assert movie.status == FileStatus.SPLIT

def test_file_of_exactly_the_limit_is_moved(make_movie, destination):
    movie = make_movie("Movie (2024) {tmdb-1}.mkv", size=MB)

    run_splitter([movie], destination)

    assert os.listdir(destination / "Movie (2024) {tmdb-1}") == ["Movie (2024) {tmdb-1}.mkv"]

def test_big_file_is_split_and_original_kept(make_movie, destination):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=2 * MB + MB // 2, title="Big: Movie?")

    assert run_splitter([movie], destination, limit_mb=1) == [movie]

    folder = destination / "Big (2024) {tmdb-1}"
    # Characters not allowed in file names are replaced
    parts = sorted(os.listdir(folder))
    assert parts == ["Big. Movie. (2024).zip.001", "Big. Movie. (2024).zip.002", "Big. Movie. (2024).zip.003"]
    assert all(os.path.getsize(folder / part) <= MB for part in parts)
    assert os.path.exists(movie.file_full_path)
    assert not os.path.exists(f"{folder}.partial")
    assert movie.status == FileStatus.SPLIT

def test_parts_contain_the_movie(make_movie, destination, tmp_path):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1, title="Big")
    run_splitter([movie], destination)

    folder = destination / "Big (2024) {tmdb-1}"
    joined = tmp_path / "joined.zip"
    with open(joined, "wb") as f:
        for part in sorted(os.listdir(folder)):
            f.write((folder / part).read_bytes())
    with zipfile.ZipFile(joined) as archive:
        assert archive.read("Big (2024) {tmdb-1}.mkv") == Path(movie.file_full_path).read_bytes()

def test_split_logs_start_and_end(make_movie, destination, capsys):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)

    run_splitter([movie], destination)

    output = capsys.readouterr().out
    assert "Splitting \"Big (2024) {tmdb-1}.mkv\" (1.0 MB)..." in output
    assert "\"Big (2024) {tmdb-1}.mkv\" split into 2 parts in 0m 0s" in output

def test_already_split_file_is_not_split_again(make_movie, destination, monkeypatch):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    (destination / "Big (2024) {tmdb-1}").mkdir()
    monkeypatch.setattr(file_splitter, "create_split_zip", failing_split([AssertionError("split again")]))

    assert run_splitter([movie], destination) == [movie]
    assert error_reasons() == []

def test_failed_split_is_retried(make_movie, destination, monkeypatch):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    monkeypatch.setattr(file_splitter, "create_split_zip", failing_split([OSError("Disk busy")]))

    assert run_splitter([movie], destination) == [movie]
    assert len(os.listdir(destination / "Big (2024) {tmdb-1}")) == 2

def test_split_failing_3_times_is_reported(make_movie, destination, monkeypatch):
    movie = make_movie("Big (2024) {tmdb-1}.mkv", size=MB + 1)
    monkeypatch.setattr(file_splitter, "create_split_zip", failing_split([OSError("No space left on device")] * 3))

    assert run_splitter([movie], destination) == []
    assert error_reasons() == [("SPLIT", movie.file_name, "No space left on device (failed after 3 attempts)")]
    # Only the temporary folder is left, so the next run splits it again
    assert not os.path.exists(destination / "Big (2024) {tmdb-1}")
    assert movie.status == FileStatus.ERROR

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
