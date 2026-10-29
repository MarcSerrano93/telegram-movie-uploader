"""
Stage 2 of the movies pipeline: moves each movie to its own folder in the destination, or splits it there
into zip parts if it is bigger than the Telegram upload limit.
"""
import os
import re
import shutil
import time
from queue import Queue

from core.constants import FileStatus, LogColor, Step
from core.pipeline_stage import PipelineStage
from core.utils import PermanentError, with_retries, format_size, format_duration
from core.zip_split import create_split_zip
from movies.movie import Movie

INVALID_FILE_NAME_CHARS = r'[<>:"/\\|?*]'

class FileSplitter(PipelineStage):
    step = Step.SPLIT
    log_name = "FileSplitter"
    log_color = LogColor.PINK

    def __init__(self, input_queue: Queue, output_queue: Queue, destination_folder: str, telegram_size_limit_mb: int):
        super().__init__(input_queue, output_queue)
        self.destination_folder = destination_folder
        self.telegram_size_limit_mb = telegram_size_limit_mb

    def _split_file(self, movie: Movie, destination_path: str):
        """
        Splits the movie into a temporary folder and renames it to destination_path only when the split succeeds,
        so an interrupted split is redone on the next run instead of uploading incomplete parts.
        """
        tmp_path = destination_path + ".partial"
        shutil.rmtree(tmp_path, ignore_errors=True)
        os.makedirs(tmp_path)

        file_title = re.sub(INVALID_FILE_NAME_CHARS, ".", movie.title)
        archive_path = os.path.join(tmp_path, f"{file_title} ({movie.year}).zip")
        self.log(f"Splitting \"{movie.file_name}\" ({format_size(os.path.getsize(movie.file_full_path))})...")
        start_time = time.time()
        parts = create_split_zip(movie.file_full_path, archive_path, self.telegram_size_limit_mb * 1024 * 1024)
        os.rename(tmp_path, destination_path)
        self.log(f"\"{movie.file_name}\" split into {len(parts)} parts in {format_duration(time.time() - start_time)}")

    def process(self, movie: Movie):
        """
        Small files are moved to the destination folder. Big ones are split there into zip parts, and the original
        stays in the source folder until the upload finishes (see MovieTelegramApiClient._move_original_to_destination).
        """
        if not os.path.isfile(movie.file_full_path):
            raise PermanentError(f"Source file not found: {movie.file_full_path}")

        # Named after the source file ("Movie (2024) {tmdb-112233}"): readable, and the same on every run
        destination_path = os.path.join(self.destination_folder, os.path.splitext(movie.file_name)[0])
        file_size = os.path.getsize(movie.file_full_path)
        if file_size > self.telegram_size_limit_mb * 1024 * 1024:
            if os.path.isdir(destination_path):
                # Split in a previous run whose upload did not finish
                self.log(f"File: \"{movie.file_name}\" already split")
            else:
                with_retries(self.step, movie.file_name, lambda: self._split_file(movie, destination_path))
        else:
            os.makedirs(destination_path, exist_ok=True)
            with_retries(self.step, movie.file_name, lambda: shutil.move(movie.file_full_path, os.path.join(destination_path, movie.file_name)))
            self.log(f"File: \"{movie.file_name}\" moved")

        movie.destination_path = destination_path
        movie.status = FileStatus.SPLIT
