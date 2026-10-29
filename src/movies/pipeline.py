"""
The movies pipeline: what main.py runs with "python src/main.py movies".
"""
from queue import Queue

from movies.file_splitter import FileSplitter
from movies.folder_reader import FolderReader
from movies.telegram_api_client import MovieTelegramApiClient
from movies.tmdb_api_client import MovieTmdbApiClient

ITEM_LABEL = "movies"   # Shown in the summary: "Uploaded: X of Y movies"

def read_items(config):
    return FolderReader(config.source_files_path).read()

def create_stages(config, input_queue):
    """
    TMDB -> move or split -> upload, connected by queues.
    """
    split_queue, upload_queue = Queue(), Queue()
    return [
        MovieTmdbApiClient(input_queue, split_queue),
        FileSplitter(split_queue, upload_queue, config.destination_files_path, config.telegram_size_limit_mb),
        MovieTelegramApiClient(upload_queue, config.telegram_group),
    ]
