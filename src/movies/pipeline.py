"""
The movies pipeline: what main.py runs with "python src/main.py movies".
"""
from queue import Queue

from movies.file_splitter import FileSplitter
from movies.folder_reader import FolderReader
from movies.mkv_splitter import MkvSplitter
from movies.telegram_api_client import MovieTelegramApiClient
from movies.tmdb_api_client import MovieTmdbApiClient

ITEM_LABEL = "movies"   # Shown in the summary: "Uploaded: X of Y movies"

def read_items(config, name_filter=""):
    return FolderReader(config.source_files_path, name_filter).read()

def create_stages(config, input_queue):
    """
    TMDB -> zip parts -> (optional) MKV parts -> upload, connected by queues.
    The queues after a split hold one movie: splitting is faster than uploading, and without a limit every movie
    would be split before the first upload ends and its parts deleted, which could fill the disk.
    """
    split_queue, upload_queue = Queue(), Queue(maxsize=1)
    stages = [MovieTmdbApiClient(input_queue, split_queue)]
    if config.mkv_parts_enabled:
        mkv_queue = Queue(maxsize=1)
        stages.append(FileSplitter(split_queue, mkv_queue, config.destination_files_path, config.telegram_size_limit_mb))
        stages.append(MkvSplitter(mkv_queue, upload_queue, config.telegram_size_limit_mb, config.mkvmerge_path))
    else:
        stages.append(FileSplitter(split_queue, upload_queue, config.destination_files_path, config.telegram_size_limit_mb))
    stages.append(MovieTelegramApiClient(upload_queue, config.telegram_group, config.mkv_parts_telegram_group))
    return stages
