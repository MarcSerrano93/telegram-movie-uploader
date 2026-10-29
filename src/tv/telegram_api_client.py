"""
Stage 2 of the TV pipeline: uploads each show to its own topic: the backdrop with the show info, then each season
(its poster and its episodes). The first time, it also posts the show poster in the General topic, with a link
to the show's topic. The episode files stay in the source folder.
"""
import os

from telethon.errors import WebpageCurlFailedError, WebpageMediaEmptyError

from core.constants import FileStatus, PROJECT_ROOT
from core.telegram_api_client import TelegramApiClient
from core.utils import report_warning
from tv.show import BACKDROP_CAPTION_START, Show

MEDIA_PATH = os.path.join(PROJECT_ROOT, "media")
DEFAULT_BACKDROP = os.path.join(MEDIA_PATH, "no-media-banner.png")
DEFAULT_POSTER = os.path.join(MEDIA_PATH, "no-media-poster.png")
TOPIC_LINK_URL = "https://t.me/c/{group_id}/{topic_id}"
IMAGE_URL_ERRORS = (WebpageMediaEmptyError, WebpageCurlFailedError)   # Telegram could not download the image from TMDB

class ShowTelegramApiClient(TelegramApiClient):
    log_name = "ShowTelegramApiClient"

    def _has_backdrop(self, messages):
        return any(message.photo and (message.message or "").startswith(BACKDROP_CAPTION_START) for message in messages)

    def _has_season_poster(self, messages, number):
        # " ==" so that "Temporada 1" does not match "Temporada 10"
        return any(message.photo and f"Temporada {number} ==" in (message.message or "") for message in messages)

    async def _send_image(self, client, supergroup, show: Show, image_url, default_image, caption, description, topic_id=None):
        """
        Sends the TMDB image with its caption or, if TMDB has none or Telegram cannot download it, the default image.
        Without topic_id it goes to the General topic.
        """
        if image_url:
            try:
                await client.send_file(entity=supergroup, file=image_url, caption=caption, reply_to=topic_id)
                return
            except IMAGE_URL_ERRORS:
                report_warning(self.step, show.file_name, f"Telegram could not download the {description} from TMDB, default image sent")
        else:
            report_warning(self.step, show.file_name, f"No {description} in TMDB, default image sent")
        await client.send_file(entity=supergroup, file=default_image, caption=caption, reply_to=topic_id)

    async def _send_backdrop(self, client, supergroup, topic_id, show: Show):
        # Checked on every attempt, in case a previous one was sent but its response was lost
        if self._has_backdrop(await self._get_topic_messages(client, supergroup, topic_id)):
            return
        await self._send_image(client, supergroup, show, show.backdrop_path, DEFAULT_BACKDROP, show.generate_telegram_caption(), "backdrop", topic_id)

    async def _send_season_poster(self, client, supergroup, topic_id, show: Show, number):
        if self._has_season_poster(await self._get_topic_messages(client, supergroup, topic_id), number):
            return
        season = show.get_season(number)
        await self._send_image(client, supergroup, show, season.poster_path, DEFAULT_POSTER, season.generate_telegram_caption(),
                               f"season {number} poster", topic_id)

    async def _upload_item(self, client, supergroup, show: Show):
        """
        Full upload of one show: find or create its topic, send the backdrop (and the poster to General) if the topic
        does not have it yet, then for each season with missing episodes its poster and the episodes in albums of up to 10.
        Whatever is already in the topic is skipped.
        """
        topic_id, created = await self._retry(show, lambda: self._find_or_create_topic(client, supergroup, show.name, show.year, show.tmdb_id))
        messages = [] if created else await self._retry(show, lambda: self._get_topic_messages(client, supergroup, topic_id))

        if not self._has_backdrop(messages):
            # The General poster goes first: if the backdrop then fails, the next run sends the poster again,
            # better than never sending it
            topic_link = TOPIC_LINK_URL.format(group_id=supergroup.id, topic_id=topic_id)
            await self._retry(show, lambda: self._send_image(client, supergroup, show, show.poster_path, DEFAULT_POSTER,
                                                             show.generate_telegram_caption(topic_link), "poster"))
            await self._retry(show, lambda: self._send_backdrop(client, supergroup, topic_id, show))

        sent_files = self._get_file_names(messages)
        for number, file_names in show.episodes.items():
            if any(name not in sent_files for name in file_names) and not self._has_season_poster(messages, number):
                await self._retry(show, lambda: self._send_season_poster(client, supergroup, topic_id, show, number))
            await self._upload_files(client, supergroup, topic_id, show, f"{show.name} season {number}", show.folder_path, file_names, sent_files)

        show.status = FileStatus.UPLOADED
