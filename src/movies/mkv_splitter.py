"""
Optional stage of the movies pipeline, after FileSplitter: splits the movies bigger than the Telegram upload limit
into playable MKV parts, for the MKV group. Smaller movies go to that group as they are.
"""
import os
import shutil
import time
from queue import Queue

from core.constants import LogColor, Step
from core.mkv_split import create_mkv_parts
from core.pipeline_stage import PipelineStage
from core.utils import PermanentError, with_retries, format_size, format_duration
from movies.movie import Movie

MKV_PARTS_FOLDER = "mkv_parts"
PART_SIZE_RATIO = 0.95     # mkvmerge cuts at the first keyframe after the size asked, this keeps the parts under the limit

class MkvSplitter(PipelineStage):
    step = Step.SPLIT
    log_name = "MkvSplitter"
    log_color = LogColor.PURPLE

    def __init__(self, input_queue: Queue, output_queue: Queue, telegram_size_limit_mb: int, mkvmerge_path: str):
        super().__init__(input_queue, output_queue)
        self.telegram_size_limit_mb = telegram_size_limit_mb
        self.mkvmerge_path = mkvmerge_path

    def _split_file(self, movie: Movie, parts_path: str):
        """
        Splits the movie into a temporary folder and renames it to parts_path only when the split succeeds,
        so an interrupted split is redone on the next run instead of uploading incomplete parts.
        """
        tmp_path = parts_path + ".partial"
        shutil.rmtree(tmp_path, ignore_errors=True)
        os.makedirs(tmp_path)

        # mkvmerge reads % in the output name as a number format
        base_name = f"{movie.get_file_title()} {{tmdb-{movie.tmdb_id}}}".replace("%", ".")
        self.log(f"Creating MKV parts of \"{movie.file_name}\" ({format_size(os.path.getsize(movie.file_full_path))})...")
        start_time = time.time()
        part_size_mb = max(int(self.telegram_size_limit_mb * PART_SIZE_RATIO), 1)
        parts = create_mkv_parts(self.mkvmerge_path, movie.file_full_path, tmp_path, base_name, part_size_mb)
        for part in parts:
            if os.path.getsize(part) > self.telegram_size_limit_mb * 1024 * 1024:
                raise PermanentError(f"MKV part \"{os.path.basename(part)}\" ({format_size(os.path.getsize(part))}) is bigger than the Telegram limit")
        os.rename(tmp_path, parts_path)
        self.log(f"\"{movie.file_name}\" split into {len(parts)} MKV parts in {format_duration(time.time() - start_time)}")

    def process(self, movie: Movie):
        if os.path.getsize(movie.file_full_path) <= self.telegram_size_limit_mb * 1024 * 1024:
            return  # Small files are uploaded whole
        parts_path = os.path.join(movie.destination_path, MKV_PARTS_FOLDER)
        if os.path.isdir(parts_path):
            # Split in a previous run whose upload did not finish
            self.log(f"File: \"{movie.file_name}\" already has its MKV parts")
        else:
            with_retries(self.step, movie.file_name, lambda: self._split_file(movie, parts_path))
        movie.mkv_parts_path = parts_path
