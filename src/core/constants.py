"""
Constants and enums shared by the whole project.
"""
import os
from enum import Enum

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Retries for operations that can fail temporarily (network, OS, Telegram...)
MAX_ATTEMPTS = 3
RETRY_DELAYS = [10, 30]   # Seconds to wait before attempt 2 and attempt 3

class FileStatus(Enum):
    NONE = 0
    PARSED = 1
    SPLIT = 2       # Split into the destination folder, if it was needed
    UPLOADED = 3
    ERROR = 4

class Step(Enum):
    READ = "READ"
    TMDB = "TMDB"
    SPLIT = "SPLIT"
    UPLOAD = "UPLOAD"
    UNKNOWN = "UNKNOWN"

class LogColor:
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    ORANGE = "\033[33m"
    BLUE = "\033[34m"
    PURPLE = "\033[35m"
    CYAN = "\033[36m"
    LIGHT_GREY = "\033[37m"
    DARK_GREY = "\033[90m"
    LIGHT_RED = "\033[91m"
    LIGHT_GREEN = "\033[92m"
    YELLOW = "\033[93m"
    LIGHT_BLUE = "\033[94m"
    PINK = "\033[95m"
    LIGHT_CYAN = "\033[96m"
    END = "\033[0m"
