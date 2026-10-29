"""
TMDB API requests shared by every mode, and the {tmdb-<id>} tag of file and folder names.
"""
import os
import re

import requests

from core.utils import PermanentError

API_URL = "https://api.themoviedb.org/3"
REQUEST_TIMEOUT = 30    # Seconds
LANGUAGE_ES = "es-ES"
LANGUAGE_EN = "en-US"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE_URL = "https://image.tmdb.org/t/p/w1280"
TMDB_ID_REGEX = re.compile(r"\{tmdb-(\d+)\}")

def parse_tmdb_id(text):
    """
    Returns the id of the {tmdb-<id>} tag in text (file name, folder name, topic title...), or None if there is no tag.
    """
    match = TMDB_ID_REGEX.search(text)
    return match.group(1) if match else None

def image_url(base_url, path):
    """
    Returns the full URL of a TMDB image, or "" if TMDB has no image.
    """
    return base_url + path if path else ""

def get_info(path, language, not_found_message):
    """
    Returns the JSON of a TMDB request, e.g. path "movie/603" or "tv/1396".
    A wrong id or API key raises PermanentError, other errors can be retried.
    """
    response = requests.get(f"{API_URL}/{path}", params={"api_key": os.getenv("API_KEY"), "language": language},
                            timeout=REQUEST_TIMEOUT)
    if response.status_code == 404:
        raise PermanentError(not_found_message)
    if response.status_code == 401:
        raise PermanentError("Invalid TMDB API key")
    response.raise_for_status()
    return response.json()
