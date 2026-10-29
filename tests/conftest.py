"""
Shared fixtures. pytest.ini adds src/ to the import path.
"""
import os

import pytest

import shared_state
import utils
from movie import Movie

@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch):
    # Retries still happen, without waiting 10s/30s
    monkeypatch.setattr(utils, "RETRY_DELAYS", [0, 0])

@pytest.fixture(autouse=True)
def clean_shared_state():
    yield
    for items in (shared_state.movies, shared_state.errors, shared_state.warnings):
        items.clear()

@pytest.fixture
def make_movie(tmp_path):
    """
    Creates a movie file of the given size in tmp_path/source and returns its Movie, with TMDB info filled in.
    """
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    def make(file_name="Movie (2024) {tmdb-1}.mkv", size=100, title="Película", year="2024"):
        path = source / file_name
        path.write_bytes(os.urandom(size))
        movie = Movie(str(path))
        movie.set_movie_metadata(title, "Movie", year, [], 100, "https://image.tmdb.org/t/p/w500/poster.jpg")
        return movie
    return make

def error_reasons():
    """
    Returns the (step value, file name, reason) of every reported error, as strings.
    """
    return [(step.value, file_name, str(reason)) for step, file_name, reason in shared_state.errors]
