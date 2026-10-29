"""
Upload logic with a fake Telegram client: no network and no account needed.
"""
import asyncio
import os
from queue import Queue
from types import SimpleNamespace

import pytest
from telethon.errors import ForbiddenError
from telethon.tl.functions.messages import CreateForumTopicRequest, GetForumTopicsRequest

import shared_state
import telegram_api_client
from constants import FileStatus
from telegram_api_client import TelegramApiClient, TOPIC_TITLE_MAX_LENGTH

class FakeTopic:
    def __init__(self, topic_id, title):
        self.id = topic_id
        self.title = title
        self.messages = []

class FakeUpdate:
    def __init__(self, message_id):
        self.message = SimpleNamespace(id=message_id)

class FakeTelegram:
    """
    Keeps the topics and messages of one group in memory, with the client methods the uploader uses.
    """
    def __init__(self):
        self.topics = {}
        self.uploaded_files = []    # Names, in upload order
        self.sent_albums = []       # Names of the files of each send_file call with files
        self.lost_album_responses = 0   # Next albums that are sent, but whose response is lost
        self.request_errors = []        # Raised by the next topic requests
        self.request_count = 0

    def add_topic(self, title):
        topic = FakeTopic(len(self.topics) + 100, title)
        self.topics[topic.id] = topic
        return topic

    async def __call__(self, request):
        self.request_count += 1
        if self.request_errors:
            raise self.request_errors.pop(0)
        if isinstance(request, GetForumTopicsRequest):
            # Like Telegram's search, it may also return topics that only look similar
            return SimpleNamespace(topics=list(self.topics.values()))
        if isinstance(request, CreateForumTopicRequest):
            topic = self.add_topic(request.title)
            return SimpleNamespace(updates=[FakeUpdate(topic.id)])
        raise NotImplementedError(request)

    async def iter_messages(self, entity, reply_to):
        for message in list(self.topics[reply_to].messages):
            yield message

    async def send_message(self, entity, message, reply_to):
        self.topics[reply_to].messages.append(SimpleNamespace(photo=None, message=message, file=None))

    async def send_file(self, entity, file, reply_to, caption=None, force_document=False):
        messages = self.topics[reply_to].messages
        if isinstance(file, str):   # Poster URL
            messages.append(SimpleNamespace(photo=True, message=caption, file=None))
        else:
            files = file if isinstance(file, list) else [file]
            self.sent_albums.append([uploaded.name for uploaded in files])
            for uploaded in files:
                messages.append(self.file_message(uploaded.name))
            if self.lost_album_responses:
                self.lost_album_responses -= 1
                raise ConnectionError("Response lost")

    def file_message(self, name):
        return SimpleNamespace(photo=None, message="", file=SimpleNamespace(name=name))

@pytest.fixture
def telegram(monkeypatch):
    fake = FakeTelegram()
    async def fake_upload_file(client, file, file_name, progress_callback):
        size = os.fstat(file.fileno()).st_size
        progress_callback(size, size)
        fake.uploaded_files.append(file_name)
        return SimpleNamespace(name=file_name)
    monkeypatch.setattr(telegram_api_client, "upload_file", fake_upload_file)
    monkeypatch.setattr(telegram_api_client, "ForumTopic", FakeTopic)
    monkeypatch.setattr(telegram_api_client, "UpdateNewChannelMessage", FakeUpdate)
    return fake

@pytest.fixture
def split_movie(make_movie, tmp_path):
    """
    Returns a function that creates a movie already split into the given number of parts in the destination.
    """
    def make(parts=3, **kwargs):
        movie = make_movie(**kwargs)
        movie.destination_path = str(tmp_path / "destination" / os.path.splitext(movie.file_name)[0])
        os.makedirs(movie.destination_path)
        for part in range(1, parts + 1):
            with open(os.path.join(movie.destination_path, f"Película (2024).zip.{part:03d}"), "wb") as f:
                f.write(b"part")
        return movie
    return make

def part_names(count, start=1):
    return [f"Película (2024).zip.{part:03d}" for part in range(start, count + 1)]

def upload(telegram, movie):
    uploader = TelegramApiClient(Queue(), "group")
    asyncio.run(uploader._upload_movie(telegram, "group", movie))

