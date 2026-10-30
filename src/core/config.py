"""
Loads config.json and checks the section of the mode being run, together with the .env variables.
"""
import json
import os

from core.constants import PROJECT_ROOT
from core.mkv_split import find_mkvmerge

CONFIG_FILE_PATH = os.path.join(PROJECT_ROOT, "config.json")
TELEGRAM_MAX_SIZE_LIMIT_MB = 4000   # Telegram Premium upload limit per file

# JSON keys
TELEGRAM_SIZE_LIMIT_MB = "telegram_size_limit_mb"
SOURCE_FILES_PATH = "source_files_path"
DESTINATION_FILES_PATH = "destination_files_path"
TELEGRAM_GROUP = "telegram_group"
MKV_PARTS_ENABLED = "mkv_parts_enabled"                 # Optional, movies only
MKV_PARTS_TELEGRAM_GROUP = "mkv_parts_telegram_group"   # Only needed if enabled
MKVMERGE_PATH = "mkvmerge_path"                         # Optional, for a mkvmerge that find_mkvmerge() does not find

# Required keys of the section of each mode. Only the section of the mode being run is checked
MODE_KEYS = {
    "movies": (SOURCE_FILES_PATH, DESTINATION_FILES_PATH, TELEGRAM_GROUP),
    "tv": (SOURCE_FILES_PATH, TELEGRAM_GROUP),
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
        self.mkv_parts_enabled = section.get(MKV_PARTS_ENABLED, False) if mode == "movies" else False
        self.mkv_parts_telegram_group = self._get(section, MKV_PARTS_TELEGRAM_GROUP, mode) if self.mkv_parts_enabled is True else None
        self.mkvmerge_path = section.get(MKVMERGE_PATH) if self.mkv_parts_enabled is True else None
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
        # Before the modes, the movie keys were at the top level
        if mode not in config and SOURCE_FILES_PATH in config:
            raise ConfigError("config.json has the old format: move the movie keys into a \"movies\" section, see config.example.json")
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
        self._validate_mkv_parts()
        for name in ENV_VARIABLES:
            if not os.getenv(name):
                raise ConfigError(f"{name} is missing in .env")
        if not os.getenv("API_ID").isdigit():
            raise ConfigError("API_ID in .env must be a number")

    def _validate_mkv_parts(self):
        if type(self.mkv_parts_enabled) is not bool:
            raise ConfigError(f"{self._name(MKV_PARTS_ENABLED, self.mode)} must be true or false")
        if not self.mkv_parts_enabled:
            return
        group_name = self._name(MKV_PARTS_TELEGRAM_GROUP, self.mode)
        if self.mkv_parts_telegram_group is None or str(self.mkv_parts_telegram_group).strip() == "":
            raise ConfigError(f"{group_name} is empty")
        if self.mkv_parts_telegram_group == self.telegram_group:
            raise ConfigError(f"{group_name} must be different from {self._name(TELEGRAM_GROUP, self.mode)}")
        if self.mkvmerge_path:
            if not os.path.isfile(self.mkvmerge_path):
                raise ConfigError(f"{self._name(MKVMERGE_PATH, self.mode)} does not exist: {self.mkvmerge_path}")
            return
        self.mkvmerge_path = find_mkvmerge()
        if self.mkvmerge_path is None:
            raise ConfigError(f"{self._name(MKV_PARTS_ENABLED, self.mode)} is on but mkvmerge was not found: install MKVToolNix from "
                              f"https://mkvtoolnix.download or set {self._name(MKVMERGE_PATH, self.mode)}")
