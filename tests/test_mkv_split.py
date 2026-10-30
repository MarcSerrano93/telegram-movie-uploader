"""
MKV parts with a fake mkvmerge: no MKVToolNix needed. Real MKV splitting is not covered here.
"""
import os
import subprocess
from queue import Queue
from types import SimpleNamespace

import pytest

from conftest import error_reasons
from core import mkv_split, utils
from core.mkv_split import create_mkv_parts, find_mkvmerge
from movies.mkv_splitter import MkvSplitter

MB = 1024 * 1024
MKVMERGE = "/usr/bin/mkvmerge"

@pytest.fixture
def fake_mkvmerge(monkeypatch):
    """
    Replaces mkvmerge: writes the parts of .part_sizes in the folder it runs from and finishes with .return_code.
    Records the commands in .commands. .errors are raised by the next runs.
    """
    fake = SimpleNamespace(commands=[], part_sizes=[10, 10], return_code=0, stdout="", errors=[])
    def run(command, cwd, **kwargs):
        fake.commands.append(command)
        if fake.errors:
            raise fake.errors.pop(0)
        output = command[command.index("--output") + 1]
        for index, size in enumerate(fake.part_sizes, start=1):
            with open(os.path.join(cwd, output.replace("%d", str(index))), "wb") as f:
                f.write(b"x" * size)
        return subprocess.CompletedProcess(command, fake.return_code, stdout=fake.stdout)
    monkeypatch.setattr(mkv_split.subprocess, "run", run)
    return fake

def run_splitter(movies, limit_mb=1):
    """
    Runs the MkvSplitter thread with the movies and returns the ones it passed to the next stage.
    """
    input_queue, output_queue = Queue(), Queue()
    for movie in movies:
        input_queue.put(movie)
    input_queue.put(None)
    splitter = MkvSplitter(input_queue, output_queue, limit_mb, MKVMERGE)
    splitter.start()
    splitter.join(timeout=60)
    assert not splitter.is_alive()
    return list(iter(output_queue.get, None))

def resize(movie, size):
    os.truncate(movie.file_full_path, size)     # Without writing the data, so it is instant
    return movie

@pytest.fixture
def big_movie(make_movie, tmp_path):
    """
    A movie of 41 MB, still in the source folder, with its folder in the destination as FileSplitter leaves the big ones.
    """
    movie = resize(make_movie(), 41 * MB)
    movie.destination_path = str(tmp_path / "destination")
    os.makedirs(movie.destination_path)
    return movie

def test_find_mkvmerge_in_path(monkeypatch):
    monkeypatch.setattr(mkv_split.shutil, "which", lambda name: "/usr/bin/mkvmerge")
    assert find_mkvmerge() == "/usr/bin/mkvmerge"

def test_find_mkvmerge_in_the_windows_folder(monkeypatch, tmp_path):
    path = tmp_path / "mkvmerge.exe"
    path.write_bytes(b"")
    monkeypatch.setattr(mkv_split.shutil, "which", lambda name: None)
    monkeypatch.setattr(mkv_split, "WINDOWS_MKVMERGE_PATH", str(path))
    assert find_mkvmerge() == str(path)

def test_mkvmerge_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(mkv_split.shutil, "which", lambda name: None)
    monkeypatch.setattr(mkv_split, "WINDOWS_MKVMERGE_PATH", str(tmp_path / "missing.exe"))
    assert find_mkvmerge() is None

def test_command_and_parts(fake_mkvmerge, tmp_path):
    parts = create_mkv_parts(MKVMERGE, "in.mkv", str(tmp_path), "Movie (2024) {tmdb-1}", 3900)

    assert fake_mkvmerge.commands == [[MKVMERGE, "--output", "Movie (2024) {tmdb-1} pt%d.mkv", "--split", "size:3900M", os.path.abspath("in.mkv")]]
    assert [os.path.basename(part) for part in parts] == ["Movie (2024) {tmdb-1} pt1.mkv", "Movie (2024) {tmdb-1} pt2.mkv"]

