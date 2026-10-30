import asyncio
import os

import pytest

from core import shared_state, utils
from core.constants import FileStatus, Step
from core.utils import (PermanentError, check_path_length, format_duration, format_size, print_summary, report_failure,
                        report_warning, with_retries, with_retries_async)
from movies.movie import Movie

def test_path_over_the_limit_is_a_permanent_error(monkeypatch, tmp_path):
    path = str(tmp_path / "file.mkv")
    monkeypatch.setattr(utils, "MAX_PATH_LENGTH", len(os.path.realpath(path)) - 1)
    with pytest.raises(PermanentError, match="Path too long"):
        check_path_length(path)

def test_path_of_exactly_the_limit_is_fine(monkeypatch, tmp_path):
    path = str(tmp_path / "file.mkv")
    monkeypatch.setattr(utils, "MAX_PATH_LENGTH", len(os.path.realpath(path)))
    check_path_length(path)

def test_no_path_limit_outside_windows(monkeypatch):
    monkeypatch.setattr(utils, "MAX_PATH_LENGTH", None)
    check_path_length("x" * 1000)

class FloodWait(Exception):
    """
    Like Telegram's FloodWaitError: has the seconds to wait.
    """
    seconds = 0.01

def failing(errors, result="ok"):
    """
    Returns an operation that raises the given errors one per call, then returns result. calls counts the calls.
    """
    calls = []
    def operation():
        calls.append(1)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return result
    return operation, calls

def test_retry_succeeds_after_temporary_errors():
    operation, calls = failing([OSError("locked"), ConnectionError("down")])
    assert with_retries(Step.SPLIT, "a.mkv", operation) == "ok"
    assert len(calls) == 3

def test_retry_gives_up_after_3_attempts():
    operation, calls = failing([OSError("locked")] * 5)
    with pytest.raises(RuntimeError, match="locked \\(failed after 3 attempts\\)"):
        with_retries(Step.SPLIT, "a.mkv", operation)
    assert len(calls) == 3

def test_permanent_error_is_not_retried():
    operation, calls = failing([PermanentError("wrong id")])
    with pytest.raises(PermanentError):
        with_retries(Step.TMDB, "a.mkv", operation)
    assert len(calls) == 1

def test_extra_permanent_errors_are_not_retried():
    operation, calls = failing([PermissionError("forbidden")])
    with pytest.raises(PermissionError):
        with_retries(Step.UPLOAD, "a.mkv", operation, (PermissionError,))
    assert len(calls) == 1

def test_flood_waits_do_not_count_as_attempts():
    operation, calls = failing([FloodWait()] * 5)
    assert with_retries(Step.UPLOAD, "a.mkv", operation) == "ok"
    assert len(calls) == 6

def test_async_retry():
    operation, calls = failing([ConnectionError("down"), FloodWait(), ConnectionError("down")])
    async def async_operation():
        return operation()
    assert asyncio.run(with_retries_async(Step.UPLOAD, "a.mkv", async_operation)) == "ok"
    assert len(calls) == 4

def test_async_retry_gives_up_after_3_attempts():
    operation, calls = failing([ConnectionError("down")] * 5)
    async def async_operation():
        return operation()
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        asyncio.run(with_retries_async(Step.UPLOAD, "a.mkv", async_operation))
    assert len(calls) == 3

def test_reports_are_stored_for_the_summary():
    report_failure(Step.TMDB, "a.mkv", "not found")
    report_warning(Step.UPLOAD, "b.mkv", "no poster")
    assert shared_state.errors == [(Step.TMDB, "a.mkv", "not found")]
    assert shared_state.warnings == [(Step.UPLOAD, "b.mkv", "no poster")]

@pytest.mark.parametrize("size, expected", [
    (512, "512.0 B"),
    (1536, "1.5 KB"),
    (3 * 1024 ** 2, "3.0 MB"),
    (5 * 1024 ** 3, "5.0 GB"),
    (2048 * 1024 ** 3, "2048.0 GB"),
])
def test_format_size(size, expected):
    assert format_size(size) == expected

@pytest.mark.parametrize("seconds, expected", [(59.9, "0m 59s"), (125, "2m 5s"), (3725, "1h 2m 5s")])
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected

def add_movie(file_name, status):
    movie = Movie(file_name)
    movie.status = status
    shared_state.items.append(movie)

def test_summary_without_errors(capsys):
    add_movie("a {tmdb-1}.mkv", FileStatus.UPLOADED)
    print_summary("movies")
    output = capsys.readouterr().out
    assert "Uploaded: 1 of 1 movies" in output
    assert "No errors" in output

def test_summary_with_errors_and_warnings(capsys):
    add_movie("uploaded {tmdb-1}.mkv", FileStatus.UPLOADED)
    add_movie("failed {tmdb-2}.mkv", FileStatus.ERROR)
    add_movie("stuck {tmdb-3}.mkv", FileStatus.PARSED)
    report_failure(Step.READ, "no tag.mkv", "No {tmdb-<id>} tag in the file name")
    report_failure(Step.TMDB, "failed {tmdb-2}.mkv", "Movie not found in TMDB")
    report_warning(Step.UPLOAD, "uploaded {tmdb-1}.mkv", "No poster in TMDB")
    capsys.readouterr()

    print_summary("movies")
    output = capsys.readouterr().out
    # 3 movies + the file skipped while reading the folder
    assert "Uploaded: 1 of 4 movies" in output
    assert "ERRORS (3)" in output
    assert "Stopped with status PARSED" in output   # Not finished, without a reported error
    assert "WARNINGS (1)" in output
    assert "No errors" not in output
