"""
Stage 3 of the movies pipeline: uploads each movie to its own topic: the poster with its caption,
then the file or its parts.
"""
import asyncio
import os
import re
import shutil

from core.constants import FileStatus
from core.telegram_api_client import TelegramApiClient
from core.utils import PermanentError, report_warning, with_retries_async
from movies.movie import Movie

SPLIT_PART_REGEX = re.compile(r"\.zip\.\d{3}$") # Zip parts: "Movie (2024).zip.001"
POSTER_CAPTION_START = "🎬|"                    # Start of Movie.generate_telegram_poster_caption()

class MovieTelegramApiClient(TelegramApiClient):
    log_name = "MovieTelegramApiClient"

    def _has_poster(self, messages):
        return any(message.photo or (message.message or "").startswith(POSTER_CAPTION_START) for message in messages)

    async def _send_poster(self, client, supergroup, topic_id, movie: Movie):
        # Checked on every attempt, in case a previous one was sent but its response was lost
        if self._has_poster(await self._get_topic_messages(client, supergroup, topic_id)):
            return
        caption = movie.generate_telegram_poster_caption()
        if movie.poster_path:
            await client.send_file(entity=supergroup, file=movie.poster_path, caption=caption, reply_to=topic_id)
        else:
            await client.send_message(entity=supergroup, message=caption, reply_to=topic_id)

    def _get_files_to_upload(self, movie: Movie):
        """
        Returns the names of the files to upload, in order: the zip parts if the movie was split, otherwise the movie file.
        """
        file_names = sorted(entry.name for entry in os.scandir(movie.destination_path) if entry.is_file())
        parts = [name for name in file_names if SPLIT_PART_REGEX.search(name)]
        upload_names = parts or [movie.file_name]
        for name in upload_names:
            if not os.path.isfile(os.path.join(movie.destination_path, name)):
                raise PermanentError(f"File not found: {os.path.join(movie.destination_path, name)}")
        return upload_names

    async def _upload_item(self, client, supergroup, movie: Movie):
        """
        Full upload of one movie: find or create its topic, send the poster, upload the files in albums of up to 10
        and move the original next to its parts. Whatever is already in the topic is skipped.
        """
        topic_id, created = await self._retry(movie, lambda: self._find_or_create_topic(client, supergroup, movie.title, movie.year, movie.tmdb_id))
        if created:
            poster_sent, sent_files = False, set()
        else:
            messages = await self._retry(movie, lambda: self._get_topic_messages(client, supergroup, topic_id))
            poster_sent, sent_files = self._has_poster(messages), self._get_file_names(messages)

        if not poster_sent:
            if not movie.poster_path:
                report_warning(self.step, movie.file_name, "No poster in TMDB, info sent as text")
            await self._retry(movie, lambda: self._send_poster(client, supergroup, topic_id, movie))

        file_names = self._get_files_to_upload(movie)
        await self._upload_files(client, supergroup, topic_id, movie, f"movie: {movie.title}", movie.destination_path, file_names, sent_files)

        movie.status = FileStatus.UPLOADED
        await self._move_original_to_destination(movie)

    async def _move_original_to_destination(self, movie: Movie):
        """
        Split movies keep their original file in the source folder until the upload succeeds.
        Then it is moved next to its parts, so the next run does not upload it again.
        """
        if not os.path.isfile(movie.file_full_path):
            return  # Small files were already moved by the FileSplitter
        destination_file = os.path.join(movie.destination_path, movie.file_name)
        try:
            await with_retries_async(self.step, movie.file_name, lambda: asyncio.to_thread(shutil.move, movie.file_full_path, destination_file))
            self.log(f"Original file: \"{movie.file_name}\" moved to {movie.destination_path}")
        except Exception as e:
            report_warning(self.step, movie.file_name, f"Uploaded, but could not move the original: {e}")
