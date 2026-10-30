"""
Last stage of the movies pipeline: uploads each movie to its own topic: the poster with its caption,
then the file or its parts. If enabled, it does the same in the MKV group, with the MKV parts.
"""
import asyncio
import os
import shutil

from core.constants import FileStatus
from core.mkv_split import list_mkv_parts
from core.telegram_api_client import TelegramApiClient, get_topic_link
from core.utils import PermanentError, report_warning, with_retries_async
from movies.movie import Movie

POSTER_CAPTION_START = "🎬|"    # Start of Movie.generate_telegram_poster_caption()

class MovieTelegramApiClient(TelegramApiClient):
    log_name = "MovieTelegramApiClient"

    def __init__(self, input_queue, telegram_group, mkv_parts_telegram_group=None):
        super().__init__(input_queue, telegram_group)
        self.mkv_parts_telegram_group = mkv_parts_telegram_group

    def _has_poster(self, messages):
        return any(message.photo or (message.message or "").startswith(POSTER_CAPTION_START) for message in messages)

    async def _send_poster(self, client, supergroup, topic_id, movie: Movie):
        # Checked on every attempt, in case a previous one was sent but its response was lost
        if self._has_poster(await self._get_topic_messages(client, supergroup, topic_id)):
            return
        caption = movie.generate_telegram_poster_caption()
        if movie.poster_path:
            await client.send_file(entity=supergroup, file=movie.poster_path, caption=caption, reply_to=topic_id, silent=True)
        else:
            await client.send_message(entity=supergroup, message=caption, reply_to=topic_id, silent=True)

    async def _send_general_poster(self, client, supergroup, topic_id, movie: Movie):
        """
        Posts the poster in the General topic, silently, with a link to the topic of the movie.
        """
        caption = movie.generate_telegram_poster_caption(get_topic_link(supergroup, topic_id))
        if movie.poster_path:
            await client.send_file(entity=supergroup, file=movie.poster_path, caption=caption, silent=True)
        else:
            await client.send_message(entity=supergroup, message=caption, silent=True)

    def _get_whole_file(self, movie: Movie):
        if not os.path.isfile(movie.file_full_path):
            raise PermanentError(f"File not found: {movie.file_full_path}")
        return os.path.dirname(movie.file_full_path), [movie.file_name]

    def _get_files_to_upload(self, movie: Movie):
        """
        Returns the folder and names of the files for the main group: the zip parts or, for small movies, the movie file.
        """
        if not movie.zip_parts_path:
            return self._get_whole_file(movie)
        parts = sorted(os.listdir(movie.zip_parts_path))
        if not parts:
            raise PermanentError(f"No zip parts found in {movie.zip_parts_path}")
        return movie.zip_parts_path, parts

    def _get_mkv_files_to_upload(self, movie: Movie):
        """
        Returns the folder and names of the files for the MKV group: the MKV parts or, for small movies, the movie file.
        """
        if not movie.mkv_parts_path:
            return self._get_whole_file(movie)
        return movie.mkv_parts_path, list_mkv_parts(movie.mkv_parts_path)

    async def _upload_item(self, client, supergroup, movie: Movie):
        """
        Full upload of one movie: to the main group and, if enabled, to the MKV group. Then moves the original to its
        folder in the destination and deletes the parts. If an upload fails, everything stays for the next run.
        The MKV group is looked up first, so a wrong link fails before uploading anything.
        """
        mkv_group = None
        if self.mkv_parts_telegram_group:
            mkv_group = await self._retry(movie, lambda: client.get_entity(self.mkv_parts_telegram_group))

        folder, file_names = self._get_files_to_upload(movie)
        await self._upload_to_group(client, supergroup, movie, folder, file_names, f"movie: {movie.title}")
        if mkv_group:
            folder, file_names = self._get_mkv_files_to_upload(movie)
            await self._upload_to_group(client, mkv_group, movie, folder, file_names, f"MKV of movie: {movie.title}")

        movie.status = FileStatus.UPLOADED
        await self._move_original_to_destination(movie)
        await self._delete_parts(movie)

    async def _upload_to_group(self, client, supergroup, movie: Movie, folder, file_names, label):
        """
        Fills the topic of the movie in one group: find or create it, send the poster (also to the General topic) and
        upload the files in albums of up to 10. Whatever is already in the topic is skipped.
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
            # The General poster goes first: if the topic poster then fails, the next run sends the General one
            # again, better than never sending it
            await self._retry(movie, lambda: self._send_general_poster(client, supergroup, topic_id, movie))
            await self._retry(movie, lambda: self._send_poster(client, supergroup, topic_id, movie))

        await self._upload_files(client, supergroup, topic_id, movie, label, folder, file_names, sent_files)

    async def _move_original_to_destination(self, movie: Movie):
        """
        Movies keep their original file in the source folder until every upload succeeds, so a failed one can be
        run again. Then it is moved to its folder in the destination, so the next run does not upload it again.
        """
        destination_file = os.path.join(movie.destination_path, movie.file_name)
        try:
            os.makedirs(movie.destination_path, exist_ok=True)
            await with_retries_async(self.step, movie.file_name, lambda: asyncio.to_thread(shutil.move, movie.file_full_path, destination_file))
            self.log(f"Original file: \"{movie.file_name}\" moved to {movie.destination_path}")
        except Exception as e:
            report_warning(self.step, movie.file_name, f"Uploaded, but could not move the original: {e}")

    async def _delete_parts(self, movie: Movie):
        """
        The parts are already in Telegram and can be created again from the original, so they only take up disk space.
        """
        for parts_path in (movie.zip_parts_path, movie.mkv_parts_path):
            if not parts_path:
                continue
            try:
                await with_retries_async(self.step, movie.file_name, lambda: asyncio.to_thread(shutil.rmtree, parts_path))
                self.log(f"Parts deleted: {parts_path}")
            except Exception as e:
                report_warning(self.step, movie.file_name, f"Uploaded, but could not delete {parts_path}: {e}")
