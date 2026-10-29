"""
Loads config.json and checks it, together with the .env variables, before anything else runs.
"""
import json
import os

from constants import PROJECT_ROOT

CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.json")
TELEGRAM_MAX_SIZE_LIMIT_MB = 4000   # Telegram Premium upload limit per file

# JSON keys
SOURCE_FILES_PATH = "source_files_path"
DESTINATION_FILES_PATH = "destination_files_path"
TELEGRAM_SIZE_LIMIT_MB = "telegram_size_limit_mb"
TELEGRAM_MOVIE_GROUP = "telegram_movie_group"

# .env variables
ENV_VARIABLES = ("API_ID", "API_HASH", "PHONE_NUMBER", "API_KEY")

class ConfigError(Exception):
    """
    config.json or .env is missing, or has a wrong value.
    """

class Config:
    def __init__(self):
        config = self._load()
        self.source_files_path = self._get(config, SOURCE_FILES_PATH)
        self.destination_files_path = self._get(config, DESTINATION_FILES_PATH)
        self.telegram_size_limit_mb = self._get(config, TELEGRAM_SIZE_LIMIT_MB)
        self.telegram_movie_group = self._get(config, TELEGRAM_MOVIE_GROUP)
        self._validate()

    def _load(self):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        except FileNotFoundError:
            raise ConfigError(f"{CONFIG_FILE_PATH} not found")
        except json.JSONDecodeError as e:
            raise ConfigError(f"config.json is not valid JSON: {e}")
        if not isinstance(config, dict):
            raise ConfigError("config.json must contain a JSON object")
        return config

    def _get(self, config, key):
        if key not in config:
            raise ConfigError(f"missing key \"{key}\"")
        return config[key]

    def _validate(self):
        if not os.path.isdir(self.source_files_path):
            raise ConfigError(f"{SOURCE_FILES_PATH} does not exist: {self.source_files_path}")
        if not os.path.isdir(self.destination_files_path):
            raise ConfigError(f"{DESTINATION_FILES_PATH} does not exist: {self.destination_files_path}")
        # type() instead of isinstance(), so true/false are not accepted as numbers
        if type(self.telegram_size_limit_mb) is not int or not 1 <= self.telegram_size_limit_mb <= TELEGRAM_MAX_SIZE_LIMIT_MB:
            raise ConfigError(f"{TELEGRAM_SIZE_LIMIT_MB} must be a whole number between 1 and {TELEGRAM_MAX_SIZE_LIMIT_MB} (MB)")
        if self.telegram_movie_group is None or str(self.telegram_movie_group).strip() == "":
            raise ConfigError(f"{TELEGRAM_MOVIE_GROUP} is empty")
        for name in ENV_VARIABLES:
            if not os.getenv(name):
                raise ConfigError(f"{name} is missing in .env")
        if not os.getenv("API_ID").isdigit():
            raise ConfigError("API_ID in .env must be a number")
