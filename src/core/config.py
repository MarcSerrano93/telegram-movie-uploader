"""
Loads config.json and checks the section of the mode being run, together with the .env variables.
"""
import json
import os

from core.constants import PROJECT_ROOT

CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.json")
TELEGRAM_MAX_SIZE_LIMIT_MB = 4000   # Telegram Premium upload limit per file

# JSON keys
TELEGRAM_SIZE_LIMIT_MB = "telegram_size_limit_mb"
SOURCE_FILES_PATH = "source_files_path"
DESTINATION_FILES_PATH = "destination_files_path"
TELEGRAM_GROUP = "telegram_group"

# Keys of the section of each mode. Only the section of the mode being run is checked
MODE_KEYS = {
    "movies": (SOURCE_FILES_PATH, DESTINATION_FILES_PATH, TELEGRAM_GROUP),
}
MODES = tuple(MODE_KEYS)

# .env variables
ENV_VARIABLES = ("API_ID", "API_HASH", "PHONE_NUMBER", "API_KEY")

class ConfigError(Exception):
    """
    config.json or .env is missing, or has a wrong value.
    """

class Config:
    def __init__(self, mode):
        config = self._load()
        self.mode = mode
        self.telegram_size_limit_mb = self._get(config, TELEGRAM_SIZE_LIMIT_MB)
        section = self._get_section(config, mode)
        self.source_files_path = self._get(section, SOURCE_FILES_PATH, mode)
        self.destination_files_path = self._get(section, DESTINATION_FILES_PATH, mode) if DESTINATION_FILES_PATH in MODE_KEYS[mode] else None
        self.telegram_group = self._get(section, TELEGRAM_GROUP, mode)
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

    def _get(self, config, key, section=None):
        if key not in config:
            raise ConfigError(f"missing key \"{self._name(key, section)}\"")
        return config[key]

    def _get_section(self, config, mode):
        if mode not in config and SOURCE_FILES_PATH in config:
            raise ConfigError(f"config.json has the old format: move the movie keys into a \"{mode}\" section, see config.example.json")
        section = self._get(config, mode)
        if not isinstance(section, dict):
            raise ConfigError(f"\"{mode}\" must be a JSON object")
        return section

    def _name(self, key, section=None):
        return f"{section}.{key}" if section else key

    def _validate(self):
        for key in (SOURCE_FILES_PATH, DESTINATION_FILES_PATH):
            path = getattr(self, key)
            if path is not None and not os.path.isdir(path):
                raise ConfigError(f"{self._name(key, self.mode)} does not exist: {path}")
        # type() instead of isinstance(), so true/false are not accepted as numbers
        if type(self.telegram_size_limit_mb) is not int or not 1 <= self.telegram_size_limit_mb <= TELEGRAM_MAX_SIZE_LIMIT_MB:
            raise ConfigError(f"{TELEGRAM_SIZE_LIMIT_MB} must be a whole number between 1 and {TELEGRAM_MAX_SIZE_LIMIT_MB} (MB)")
        if self.telegram_group is None or str(self.telegram_group).strip() == "":
            raise ConfigError(f"{self._name(TELEGRAM_GROUP, self.mode)} is empty")
        for name in ENV_VARIABLES:
            if not os.getenv(name):
                raise ConfigError(f"{name} is missing in .env")
        if not os.getenv("API_ID").isdigit():
            raise ConfigError("API_ID in .env must be a number")
