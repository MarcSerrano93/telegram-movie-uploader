"""
The TV pipeline: what main.py runs with "python src/main.py tv".
"""
from queue import Queue

from tv.folder_reader import ShowFolderReader
from tv.telegram_api_client import ShowTelegramApiClient
from tv.tmdb_api_client import ShowTmdbApiClient

ITEM_LABEL = "TV shows"   # Shown in the summary: "Uploaded: X of Y TV shows"

def read_items(config):
    return ShowFolderReader(config.source_files_path, config.telegram_size_limit_mb).read()

def create_stages(config, input_queue):
    """
    TMDB -> upload, connected by a queue. No split stage: episodes bigger than the limit are skipped while reading.
    """
    upload_queue = Queue()
    return [
        ShowTmdbApiClient(input_queue, upload_queue),
        ShowTelegramApiClient(upload_queue, config.telegram_group),
    ]
