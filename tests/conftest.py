"""
Shared fixtures. pytest.ini adds src/ to the import path.
"""
import json
import os
from types import SimpleNamespace

import pytest
import requests
from telethon.errors import WebpageMediaEmptyError
from telethon.extensions import markdown
from telethon.tl.functions.messages import CreateForumTopicRequest, GetForumTopicsRequest

from core import shared_state, telegram_api_client, utils
from movies.movie import Movie

@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch):
    # Retries still happen, without waiting 10s/30s
    monkeypatch.setattr(utils, "RETRY_DELAYS", [0, 0])

@pytest.fixture(autouse=True)
def clean_shared_state():
    yield
    for values in (shared_state.items, shared_state.errors, shared_state.warnings):
        values.clear()

@pytest.fixture
def make_movie(tmp_path):
    """
    Creates a movie file of the given size in tmp_path/source and returns its Movie, with TMDB info filled in.
    """
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    def make(file_name="Movie (2024) {tmdb-1}.mkv", size=100, title="Película", year="2024"):
        path = source / file_name
        path.write_bytes(os.urandom(size))
        movie = Movie(str(path))
        movie.set_movie_metadata(title, "Movie", year, [], 100, "https://image.tmdb.org/t/p/w500/poster.jpg")
        return movie
    return make

def error_reasons():
    """
    Returns the (step value, file name, reason) of every reported error, as strings.
    """
    return [(step.value, file_name, str(reason)) for step, file_name, reason in shared_state.errors]

class FakePhoto(str):
    """
    A photo already in Telegram, named after its image.
    """

class FakeGroup(str):
    """
    A Telegram group: compares as its name, and has an id for the topic links.
    """
    id = 555

class FakeTopic:
    def __init__(self, topic_id, title, group=None):
        self.id = topic_id
        self.title = title
        self.group = group      # None: visible from any group
        self.top_message = topic_id
        self.messages = []

class FakeUpdate:
    def __init__(self, message_id):
        self.message = SimpleNamespace(id=message_id)

class FakeTelegram:
    """
    Keeps the topics and messages of one group in memory, with the client methods the uploaders use.
    """
    def __init__(self):
        self.topics = {}
        self.general = []           # Messages of the General topic
        self.uploaded_files = []    # Names, in upload order
        self.sent_albums = []       # Names of the files of each send_file call with files
        self.lost_album_responses = 0   # Next albums that are sent, but whose response is lost
        self.request_errors = []        # Raised by the next topic requests
        self.request_count = 0
        self.broken_image_urls = set()  # Image URLs that Telegram cannot download
        self.unknown_groups = set()     # Groups that get_entity cannot find

    def add_topic(self, title, group=None):
        topic = FakeTopic(len(self.topics) + 100, title, group)
        self.topics[topic.id] = topic
        return topic

    async def get_entity(self, group):
        if group in self.unknown_groups:
            raise ValueError(f"Cannot find {group}")
        return FakeGroup(group)

    async def __call__(self, request):
        self.request_count += 1
        if self.request_errors:
            raise self.request_errors.pop(0)
        if isinstance(request, GetForumTopicsRequest):
            # Like Telegram's search, it may also return topics that only look similar
            topics = [topic for topic in self.topics.values() if topic.group in (None, request.peer)]
            # Like Telegram, a page starts after offset_topic, and the most recent topics come first
            topics.sort(key=lambda topic: topic.id, reverse=True)
            if request.offset_topic:
                topics = [topic for topic in topics if topic.id < request.offset_topic]
            topics = topics[:request.limit]
            messages = [SimpleNamespace(id=topic.top_message, date=None) for topic in topics]
            return SimpleNamespace(topics=topics, messages=messages)
        if isinstance(request, CreateForumTopicRequest):
            topic = self.add_topic(request.title, request.peer)
            return SimpleNamespace(updates=[FakeUpdate(topic.id)])
        raise NotImplementedError(request)

    async def iter_messages(self, entity, reply_to, reverse=False, limit=None):
        messages = self.general if reply_to == 1 else self.topics[reply_to].messages
        for message in list(messages)[:limit]:
            yield message

    async def send_message(self, entity, message, reply_to=None, silent=False, link_preview=True):
        messages = self.topics[reply_to].messages if reply_to else self.general
        messages.append(self.text_message(message))
        messages[-1].silent = silent

    async def send_file(self, entity, file, reply_to=None, caption=None, force_document=False, silent=False):
        messages = self.topics[reply_to].messages if reply_to else self.general
        if isinstance(file, (str, FakePhoto)):   # Image: TMDB URL, local file or a photo already in Telegram
            if file in self.broken_image_urls:
                raise WebpageMediaEmptyError(request=None)
            messages.append(self.photo_message(caption, file))
            messages[-1].silent = silent
        else:
            files = file if isinstance(file, list) else [file]
            self.sent_albums.append([uploaded.name for uploaded in files])
            for uploaded in files:
                messages.append(self.file_message(uploaded.name))
                messages[-1].silent = silent
            if self.lost_album_responses:
                self.lost_album_responses -= 1
                raise ConnectionError("Response lost")

    def text_message(self, text):
        plain_text, entities = markdown.parse(text)
        return SimpleNamespace(photo=None, message=plain_text, text=text, entities=entities, file=None)

    def photo_message(self, caption, image="image.jpg"):
        # Like Telegram, .message keeps no markdown: "**Bold**" arrives as "Bold". .text is the markdown version
        plain_text, entities = markdown.parse(caption or "")
        return SimpleNamespace(photo=FakePhoto(image), message=plain_text, text=caption or "", entities=entities, file=None, image=image, caption=caption)

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

def warning_reasons():
    return [(step.value, file_name, str(reason)) for step, file_name, reason in shared_state.warnings]

def fake_response(status_code, content=None):
    """
    Returns a requests.Response with the given status code and JSON content, like the ones TMDB returns.
    """
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(content or {}).encode()
    return response
