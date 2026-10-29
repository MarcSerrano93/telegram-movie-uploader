import json

import pytest

import config
from config import Config, ConfigError

ENV = {"API_ID": "12345", "API_HASH": "hash", "PHONE_NUMBER": "+34600000000", "API_KEY": "key"}

@pytest.fixture
def valid_config(tmp_path, monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return {
        "source_files_path": str(tmp_path),
        "destination_files_path": str(tmp_path),
        "telegram_size_limit_mb": 4000,
        "telegram_movie_group": "https://t.me/+test",
    }

@pytest.fixture
def load(tmp_path, monkeypatch):
    """
    Writes the content to a temporary config.json and loads it with Config().
    """
    def load_config(content):
        path = tmp_path / "config.json"
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        monkeypatch.setattr(config, "CONFIG_FILE_PATH", str(path))
        return Config()
    return load_config

def test_valid_config(load, valid_config):
    loaded = load({**valid_config, "unknown_key": "ignored"})
    assert loaded.source_files_path == valid_config["source_files_path"]
    assert loaded.telegram_size_limit_mb == 4000
    assert loaded.telegram_movie_group == "https://t.me/+test"

@pytest.mark.parametrize("limit", [1, 2000, 4000])
def test_valid_size_limits(load, valid_config, limit):
    assert load({**valid_config, "telegram_size_limit_mb": limit}).telegram_size_limit_mb == limit

def test_missing_file(tmp_path, monkeypatch, valid_config):
    monkeypatch.setattr(config, "CONFIG_FILE_PATH", str(tmp_path / "missing.json"))
    with pytest.raises(ConfigError, match="not found"):
        Config()

@pytest.mark.parametrize("content, message", [
    ("{ not json", "not valid JSON"),
    ("[]", "must contain a JSON object"),
])
def test_invalid_json(load, valid_config, content, message):
    with pytest.raises(ConfigError, match=message):
        load(content)

@pytest.mark.parametrize("key", ["source_files_path", "destination_files_path", "telegram_size_limit_mb", "telegram_movie_group"])
def test_missing_key(load, valid_config, key):
    del valid_config[key]
    with pytest.raises(ConfigError, match=f"missing key \"{key}\""):
        load(valid_config)

@pytest.mark.parametrize("key", ["source_files_path", "destination_files_path"])
def test_folder_does_not_exist(load, valid_config, tmp_path, key):
    with pytest.raises(ConfigError, match=f"{key} does not exist"):
        load({**valid_config, key: str(tmp_path / "missing")})

@pytest.mark.parametrize("limit", ["4000", 4001, 0, -1, 1.5, True, None])
def test_invalid_size_limit(load, valid_config, limit):
    with pytest.raises(ConfigError, match="must be a whole number between 1 and 4000"):
        load({**valid_config, "telegram_size_limit_mb": limit})

@pytest.mark.parametrize("group", ["", "   ", None])
def test_empty_group(load, valid_config, group):
    with pytest.raises(ConfigError, match="telegram_movie_group is empty"):
        load({**valid_config, "telegram_movie_group": group})

@pytest.mark.parametrize("name", ENV)
def test_missing_env_variable(load, valid_config, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(ConfigError, match=f"{name} is missing in .env"):
        load(valid_config)

def test_api_id_must_be_a_number(load, valid_config, monkeypatch):
    monkeypatch.setenv("API_ID", "abc")
    with pytest.raises(ConfigError, match="API_ID in .env must be a number"):
        load(valid_config)
