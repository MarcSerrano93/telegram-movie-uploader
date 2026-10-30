"""
Movie upload logic (and the shared Telegram code under it) with the fake Telegram client of conftest.py:
no network and no account needed.
"""
import asyncio
import os
from queue import Queue
from types import SimpleNamespace

import pytest
from telethon.errors import ForbiddenError

from conftest import FakeGroup, warning_reasons
from core import shared_state
from core.constants import FileStatus
from core.telegram_api_client import TOPIC_TITLE_MAX_LENGTH
from core.utils import PermanentError
from movies import telegram_api_client as movies_telegram_api_client
from movies.telegram_api_client import MovieTelegramApiClient

GROUP = FakeGroup("group")

@pytest.fixture
def split_movie(make_movie, tmp_path):
    """
    Returns a function that creates a movie already split into the given number of parts in the destination.
    """
    def make(parts=3, **kwargs):
        movie = make_movie(**kwargs)
        movie.destination_path = str(tmp_path / "destination" / os.path.splitext(movie.file_name)[0])
        movie.zip_parts_path = os.path.join(movie.destination_path, "zip_files")
        os.makedirs(movie.zip_parts_path)
        for part in range(1, parts + 1):
            with open(os.path.join(movie.zip_parts_path, f"Película (2024).zip.{part:03d}"), "wb") as f:
                f.write(b"part")
        return movie
    return make

def part_names(count, start=1):
    return [f"Película (2024).zip.{part:03d}" for part in range(start, count + 1)]

def upload(telegram, movie):
    uploader = MovieTelegramApiClient(Queue(), "group")
    asyncio.run(uploader._upload_item(telegram, GROUP, movie))

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

@pytest.fixture
def small_movie(make_movie, tmp_path):
    """
    A movie as FileSplitter leaves the small ones: still in the source, and its destination folder not created yet.
    """
    movie = make_movie()
    movie.destination_path = str(tmp_path / "destination" / "Movie (2024) {tmdb-1}")
    return movie

def test_small_movie_is_sent_as_a_single_document(telegram, small_movie):
    upload(telegram, small_movie)

    assert telegram.sent_albums == [[small_movie.file_name]]
    assert small_movie.status == FileStatus.UPLOADED

def test_small_movie_is_moved_after_the_upload(telegram, small_movie):
    upload(telegram, small_movie)

    assert not os.path.exists(small_movie.file_full_path)
    assert os.path.isfile(os.path.join(small_movie.destination_path, small_movie.file_name))

def test_small_movie_can_be_uploaded_again_after_a_failure(telegram, small_movie):
    telegram.request_errors = [ConnectionError("Connection reset")] * 3
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        upload(telegram, small_movie)
    assert os.path.isfile(small_movie.file_full_path)

    upload(telegram, small_movie)

    assert telegram.sent_albums == [[small_movie.file_name]]
    assert small_movie.status == FileStatus.UPLOADED

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

def upload_to_both_groups(telegram, movie):
    uploader = MovieTelegramApiClient(Queue(), "group", "mkv group")
    asyncio.run(uploader._upload_item(telegram, GROUP, movie))

def topic_of(telegram, group):
    [topic] = [topic for topic in telegram.topics.values() if topic.group == group]
    return topic

def file_names_of(topic):
    return [message.file.name for message in topic.messages if message.file]

def add_mkv_parts(movie, count=2):
    movie.mkv_parts_path = os.path.join(movie.destination_path, "mkv_parts")
    os.makedirs(movie.mkv_parts_path)
    names = [f"Película (2024) {{tmdb-1}} pt{part}.mkv" for part in range(1, count + 1)]
    for name in names:
        with open(os.path.join(movie.mkv_parts_path, name), "wb") as f:
            f.write(b"part")
    return names

