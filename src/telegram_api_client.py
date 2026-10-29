"""
Stage 3 of the pipeline: uploads each movie to its own topic in the Telegram group.
Re-running is safe: existing topics, posters and files are found and skipped.
"""
import asyncio
import logging
import os
import re
import shutil
import time
from queue import Queue

import telethon
from FastTelethonhelper import upload_file
from telethon import TelegramClient
from telethon.errors import ForbiddenError
from telethon.tl.functions.messages import GetForumTopicsRequest, CreateForumTopicRequest
from telethon.tl.types import ForumTopic, UpdateNewChannelMessage

from constants import FileStatus, LogColor, Step, PROJECT_ROOT
from movie import Movie
from pipeline_stage import PipelineStage
from utils import PermanentError, report_warning, with_retries_async, format_size, format_duration

SESSION_PATH = os.path.join(PROJECT_ROOT, "uploader")   # uploader.session, keeps the Telegram login
TOPIC_ICON_EMOJI_ID = 5368653135101310687
TOPIC_TITLE_MAX_LENGTH = 128
ALBUM_MAX_FILES = 10                            # Telegram limit of files per album
PROGRESS_STEP_PERCENT = 10
SPLIT_PART_REGEX = re.compile(r"\.zip\.\d{3}$") # 7z parts: "Movie (2024).zip.001"
POSTER_CAPTION_START = "🎬|"                    # Start of Movie.generate_telegram_poster_caption()
PERMANENT_TELEGRAM_ERRORS = (ForbiddenError,)   # No rights to create topics or post: retrying won't help

telethon.errors.rpc_errors_re += (("FLOOD_PREMIUM_WAIT_(\\d+)", telethon.errors.FloodWaitError),)
# Telethon warns about problems it handles itself (e.g. FastTelethon closing its extra connections after each file).
# What it cannot handle is raised as an exception, which our retries and the summary report
logging.getLogger("telethon").setLevel(logging.ERROR)

