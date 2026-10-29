"""
TV upload logic with the fake Telegram client of conftest.py: no network and no account needed.
"""
import asyncio
from queue import Queue
from types import SimpleNamespace

import pytest

from conftest import warning_reasons
from core.constants import FileStatus
from tv.show import Season, Show
from tv.telegram_api_client import DEFAULT_BACKDROP, DEFAULT_POSTER, ShowTelegramApiClient

BACKDROP_URL = "https://image.tmdb.org/t/p/w1280/backdrop.jpg"
POSTER_URL = "https://image.tmdb.org/t/p/w500/poster.jpg"
SUPERGROUP = SimpleNamespace(id=555)

@pytest.fixture
def make_show(tmp_path):
    """
    Returns a function that creates a show folder with the given episodes per season, with its TMDB info filled in.
    """
    def make(episodes=None):
        episodes = episodes or {1: 2}
        folder = tmp_path / "Show (2020) {tmdb-7}"
        folder.mkdir()
        names = {}
        for season, count in episodes.items():
            names[season] = [f"{season}x{episode:02d} - Episode.mkv" for episode in range(1, count + 1)]
            for name in names[season]:
                (folder / name).write_bytes(b"episode")
        show = Show(str(folder), names)
        seasons = {number: Season(number, count, f"https://image.tmdb.org/t/p/w500/season{number}.jpg") for number, count in episodes.items()}
        show.set_show_metadata("Show", "Serie", "2020", BACKDROP_URL, POSTER_URL, seasons)
        return show
    return make

def upload(telegram, show):
    asyncio.run(ShowTelegramApiClient(Queue(), "group")._upload_item(telegram, SUPERGROUP, show))

def captions(messages):
    return [message.message for message in messages]

def test_new_show(telegram, make_show):
    show = make_show({1: 2, 2: 1})

    upload(telegram, show)

    [topic] = telegram.topics.values()
    assert topic.title == "Show (2020) {tmdb-7}"
    assert captions(topic.messages) == [
        "🇪🇸 | Serie\n🇬🇧 | Show\n📅 | 2020\n🌐 | TMDB",
        "..--== Temporada 1 ==--..\n..--== (2 episodios) ==--..", "", "",
        "..--== Temporada 2 ==--..\n..--== (1 episodios) ==--..", "",
    ]
    assert telegram.sent_albums == [["1x01 - Episode.mkv", "1x02 - Episode.mkv"], ["2x01 - Episode.mkv"]]
    [general_poster] = telegram.general
    assert general_poster.image == POSTER_URL
    assert general_poster.caption.endswith(f"👉 | [¡Ir a la serie!](https://t.me/c/555/{topic.id})**")
    assert show.status == FileStatus.UPLOADED

def test_new_season_of_an_existing_show(telegram, make_show):
    show = make_show({1: 1, 2: 1})
    topic = telegram.add_topic("Show (2020) {tmdb-7}")
    topic.messages.append(telegram.photo_message("**🇪🇸 | Serie\n🇬🇧 | Show**"))
    topic.messages.append(telegram.photo_message("**..--== Temporada 1 ==--..\n..--== (1 episodios) ==--..**"))
    topic.messages.append(telegram.file_message("1x01 - Episode.mkv"))

    upload(telegram, show)

    assert telegram.general == []
    assert captions(topic.messages[3:]) == ["..--== Temporada 2 ==--..\n..--== (1 episodios) ==--..", ""]
    assert telegram.uploaded_files == ["2x01 - Episode.mkv"]

def test_resumed_season_does_not_repeat_its_poster(telegram, make_show):
    show = make_show({1: 3})
    topic = telegram.add_topic("Show (2020) {tmdb-7}")
    topic.messages.append(telegram.photo_message("**🇪🇸 | Serie**"))
    topic.messages.append(telegram.photo_message("**..--== Temporada 1 ==--..**"))
    topic.messages.append(telegram.file_message("1x01 - Episode.mkv"))

    upload(telegram, show)

    assert sum(1 for message in topic.messages if message.photo) == 2
    assert telegram.uploaded_files == ["1x02 - Episode.mkv", "1x03 - Episode.mkv"]

def test_season_10_poster_is_not_taken_for_season_1(telegram, make_show):
    show = make_show({1: 1})
    topic = telegram.add_topic("Show (2020) {tmdb-7}")
    topic.messages.append(telegram.photo_message("**🇪🇸 | Serie**"))
    topic.messages.append(telegram.photo_message("**..--== Temporada 10 ==--..**"))

    upload(telegram, show)

    assert "..--== Temporada 1 ==--.." in captions(topic.messages)[2]

def test_topic_without_backdrop_gets_it_and_the_general_poster(telegram, make_show):
    show = make_show()
    topic = telegram.add_topic("Show (2020) {tmdb-7}")

    upload(telegram, show)

    assert topic.messages[0].image == BACKDROP_URL
    assert len(telegram.general) == 1

def test_missing_images_use_the_default_ones(telegram, make_show):
    show = make_show()
    show.backdrop_path = show.poster_path = show.seasons[1].poster_path = ""

    upload(telegram, show)

    [topic] = telegram.topics.values()
    assert [topic.messages[0].image, topic.messages[1].image, telegram.general[0].image] == [DEFAULT_BACKDROP, DEFAULT_POSTER, DEFAULT_POSTER]
    assert [reason for _, _, reason in warning_reasons()] == [
        "No poster in TMDB, default image sent",
        "No backdrop in TMDB, default image sent",
        "No season 1 poster in TMDB, default image sent",
    ]

def test_image_telegram_cannot_download_uses_the_default_one(telegram, make_show):
    telegram.broken_image_urls.add(BACKDROP_URL)

    upload(telegram, make_show())

    [topic] = telegram.topics.values()
    assert topic.messages[0].image == DEFAULT_BACKDROP
    assert [reason for _, _, reason in warning_reasons()] == ["Telegram could not download the backdrop from TMDB, default image sent"]

def test_season_missing_in_tmdb_counts_local_episodes(telegram, make_show):
    show = make_show({1: 2})
    show.seasons = {}

    upload(telegram, show)

    [topic] = telegram.topics.values()
    assert captions(topic.messages)[1] == "..--== Temporada 1 ==--..\n..--== (2 episodios) ==--.."
    assert topic.messages[1].image == DEFAULT_POSTER

def test_more_than_10_episodes_are_sent_in_several_albums(telegram, make_show):
    upload(telegram, make_show({1: 12}))

    assert [len(album) for album in telegram.sent_albums] == [10, 2]

def test_everything_already_uploaded(telegram, make_show):
    show = make_show({1: 1})
    topic = telegram.add_topic("Show (2020) {tmdb-7}")
    topic.messages.append(telegram.photo_message("**🇪🇸 | Serie**"))
    topic.messages.append(telegram.file_message("1x01 - Episode.mkv"))

    upload(telegram, show)

    assert len(topic.messages) == 2
    assert telegram.general == []
    assert show.status == FileStatus.UPLOADED
