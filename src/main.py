"""
Entry point: loads config.json and .env, reads the source folder and runs the three pipeline stages
(TMDB -> split -> upload) in parallel threads, then prints the summary.
"""
import os
from queue import Queue

from dotenv import load_dotenv

import shared_state
from config import Config, ConfigError
from constants import PROJECT_ROOT
from file_splitter import FileSplitter
from folder_reader import FolderReader
from telegram_api_client import TelegramApiClient
from tmdb_api_client import TmdbApiClient
from utils import print_summary

def main():
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    try:
        config = Config()
    except ConfigError as e:
        print(f"Invalid config file: {e}")
        return
    shared_state.movies.extend(FolderReader(config.source_files_path).read())

    # Each stage passes the movies it processed successfully to the next one through a queue
    tmdb_queue, split_queue, upload_queue = Queue(), Queue(), Queue()
    for movie in shared_state.movies:
        tmdb_queue.put(movie)
    tmdb_queue.put(None)    # End of the list

    stages = [
        TmdbApiClient(tmdb_queue, split_queue),
        FileSplitter(split_queue, upload_queue, config.destination_files_path, config.telegram_size_limit_mb),
        TelegramApiClient(upload_queue, config.telegram_movie_group),
    ]
    for stage in stages:
        stage.start()
    for stage in stages:
        stage.join()

    print_summary()

if __name__ == "__main__":
    main()
