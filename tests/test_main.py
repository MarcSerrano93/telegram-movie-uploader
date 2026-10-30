"""
The command line, with a fake config and a fake pipeline.
"""
import sys
from types import SimpleNamespace

import pytest

import main
from core import shared_state
from core.constants import FileStatus

@pytest.fixture
def run(monkeypatch):
    """
    Returns a function that runs main() with the given arguments and returns what the fake pipeline received.
    read_items returns the given items, and create_stages records that the pipeline was started.
    """
    def run_main(arguments, items=()):
        calls = SimpleNamespace(name_filter=None, started=False)
        def read_items(config, name_filter=""):
            calls.name_filter = name_filter
            return list(items)
        def create_stages(config, input_queue):
            calls.started = True
            return []
        pipeline = SimpleNamespace(read_items=read_items, create_stages=create_stages, ITEM_LABEL="movies")
        monkeypatch.setattr(main, "PIPELINES", {"movies": pipeline, "tv": pipeline})
        monkeypatch.setattr(main, "Config", lambda mode: SimpleNamespace(source_files_path="E:/Source"))
        monkeypatch.setattr(main, "load_dotenv", lambda path: None)
        monkeypatch.setattr(sys, "argv", ["main.py", *arguments])
        main.main()
        return calls
    return run_main

def test_without_filter_everything_is_read(run):
    assert run(["movies"]).name_filter == ""

def test_filter_is_passed_to_the_reader(run):
    assert run(["tv", "--filter", "breaking"], items=[SimpleNamespace(status=FileStatus.UPLOADED, file_name="x")]).name_filter == "breaking"

def test_filter_without_matches_stops_before_starting_the_pipeline(run, capsys):
    calls = run(["movies", "--filter", "nothing"])

    assert not calls.started
    assert "Nothing in E:/Source has \"nothing\" in its name" in capsys.readouterr().out

def test_filter_with_only_errors_shows_them_in_the_summary(run, capsys):
    # A matching file without tag is an error, not "nothing found"
    shared_state.errors.append((SimpleNamespace(value="READ"), "Matrix.mkv", "No {tmdb-<id>} tag in the file name"))

    calls = run(["movies", "--filter", "matrix"])

    assert calls.started
    assert "No {tmdb-<id>} tag in the file name" in capsys.readouterr().out
