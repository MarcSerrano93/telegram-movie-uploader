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

@pytest.fixture
def mkv_config(valid_config, monkeypatch):
    """
    A valid config with the MKV parts enabled and mkvmerge installed.
    """
    monkeypatch.setattr(config, "find_mkvmerge", lambda: "mkvmerge")
    valid_config["movies"].update(mkv_parts_enabled=True, mkv_parts_telegram_group="https://t.me/+mkv")
    return valid_config

def test_mkv_parts_are_off_by_default(load, valid_config):
    loaded = load(valid_config)
    assert (loaded.mkv_parts_enabled, loaded.mkv_parts_telegram_group) == (False, None)

def test_mkv_parts_enabled(load, mkv_config):
    loaded = load(mkv_config)
    assert (loaded.mkv_parts_enabled, loaded.mkv_parts_telegram_group) == (True, "https://t.me/+mkv")

def test_mkv_parts_disabled_ignores_the_group_and_mkvmerge(load, mkv_config, monkeypatch):
    monkeypatch.setattr(config, "find_mkvmerge", lambda: None)
    mkv_config["movies"]["mkv_parts_enabled"] = False
    loaded = load(mkv_config)
    assert (loaded.mkv_parts_enabled, loaded.mkv_parts_telegram_group) == (False, None)

@pytest.mark.parametrize("value", ["true", 1, None])
def test_mkv_parts_enabled_must_be_a_boolean(load, mkv_config, value):
    mkv_config["movies"]["mkv_parts_enabled"] = value
    with pytest.raises(ConfigError, match="movies.mkv_parts_enabled must be true or false"):
        load(mkv_config)

def test_mkv_parts_need_their_group(load, mkv_config):
    del mkv_config["movies"]["mkv_parts_telegram_group"]
    with pytest.raises(ConfigError, match="missing key \"movies.mkv_parts_telegram_group\""):
        load(mkv_config)

@pytest.mark.parametrize("group", ["", "   ", None])
def test_mkv_parts_group_empty(load, mkv_config, group):
    mkv_config["movies"]["mkv_parts_telegram_group"] = group
    with pytest.raises(ConfigError, match="movies.mkv_parts_telegram_group is empty"):
        load(mkv_config)

def test_mkv_parts_group_must_be_different(load, mkv_config):
    mkv_config["movies"]["mkv_parts_telegram_group"] = mkv_config["movies"]["telegram_group"]
    with pytest.raises(ConfigError, match="must be different from movies.telegram_group"):
        load(mkv_config)

def test_mkv_parts_need_mkvmerge(load, mkv_config, monkeypatch):
    monkeypatch.setattr(config, "find_mkvmerge", lambda: None)
    with pytest.raises(ConfigError, match="mkvmerge was not found: install MKVToolNix"):
        load(mkv_config)

def test_mkvmerge_is_found_automatically(load, mkv_config):
    assert load(mkv_config).mkvmerge_path == "mkvmerge"

def test_mkvmerge_path_is_used_when_set(load, mkv_config, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "find_mkvmerge", lambda: None)
    path = tmp_path / "mkvmerge.exe"
    path.write_bytes(b"")
    mkv_config["movies"]["mkvmerge_path"] = str(path)
    assert load(mkv_config).mkvmerge_path == str(path)

def test_mkvmerge_path_must_exist(load, mkv_config, tmp_path):
    mkv_config["movies"]["mkvmerge_path"] = str(tmp_path / "missing.exe")
    with pytest.raises(ConfigError, match="movies.mkvmerge_path does not exist"):
        load(mkv_config)

def test_mkvmerge_path_is_ignored_when_disabled(load, mkv_config, tmp_path):
    mkv_config["movies"].update(mkv_parts_enabled=False, mkvmerge_path=str(tmp_path / "missing.exe"))
    assert load(mkv_config).mkvmerge_path is None

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