class TelegramApiClient(PipelineStage):
    step = Step.UPLOAD
    log_name = "TelegramApiClient"
    log_color = LogColor.LIGHT_CYAN

    def __init__(self, input_queue: Queue, telegram_movie_group):
        super().__init__(input_queue)
        self.telegram_movie_group = telegram_movie_group

    async def _retry(self, movie: Movie, operation):
        return await with_retries_async(self.step, movie.file_name, operation, PERMANENT_TELEGRAM_ERRORS)

    async def _find_topic(self, client, supergroup, tmdb_id):
        """
        Returns the id of the topic tagged {tmdb-<tmdb_id>}, or None if there is none.
        """
        response = await client(GetForumTopicsRequest(
            peer=supergroup,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
            q=f"{{tmdb-{tmdb_id}}}",
        ))
        # The search could also return similar titles, so check the exact tag
        for topic in response.topics:
            if isinstance(topic, ForumTopic) and Movie.parse_tmdb_id(topic.title) == tmdb_id:
                return topic.id
        return None

    async def _find_or_create_topic(self, client, supergroup, movie: Movie):
        """
        Returns (topic id, whether it was created now).
        It searches first on every attempt, so if an attempt created the topic but its response was lost,
        the retry finds it instead of creating a duplicate.
        """
        topic_id = await self._find_topic(client, supergroup, movie.tmdb_id)
        if topic_id is not None:
            return topic_id, False

        # Cut the title if needed, but always keep the year and the tag, the tag is how the topic is found
        tag = f" ({movie.year}) {{tmdb-{movie.tmdb_id}}}"
        topic_name = movie.title[:TOPIC_TITLE_MAX_LENGTH - len(tag)] + tag
        response = await client(CreateForumTopicRequest(
            peer=supergroup,
            title=topic_name,
            icon_emoji_id=TOPIC_ICON_EMOJI_ID,
        ))
        for update in response.updates:
            if isinstance(update, UpdateNewChannelMessage):
                self.log(f"Topic {topic_name} created")
                return update.message.id, True
        raise RuntimeError(f"Could not get the id of the new topic {topic_name}")

    async def _get_topic_content(self, client, supergroup, topic_id):
        """
        Returns (whether the poster is already sent, names of the files already sent) for the topic.
        """
        poster_sent = False
        file_names = set()
        async for message in client.iter_messages(supergroup, reply_to=topic_id):
            if message.photo or (message.message or "").startswith(POSTER_CAPTION_START):
                poster_sent = True
            elif message.file and message.file.name:
                file_names.add(message.file.name)
        return poster_sent, file_names

    async def _send_poster(self, client, supergroup, topic_id, movie: Movie):
        # Checked on every attempt, in case a previous one was sent but its response was lost
        poster_sent, _ = await self._get_topic_content(client, supergroup, topic_id)
        if poster_sent:
            return
        caption = movie.generate_telegram_poster_caption()
        if movie.poster_path:
            await client.send_file(entity=supergroup, file=movie.poster_path, caption=caption, reply_to=topic_id)
        else:
            await client.send_message(entity=supergroup, message=caption, reply_to=topic_id)

    def _get_files_to_upload(self, movie: Movie):
        """
        Returns the names of the files to upload, in order: the 7z parts if the movie was split, otherwise the movie file.
        """
        file_names = sorted(entry.name for entry in os.scandir(movie.destination_path) if entry.is_file())
        parts = [name for name in file_names if SPLIT_PART_REGEX.search(name)]
        upload_names = parts or [movie.file_name]
        for name in upload_names:
            if not os.path.isfile(os.path.join(movie.destination_path, name)):
                raise PermanentError(f"File not found: {os.path.join(movie.destination_path, name)}")
        return upload_names

    def _make_progress_printer(self, file_name, part_label):
        start_time = time.time()
        last_step = -1
        def print_progress(current, total):
            nonlocal last_step
            step = int(100 * current / total) // PROGRESS_STEP_PERCENT
            if step == last_step:
                return
            last_step = step
            speed = current / max(time.time() - start_time, 0.001)
            self.log(f"\"{file_name}\" ({part_label}): {step * PROGRESS_STEP_PERCENT}% - {format_size(current)} of {format_size(total)} - {format_size(speed)}/s")
        return print_progress

    async def _upload_part(self, client, file_path, part_label):
        """
        Uploads the file in parallel with FastTelethon. It is not visible in Telegram until it is sent in a message.
        """
        file_name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            return await upload_file(client, f, file_name, self._make_progress_printer(file_name, part_label))

    async def _send_album(self, client, supergroup, topic_id, file_names, uploaded_files):
        # Checked on every attempt, in case a previous one was sent but its response was lost
        _, sent_files = await self._get_topic_content(client, supergroup, topic_id)
        if all(name in sent_files for name in file_names):
            return
        # A single file (small movie, or the last part alone) goes as a normal document, not as an album of one
        files = uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files
        await client.send_file(entity=supergroup, file=files, force_document=True, reply_to=topic_id)

    async def _upload_movie(self, client, supergroup, movie: Movie):
        """
        Full upload of one movie: find or create its topic, send the poster, upload the files in albums of up to 10
        and move the original next to its parts. Whatever is already in the topic is skipped.
        """
        topic_id, created = await self._retry(movie, lambda: self._find_or_create_topic(client, supergroup, movie))
        if created:
            poster_sent, sent_files = False, set()
        else:
            poster_sent, sent_files = await self._retry(movie, lambda: self._get_topic_content(client, supergroup, topic_id))

        if not poster_sent:
            if not movie.poster_path:
                report_warning(self.step, movie.file_name, "No poster in TMDB, info sent as text")
            await self._retry(movie, lambda: self._send_poster(client, supergroup, topic_id, movie))

        file_names = self._get_files_to_upload(movie)
        pending = [name for name in file_names if name not in sent_files]
        if not pending:
            self.log(f"\"{movie.file_name}\": all {len(file_names)} file(s) already in Telegram, nothing to upload")
        else:
            if len(pending) < len(file_names):
                self.log(f"\"{movie.file_name}\": resuming, {len(file_names) - len(pending)} of {len(file_names)} file(s) already in Telegram")
            self.log(f"Uploading movie: {movie.title} to Telegram")
            start_time = time.time()
            total_size = 0
            # Each album is uploaded and sent before the next one, so a failed send only retries its own files
            for i in range(0, len(pending), ALBUM_MAX_FILES):
                album_names = pending[i:i + ALBUM_MAX_FILES]
                uploaded_files = []
                for name in album_names:
                    file_path = os.path.join(movie.destination_path, name)
                    part_label = f"part {file_names.index(name) + 1}/{len(file_names)}"
                    uploaded_files.append(await self._retry(movie, lambda: self._upload_part(client, file_path, part_label)))
                    total_size += os.path.getsize(file_path)
                await self._retry(movie, lambda: self._send_album(client, supergroup, topic_id, album_names, uploaded_files))
            elapsed_time = max(time.time() - start_time, 0.001)
            self.log(f"Movie: {movie.title} uploaded in {format_duration(elapsed_time)} ({format_size(total_size)}, {format_size(total_size / elapsed_time)}/s)")

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

    async def _upload_movies(self):
        client = TelegramClient(SESSION_PATH, int(os.getenv("API_ID")), os.getenv("API_HASH"))
        supergroup = None
        try:
            try:
                await client.start(os.getenv("PHONE_NUMBER"))
                supergroup = await client.get_entity(self.telegram_movie_group)
            except Exception as e:
                # Keep reading the queue so every movie that reaches this step is reported
                startup_error = e
                print(f"{LogColor.LIGHT_RED}[{self.log_name}] Error connecting to the supergroup: {e}{LogColor.END}")

            # Wait for the next movie in another thread, so the event loop keeps the connection alive
            while (movie := await asyncio.to_thread(self.input_queue.get)) is not None:
                if supergroup is None:
                    self.fail(movie, f"Could not connect to the Telegram group: {startup_error}")
                    continue
                try:
                    await self._upload_movie(client, supergroup, movie)
                except Exception as e:
                    self.fail(movie, e)
        finally:
            await client.disconnect()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._upload_movies())
        finally:
            loop.close()
        self.log("Closing thread")
