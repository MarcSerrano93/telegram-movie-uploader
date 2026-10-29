"""
The TV pipeline working together, with fake TMDB responses and a fake upload stage.
"""
from queue import Queue
from types import SimpleNamespace

import tv.pipeline
from conftest import fake_response
from core import shared_state, tmdb
from core.constants import FileStatus, Step
from core.pipeline_stage import PipelineStage
from core.utils import print_summary

class FakeUpload(PipelineStage):
    """
    Replaces ShowTelegramApiClient: marks every show as uploaded.
    """
    step = Step.UPLOAD
    log_name = "FakeUpload"

    def __init__(self, input_queue, telegram_group):
        super().__init__(input_queue, Queue())

    def process(self, show):
        show.status = FileStatus.UPLOADED

def fake_tmdb(monkeypatch):
    """
    Show 404 does not exist. The others answer in the requested language.
    """
    def get(url, params, timeout):
        show_id = url.rsplit("/", 1)[1]
        if show_id == "404":
            return fake_response(404)
        if params["language"] == tmdb.LANGUAGE_ES:
            return fake_response(200, {"name": f"Serie {show_id}"})
        return fake_response(200, {
            "name": f"Show {show_id}", "first_air_date": "2008-01-20", "backdrop_path": "/backdrop.jpg", "poster_path": None,
            "seasons": [{"season_number": 1, "episode_count": 7, "poster_path": "/s1.jpg"}],
        })
    monkeypatch.setattr(tmdb.requests, "get", get)

def test_tv_pipeline(tmp_path, monkeypatch, capsys):
    fake_tmdb(monkeypatch)
    monkeypatch.setattr(tv.pipeline, "ShowTelegramApiClient", FakeUpload)
    for folder in ["Good (2008) {tmdb-1}", "Wrong id {tmdb-404}", "No tag"]:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "1x01 - Pilot.mkv").write_bytes(b"episode")
    config = SimpleNamespace(source_files_path=str(tmp_path), telegram_size_limit_mb=4000, telegram_group="group")

    shared_state.items.extend(tv.pipeline.read_items(config))
    input_queue = Queue()
    stages = tv.pipeline.create_stages(config, input_queue)
    for show in shared_state.items:
        input_queue.put(show)
    input_queue.put(None)
    for stage in stages:
        stage.start()
    for stage in stages:
        stage.join(timeout=30)
        assert not stage.is_alive(), f"{stage.log_name} did not finish"

    good = next(show for show in shared_state.items if show.tmdb_id == "1")
    assert good.status == FileStatus.UPLOADED
    assert (good.name, good.name_es, good.year) == ("Show 1", "Serie 1", "2008")
    assert (good.backdrop_path, good.poster_path) == ("https://image.tmdb.org/t/p/w1280/backdrop.jpg", "")
    season = good.get_season(1)
    assert (season.episode_count, season.poster_path) == (7, "https://image.tmdb.org/t/p/w500/s1.jpg")

    capsys.readouterr()
    print_summary(tv.pipeline.ITEM_LABEL)
    output = capsys.readouterr().out
    assert "Uploaded: 1 of 3 TV shows" in output
    assert "Show not found in TMDB, check the id in the folder name" in output
    assert "No {tmdb-<id>} tag in the folder name" in output
