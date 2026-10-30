"""
Base of the upload stage: connects to the Telegram group and has what every mode needs to fill its topics
(find or create the topic, read what is already there, upload files in albums). Each mode defines
in _upload_item what goes into its topics. Re-running is safe: what is already in a topic is skipped.
"""
import asyncio
import logging
import os
import time
from queue import Queue

import telethon
from FastTelethonhelper import upload_file
from telethon import TelegramClient
from telethon.errors import ForbiddenError
from telethon.tl.functions.messages import GetForumTopicsRequest, CreateForumTopicRequest
from telethon.tl.types import ForumTopic, UpdateNewChannelMessage

from core.constants import Step, LogColor, PROJECT_ROOT
from core.pipeline_stage import PipelineStage
from core.utils import with_retries_async, format_size, format_duration

SESSION_PATH = os.path.join(PROJECT_ROOT, "uploader")   # uploader.session, keeps the Telegram login
TOPIC_ICON_EMOJI_ID = 5368653135101310687
TOPIC_TITLE_MAX_LENGTH = 128
ALBUM_MAX_FILES = 10                            # Telegram limit of files per album
PROGRESS_STEP_PERCENT = 10
PERMANENT_TELEGRAM_ERRORS = (ForbiddenError,)   # No rights to create topics or post: retrying won't help
TOPIC_LINK_URL = "https://t.me/c/{group_id}/{topic_id}"

telethon.errors.rpc_errors_re += (("FLOOD_PREMIUM_WAIT_(\\d+)", telethon.errors.FloodWaitError),)
# Telethon warns about problems it handles itself (e.g. FastTelethon closing its extra connections after each file).
# What it cannot handle is raised as an exception, which our retries and the summary report
logging.getLogger("telethon").setLevel(logging.ERROR)

def get_topic_link(supergroup, topic_id):
    return TOPIC_LINK_URL.format(group_id=supergroup.id, topic_id=topic_id)

class TelegramApiClient(PipelineStage):
    step = Step.UPLOAD
    log_name = "TelegramApiClient"
    log_color = LogColor.LIGHT_CYAN

    def __init__(self, input_queue: Queue, telegram_group):
        super().__init__(input_queue)
        self.telegram_group = telegram_group

    async def _upload_item(self, client, supergroup, item):
        """
        Uploads one item to its topic and sets its status to UPLOADED. Defined by each mode.
        """
        raise NotImplementedError

    async def _retry(self, item, operation):
        return await with_retries_async(self.step, item.file_name, operation, PERMANENT_TELEGRAM_ERRORS)

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
        # The search could also return similar titles, so check the exact tag ("{tmdb-1}" is not in "{tmdb-12}")
        tag = f"{{tmdb-{tmdb_id}}}"
        for topic in response.topics:
            if isinstance(topic, ForumTopic) and tag in topic.title:
                return topic.id
        return None

    async def _find_or_create_topic(self, client, supergroup, title, year, tmdb_id):
        """
        Returns (topic id, whether it was created now). The topic is named "<title> (<year>) {tmdb-<id>}".
        It searches first on every attempt, so if an attempt created the topic but its response was lost,
        the retry finds it instead of creating a duplicate.
        """
        topic_id = await self._find_topic(client, supergroup, tmdb_id)
        if topic_id is not None:
            return topic_id, False

        # Cut the title if needed, but always keep the year and the tag, the tag is how the topic is found
        tag = f" ({year}) {{tmdb-{tmdb_id}}}"
        topic_name = title[:TOPIC_TITLE_MAX_LENGTH - len(tag)] + tag
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

    async def _get_topic_messages(self, client, supergroup, topic_id):
        return [message async for message in client.iter_messages(supergroup, reply_to=topic_id)]

    def _get_file_names(self, messages):
        """
        Returns the names of the files (documents, not photos) in the messages.
        """
        return {message.file.name for message in messages if not message.photo and message.file and message.file.name}

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
        sent_files = self._get_file_names(await self._get_topic_messages(client, supergroup, topic_id))
        if all(name in sent_files for name in file_names):
            return
        # A single file (small movie, or the last part alone) goes as a normal document, not as an album of one
        files = uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files
        await client.send_file(entity=supergroup, file=files, force_document=True, reply_to=topic_id, silent=True)

    async def _upload_files(self, client, supergroup, topic_id, item, label, folder, file_names, sent_files):
        """
        Uploads the files of folder that are not in sent_files, in order and in albums of up to 10.
        label: what is uploaded, for the logs (e.g. "movie: <title>").
        """
        pending = [name for name in file_names if name not in sent_files]
        if not pending:
            self.log(f"{label}: all {len(file_names)} file(s) already in Telegram, nothing to upload")
            return
        if len(pending) < len(file_names):
            self.log(f"{label}: resuming, {len(file_names) - len(pending)} of {len(file_names)} file(s) already in Telegram")
        self.log(f"Uploading {label} to Telegram")
        start_time = time.time()
        total_size = 0
        # Each album is uploaded and sent before the next one, so a failed send only retries its own files
        for i in range(0, len(pending), ALBUM_MAX_FILES):
            album_names = pending[i:i + ALBUM_MAX_FILES]
            uploaded_files = []
            for name in album_names:
                file_path = os.path.join(folder, name)
                part_label = f"file {file_names.index(name) + 1}/{len(file_names)}"
                uploaded_files.append(await self._retry(item, lambda: self._upload_part(client, file_path, part_label)))
                total_size += os.path.getsize(file_path)
            await self._retry(item, lambda: self._send_album(client, supergroup, topic_id, album_names, uploaded_files))
        elapsed_time = max(time.time() - start_time, 0.001)
        self.log(f"{label} uploaded in {format_duration(elapsed_time)} ({format_size(total_size)}, {format_size(total_size / elapsed_time)}/s)")

    async def _upload_items(self):
        client = TelegramClient(SESSION_PATH, int(os.getenv("API_ID")), os.getenv("API_HASH"))
        supergroup = None
        try:
            try:
                await client.start(os.getenv("PHONE_NUMBER"))
                supergroup = await client.get_entity(self.telegram_group)
            except Exception as e:
                # Keep reading the queue so every item that reaches this step is reported
                startup_error = e
                print(f"{LogColor.LIGHT_RED}[{self.log_name}] Error connecting to the supergroup: {e}{LogColor.END}")

            # Wait for the next item in another thread, so the event loop keeps the connection alive
            while (item := await asyncio.to_thread(self.input_queue.get)) is not None:
                if supergroup is None:
                    self.fail(item, f"Could not connect to the Telegram group: {startup_error}")
                    continue
                try:
                    await self._upload_item(client, supergroup, item)
                except Exception as e:
                    self.fail(item, e)
        finally:
            await client.disconnect()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._upload_items())
        finally:
            loop.close()
        self.log("Closing thread")