def test_new_movie_creates_topic_poster_and_one_album(telegram, split_movie):
    movie = split_movie(parts=3)

    upload(telegram, movie)

    [topic] = telegram.topics.values()
    assert topic.title == "Película (2024) {tmdb-1}"
    assert topic.messages[0].photo
    assert telegram.sent_albums == [part_names(3)]
    assert movie.status == FileStatus.UPLOADED

def test_original_is_moved_next_to_its_parts(telegram, split_movie):
    movie = split_movie(parts=2)

    upload(telegram, movie)

    assert not os.path.exists(movie.file_full_path)
    assert os.path.isfile(os.path.join(movie.destination_path, movie.file_name))

def test_small_movie_is_sent_as_a_single_document(telegram, make_movie, tmp_path):
    movie = make_movie()
    movie.destination_path = str(tmp_path / "destination")
    os.makedirs(movie.destination_path)
    os.rename(movie.file_full_path, os.path.join(movie.destination_path, movie.file_name))

    upload(telegram, movie)

    assert telegram.sent_albums == [[movie.file_name]]
    assert movie.status == FileStatus.UPLOADED

def test_more_than_10_files_are_sent_in_several_albums(telegram, split_movie):
    upload(telegram, split_movie(parts=12))

    assert telegram.sent_albums == [part_names(10), part_names(12, start=11)]

def test_resume_uploads_only_missing_files(telegram, split_movie):
    movie = split_movie(parts=3)
    topic = telegram.add_topic("Película (2024) {tmdb-1}")
    topic.messages.append(SimpleNamespace(photo=True, message="🎬| ...", file=None))
    topic.messages.append(telegram.file_message("Película (2024).zip.001"))

    upload(telegram, movie)

    assert len(telegram.topics) == 1
    assert telegram.uploaded_files == part_names(3, start=2)
    assert sum(1 for message in topic.messages if message.photo) == 1

def test_everything_already_uploaded(telegram, split_movie):
    movie = split_movie(parts=2)
    topic = telegram.add_topic("Película (2024) {tmdb-1}")
    topic.messages.append(SimpleNamespace(photo=True, message="🎬| ...", file=None))
    topic.messages.extend(telegram.file_message(name) for name in part_names(2))

    upload(telegram, movie)

    assert telegram.uploaded_files == []
    assert movie.status == FileStatus.UPLOADED

def test_topic_is_found_by_exact_tag(telegram, split_movie):
    telegram.add_topic("Other (2024) {tmdb-12}")
    existing = telegram.add_topic("Película (2024) {tmdb-1}")

    upload(telegram, split_movie(parts=1))

    assert len(telegram.topics) == 2
    assert existing.messages

def test_long_title_is_cut_but_keeps_the_tag(telegram, split_movie):
    upload(telegram, split_movie(parts=1, title="A" * 300))

    [topic] = telegram.topics.values()
    assert len(topic.title) == TOPIC_TITLE_MAX_LENGTH
    assert topic.title.endswith(" (2024) {tmdb-1}")

def test_movie_without_poster_sends_text_and_warns(telegram, split_movie):
    movie = split_movie(parts=1)
    movie.poster_path = ""

    upload(telegram, movie)

    [topic] = telegram.topics.values()
    assert topic.messages[0].photo is None
    assert topic.messages[0].message.startswith("🎬|")
    assert [reason for _, _, reason in shared_state.warnings] == ["No poster in TMDB, info sent as text"]

def test_lost_response_does_not_send_the_album_twice(telegram, split_movie):
    movie = split_movie(parts=2)
    telegram.lost_album_responses = 1

    upload(telegram, movie)

    assert telegram.sent_albums == [part_names(2)]
    assert movie.status == FileStatus.UPLOADED

def test_forbidden_error_is_not_retried(telegram, split_movie):
    telegram.request_errors = [ForbiddenError(None, "CHAT_ADMIN_REQUIRED")] * 3

    with pytest.raises(ForbiddenError):
        upload(telegram, split_movie(parts=1))
    assert telegram.request_count == 1

def test_temporary_error_is_retried(telegram, split_movie):
    movie = split_movie(parts=1)
    telegram.request_errors = [ConnectionError("Connection reset")]

    upload(telegram, movie)

    assert movie.status == FileStatus.UPLOADED
    assert len(telegram.topics) == 1

def test_missing_part_files_fail(telegram, split_movie):
    movie = split_movie(parts=1)
    for name in os.listdir(movie.destination_path):
        os.remove(os.path.join(movie.destination_path, name))

    with pytest.raises(Exception, match="File not found"):
        upload(telegram, movie)
