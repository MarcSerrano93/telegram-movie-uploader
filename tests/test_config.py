import json

import pytest

from core import config
from core.config import Config, ConfigError

ENV = {"API_ID": "12345", "API_HASH": "hash", "PHONE_NUMBER": "+34600000000", "API_KEY": "key"}
MOVIE_KEYS = ["source_files_path", "destination_files_path", "telegram_group"]

@pytest.fixture
def valid_config(tmp_path, monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return {
        "telegram_size_limit_mb": 4000,
        "movies": {
            "source_files_path": str(tmp_path),
            "destination_files_path": str(tmp_path),
            "telegram_group": "https://t.me/+test",
        },
    }

@pytest.fixture
def load(tmp_path, monkeypatch):
    """
    Writes the content to a temporary config.json and loads it with Config() for the given mode.
    """
    def load_config(content, mode="movies"):
        path = tmp_path / "config.json"
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        monkeypatch.setattr(config, "CONFIG_FILE_PATH", str(path))
        return Config(mode)
    return load_config

def test_valid_config(load, valid_config):
    valid_config["movies"]["unknown_key"] = "ignored"
    loaded = load(valid_config)
    assert loaded.mode == "movies"
    assert loaded.source_files_path == valid_config["movies"]["source_files_path"]
    assert loaded.destination_files_path == valid_config["movies"]["destination_files_path"]
    assert loaded.telegram_size_limit_mb == 4000
    assert loaded.telegram_group == "https://t.me/+test"

def test_other_sections_are_not_checked(load, valid_config):
    valid_config["tv"] = {"source_files_path": "Z:/does/not/exist"}
    assert load(valid_config).mode == "movies"

def test_tv_mode(load, valid_config, tmp_path):
    del valid_config["movies"]
    valid_config["tv"] = {"source_files_path": str(tmp_path), "telegram_group": "https://t.me/+tv"}
    loaded = load(valid_config, mode="tv")
    assert (loaded.source_files_path, loaded.destination_files_path, loaded.telegram_group) == (str(tmp_path), None, "https://t.me/+tv")

def test_tv_mode_with_old_format(load, valid_config):
    old = {"telegram_size_limit_mb": 4000, **valid_config["movies"]}
    with pytest.raises(ConfigError, match="move the movie keys into a \"movies\" section"):
        load(old, mode="tv")

@pytest.mark.parametrize("limit", [1, 2000, 4000])
def test_valid_size_limits(load, valid_config, limit):
    assert load({**valid_config, "telegram_size_limit_mb": limit}).telegram_size_limit_mb == limit

def test_missing_file(tmp_path, monkeypatch, valid_config):
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(ConfigError, match="not found"):
        Config("movies")

@pytest.mark.parametrize("content, message", [
    ("{ not json", "not valid JSON"),
    ("[]", "must contain a JSON object"),
])
def test_invalid_json(load, valid_config, content, message):
    with pytest.raises(ConfigError, match=message):
        load(content)

def test_old_flat_format(load, valid_config):
    old = {"telegram_size_limit_mb": 4000, **valid_config["movies"]}
    with pytest.raises(ConfigError, match="old format: move the movie keys into a \"movies\" section"):
        load(old)

def test_missing_mode_section(load, valid_config):
    del valid_config["movies"]
    with pytest.raises(ConfigError, match="missing key \"movies\""):
        load(valid_config)

def test_mode_section_must_be_an_object(load, valid_config):
    with pytest.raises(ConfigError, match="\"movies\" must be a JSON object"):
        load({**valid_config, "movies": "E:/Movies"})

def test_missing_size_limit(load, valid_config):
    del valid_config["telegram_size_limit_mb"]
    with pytest.raises(ConfigError, match="missing key \"telegram_size_limit_mb\""):
        load(valid_config)

@pytest.mark.parametrize("key", MOVIE_KEYS)
def test_missing_movie_key(load, valid_config, key):
    del valid_config["movies"][key]
    with pytest.raises(ConfigError, match=f"missing key \"movies.{key}\""):
        load(valid_config)

@pytest.mark.parametrize("key", ["source_files_path", "destination_files_path"])
def test_folder_does_not_exist(load, valid_config, tmp_path, key):
    valid_config["movies"][key] = str(tmp_path / "missing")
    with pytest.raises(ConfigError, match=f"movies.{key} does not exist"):
        load(valid_config)

@pytest.mark.parametrize("limit", ["4000", 4001, 0, -1, 1.5, True, None])
def test_invalid_size_limit(load, valid_config, limit):
    with pytest.raises(ConfigError, match="must be a whole number between 1 and 4000"):
        load({**valid_config, "telegram_size_limit_mb": limit})

@pytest.mark.parametrize("group", ["", "   ", None])
def test_empty_group(load, valid_config, group):
    valid_config["movies"]["telegram_group"] = group
    with pytest.raises(ConfigError, match="movies.telegram_group is empty"):
        load(valid_config)

@pytest.mark.parametrize("name", ENV)
def test_missing_env_variable(load, valid_config, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ConfigError, match=f"{name} is missing in .env"):
        load(valid_config)

def test_api_id_must_be_a_number(load, valid_config, monkeypatch):
    monkeypatch.setenv("API_ID", "abc")
    with pytest.raises(ConfigError, match="API_ID in .env must be a number"):
        load(valid_config)