def test_big_movie_sends_zip_parts_and_mkv_parts_to_their_groups(telegram, split_movie):
    movie = split_movie(parts=2)
    mkv_names = add_mkv_parts(movie)

    upload_to_both_groups(telegram, movie)

    zip_topic, mkv_topic = topic_of(telegram, "group"), topic_of(telegram, "mkv group")
    assert file_names_of(zip_topic) == part_names(2)
    assert file_names_of(mkv_topic) == mkv_names
    assert zip_topic.messages[0].photo and mkv_topic.messages[0].photo
    assert zip_topic.title == mkv_topic.title
    assert movie.status == FileStatus.UPLOADED
    assert os.path.isfile(os.path.join(movie.destination_path, movie.file_name))

def test_after_a_full_upload_only_the_original_is_left(telegram, split_movie):
    movie = split_movie(parts=2)
    add_mkv_parts(movie)

    upload_to_both_groups(telegram, movie)

    assert os.listdir(movie.destination_path) == [movie.file_name]

def test_parts_are_kept_if_the_mkv_group_upload_fails(telegram, split_movie, monkeypatch):
    movie = split_movie(parts=2)
    add_mkv_parts(movie)
    uploader = MovieTelegramApiClient(Queue(), "group", "mkv group")
    real_upload_to_group = uploader._upload_to_group
    async def upload_to_group(client, supergroup, *args):
        if supergroup == "mkv group":
            telegram.request_errors = [ConnectionError("Connection reset")] * 3
        await real_upload_to_group(client, supergroup, *args)
    monkeypatch.setattr(uploader, "_upload_to_group", upload_to_group)

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        asyncio.run(uploader._upload_item(telegram, GROUP, movie))

    assert sorted(os.listdir(movie.destination_path)) == ["mkv_parts", "zip_files"]
    assert len(os.listdir(movie.zip_parts_path)) == 2
    assert os.path.isfile(movie.file_full_path)

def test_parts_that_cannot_be_deleted_only_give_a_warning(telegram, split_movie, monkeypatch):
    movie = split_movie(parts=1)
    def failing_rmtree(path):
        raise PermissionError("File in use")
    monkeypatch.setattr(movies_telegram_api_client.shutil, "rmtree", failing_rmtree)

    upload(telegram, movie)

    assert movie.status == FileStatus.UPLOADED
    assert "could not delete" in warning_reasons()[0][2]

def test_mkv_parts_are_uploaded_in_order_by_number(telegram, split_movie):
    movie = split_movie(parts=1)
    mkv_names = add_mkv_parts(movie, count=11)

    upload_to_both_groups(telegram, movie)

    assert file_names_of(topic_of(telegram, "mkv group")) == mkv_names

def test_small_movie_goes_whole_to_both_groups(telegram, small_movie):
    upload_to_both_groups(telegram, small_movie)

    assert file_names_of(topic_of(telegram, "group")) == [small_movie.file_name]
    assert file_names_of(topic_of(telegram, "mkv group")) == [small_movie.file_name]
    assert small_movie.status == FileStatus.UPLOADED
    assert not os.path.exists(small_movie.file_full_path)

def test_failed_mkv_group_upload_keeps_a_small_movie_in_the_source(telegram, small_movie, monkeypatch):
    uploader = MovieTelegramApiClient(Queue(), "group", "mkv group")
    real_upload_to_group = uploader._upload_to_group
    async def upload_to_group(client, supergroup, *args):
        if supergroup == "mkv group":
            telegram.request_errors = [ConnectionError("Connection reset")] * 3
        await real_upload_to_group(client, supergroup, *args)
    monkeypatch.setattr(uploader, "_upload_to_group", upload_to_group)

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        asyncio.run(uploader._upload_item(telegram, GROUP, small_movie))

    assert small_movie.status != FileStatus.UPLOADED
    assert os.path.isfile(small_movie.file_full_path)

