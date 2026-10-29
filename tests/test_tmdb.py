"""
TMDB requests with a fake requests.get: no network and no API key needed.
"""
from types import SimpleNamespace

import pytest
import requests

from conftest import fake_response
from core import tmdb
from core.tmdb import parse_tmdb_id
from core.utils import PermanentError

@pytest.fixture
def fake_tmdb(monkeypatch):
    """
    Records the (url, params) of each request in .calls. Set .response to choose what TMDB answers.
    """
    fake = SimpleNamespace(calls=[], response=fake_response(200, {"name": "Show"}))
    def get(url, params, timeout):
        fake.calls.append((url, params))
        return fake.response
    monkeypatch.setattr(tmdb.requests, "get", get)
    monkeypatch.setenv("API_KEY", "key")
    return fake

@pytest.mark.parametrize("text, expected", [
    ("Movie (2024) {tmdb-112233}.mkv", "112233"),
    ("Movie {tmdb-7} extra.mkv", "7"),
    ("Movie (2024).mkv", None),
    ("Movie {tmdb-abc}.mkv", None),
    ("Movie {tmdb 1}.mkv", None),
])
def test_parse_tmdb_id(text, expected):
    assert parse_tmdb_id(text) == expected

def test_image_url():
    assert tmdb.image_url(tmdb.POSTER_BASE_URL, "/a.jpg") == "https://image.tmdb.org/t/p/w500/a.jpg"
    assert tmdb.image_url(tmdb.POSTER_BASE_URL, None) == ""

def test_get_info(fake_tmdb):
    assert tmdb.get_info("tv/1396", tmdb.LANGUAGE_EN, "not found") == {"name": "Show"}
    assert fake_tmdb.calls == [("https://api.themoviedb.org/3/tv/1396", {"api_key": "key", "language": "en-US"})]

@pytest.mark.parametrize("status_code, message", [(404, "not found"), (401, "Invalid TMDB API key")])
def test_wrong_id_or_key_is_permanent(fake_tmdb, status_code, message):
    fake_tmdb.response = fake_response(status_code)
    with pytest.raises(PermanentError, match=message):
        tmdb.get_info("tv/1", tmdb.LANGUAGE_EN, "not found")

def test_server_error_can_be_retried(fake_tmdb):
    fake_tmdb.response = fake_response(500)
    with pytest.raises(requests.HTTPError):
        tmdb.get_info("tv/1", tmdb.LANGUAGE_EN, "not found")