def test_parts_are_in_order_by_number(fake_mkvmerge, tmp_path):
    fake_mkvmerge.part_sizes = [10] * 11

    parts = create_mkv_parts(MKVMERGE, "in.mkv", str(tmp_path), "Movie", 100)

    assert [os.path.basename(part) for part in parts] == [f"Movie pt{number}.mkv" for number in range(1, 12)]

def test_too_long_path_fails_without_running_mkvmerge(fake_mkvmerge, big_movie, monkeypatch):
    monkeypatch.setattr(utils, "MAX_PATH_LENGTH", 10)

    assert run_splitter([big_movie]) == []
    assert fake_mkvmerge.commands == []
    assert "Path too long" in error_reasons()[0][2]

def test_no_parts_created_is_a_failure(fake_mkvmerge, tmp_path):
    fake_mkvmerge.part_sizes = []
    with pytest.raises(RuntimeError, match="there are no \"Movie ptN.mkv\" files"):
        create_mkv_parts(MKVMERGE, "in.mkv", str(tmp_path), "Movie", 100)

def test_warnings_are_not_a_failure(fake_mkvmerge, tmp_path):
    fake_mkvmerge.return_code = 1
    assert len(create_mkv_parts(MKVMERGE, "in.mkv", str(tmp_path), "Movie", 100)) == 2

def test_error_shows_the_last_line_of_mkvmerge(fake_mkvmerge, tmp_path):
    fake_mkvmerge.return_code = 2
    fake_mkvmerge.stdout = "mkvmerge v90\nError: The file is damaged.\n"
    with pytest.raises(RuntimeError, match="mkvmerge failed: Error: The file is damaged."):
        create_mkv_parts(MKVMERGE, "in.mkv", str(tmp_path), "Movie", 100)

def test_big_movie_gets_its_parts(fake_mkvmerge, big_movie):
    assert run_splitter([big_movie], limit_mb=40) == [big_movie]

    parts_path = os.path.join(big_movie.destination_path, "mkv_parts")
    assert big_movie.mkv_parts_path == parts_path
    assert sorted(os.listdir(parts_path)) == ["Película (2024) {tmdb-1} pt1.mkv", "Película (2024) {tmdb-1} pt2.mkv"]
    assert not os.path.exists(parts_path + ".partial")
    assert os.path.isfile(big_movie.file_full_path)
    # Asks for a bit less than the limit, as a part can end over the size asked
    assert "size:38M" in fake_mkvmerge.commands[0]

def test_small_movie_is_not_split(fake_mkvmerge, make_movie):
    movie = make_movie(size=100)

    assert run_splitter([movie]) == [movie]
    assert fake_mkvmerge.commands == []
    assert movie.mkv_parts_path == ""

def test_already_split_movie_is_not_split_again(fake_mkvmerge, big_movie):
    os.makedirs(os.path.join(big_movie.destination_path, "mkv_parts"))

    assert run_splitter([big_movie]) == [big_movie]
    assert fake_mkvmerge.commands == []
    assert big_movie.mkv_parts_path == os.path.join(big_movie.destination_path, "mkv_parts")

def test_percent_is_removed_from_the_output_name(fake_mkvmerge, make_movie, tmp_path):
    movie = resize(make_movie(title="100% Wolf"), 2 * MB)
    movie.destination_path = str(tmp_path / "destination")
    os.makedirs(movie.destination_path)

    run_splitter([movie])

    assert sorted(os.listdir(movie.mkv_parts_path))[0] == "100. Wolf (2024) {tmdb-1} pt1.mkv"

def test_part_over_the_limit_fails_without_retrying(fake_mkvmerge, big_movie):
    fake_mkvmerge.part_sizes = [MB + 1]

    assert run_splitter([big_movie]) == []
    assert len(fake_mkvmerge.commands) == 1
    assert "is bigger than the Telegram limit" in error_reasons()[0][2]
    assert not os.path.exists(os.path.join(big_movie.destination_path, "mkv_parts"))

def test_failed_split_is_retried_from_a_clean_folder(fake_mkvmerge, big_movie):
    fake_mkvmerge.errors = [OSError("Disk busy")]

    assert run_splitter([big_movie]) == [big_movie]
    assert len(fake_mkvmerge.commands) == 2
    assert len(os.listdir(big_movie.mkv_parts_path)) == 2