def test_resume_only_uploads_what_the_mkv_group_is_missing(telegram, split_movie):
    movie = split_movie(parts=1)
    mkv_names = add_mkv_parts(movie)
    zip_topic = telegram.add_topic("Película (2024) {tmdb-1}", "group")
    zip_topic.messages.append(SimpleNamespace(photo=True, message="🎬| ...", file=None))
    zip_topic.messages.append(telegram.file_message(part_names(1)[0]))
    mkv_topic = telegram.add_topic("Película (2024) {tmdb-1}", "mkv group")
    mkv_topic.messages.append(SimpleNamespace(photo=True, message="🎬| ...", file=None))
    mkv_topic.messages.append(telegram.file_message(mkv_names[0]))

    upload_to_both_groups(telegram, movie)

    assert telegram.uploaded_files == [mkv_names[1]]

def test_failed_mkv_group_upload_keeps_the_original_in_the_source(telegram, split_movie):
    movie = split_movie(parts=1)
    movie.mkv_parts_path = os.path.join(movie.destination_path, "missing")

    with pytest.raises(FileNotFoundError):
        upload_to_both_groups(telegram, movie)

    assert movie.status != FileStatus.UPLOADED
    assert os.path.isfile(movie.file_full_path)

def test_wrong_mkv_group_fails_before_uploading_anything(telegram, split_movie):
    movie = split_movie(parts=1)
    telegram.unknown_groups.add("mkv group")

    with pytest.raises(RuntimeError, match="Cannot find mkv group"):
        upload_to_both_groups(telegram, movie)

    assert telegram.uploaded_files == []

def test_mkv_group_is_not_used_when_disabled(telegram, split_movie):
    upload(telegram, split_movie(parts=1))

    assert [topic.group for topic in telegram.topics.values()] == ["group"]

def test_missing_part_files_fail(telegram, split_movie):
    movie = split_movie(parts=1)
    for name in os.listdir(movie.zip_parts_path):
        os.remove(os.path.join(movie.zip_parts_path, name))

    with pytest.raises(PermanentError, match="No zip parts found"):
        upload(telegram, movie)

def test_missing_small_movie_fails(telegram, small_movie):
    os.remove(small_movie.file_full_path)

    with pytest.raises(PermanentError, match="File not found"):
        upload(telegram, small_movie)

def test_new_movie_posts_its_poster_in_general_with_a_link(telegram, split_movie):
    upload(telegram, split_movie(parts=1))

    [topic] = telegram.topics.values()
    [entry] = telegram.general
    assert entry.silent
    assert entry.image == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert entry.caption.startswith("🎬| **Película**")
    assert entry.caption.endswith(f"👉 | [¡Ir a la película!](https://t.me/c/555/{topic.id})**")

def test_new_movie_posts_in_general_of_both_groups(telegram, split_movie):
    movie = split_movie(parts=1)
    add_mkv_parts(movie)

    upload_to_both_groups(telegram, movie)

    assert len(telegram.general) == 2

def test_movie_without_poster_posts_its_text_in_general(telegram, split_movie):
    movie = split_movie(parts=1)
    movie.poster_path = ""

    upload(telegram, movie)

    [entry] = telegram.general
    assert entry.silent
    assert entry.photo is None
    assert entry.text.endswith("[¡Ir a la película!](https://t.me/c/555/100)**")

def test_existing_topic_with_poster_posts_nothing_in_general(telegram, split_movie):
    movie = split_movie(parts=1)
    topic = telegram.add_topic("Película (2024) {tmdb-1}")
    topic.messages.append(SimpleNamespace(photo=True, message="🎬| ...", file=None))

    upload(telegram, movie)

    assert telegram.general == []

def test_every_message_of_a_movie_is_silent(telegram, split_movie):
    upload(telegram, split_movie(parts=2))

    [topic] = telegram.topics.values()
    assert len(topic.messages) == 3
    assert all(message.silent for message in topic.messages)

def test_text_poster_is_silent(telegram, split_movie):
    movie = split_movie(parts=1)
    movie.poster_path = ""

    upload(telegram, movie)

    [topic] = telegram.topics.values()
    assert topic.messages[0].silent
