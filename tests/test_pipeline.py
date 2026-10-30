"""
The movies pipeline working together, with fake TMDB responses and a fake upload stage.
"""
from queue import Queue
from types import SimpleNamespace

import requests

import movies.pipeline
from core import shared_state, tmdb
from core.constants import FileStatus, Step
from core.pipeline_stage import PipelineStage
from conftest import fake_response
from core.utils import print_summary
from movies.mkv_splitter import MkvSplitter

class FakeUpload(PipelineStage):
    """
    Replaces MovieTelegramApiClient: marks every movie as uploaded.
    """
    step = Step.UPLOAD
    log_name = "FakeUpload"

    def __init__(self, input_queue, telegram_group, mkv_parts_telegram_group=None):
        super().__init__(input_queue, Queue())

    def process(self, movie):
        movie.status = FileStatus.UPLOADED

def fake_tmdb(monkeypatch):
    """
    Movie 404 does not exist, 99 never answers and 7 fails twice before answering.
    """
    calls = {}
    def get(url, params, timeout):
        movie_id = url.rsplit("/", 1)[1]
        calls[movie_id] = calls.get(movie_id, 0) + 1
        if movie_id == "99" or (movie_id == "7" and calls[movie_id] <= 2):
            raise requests.ConnectionError("Connection aborted")
        if movie_id == "404":
            return fake_response(404)
        return fake_response(200, {"title": f"Película {movie_id}", "release_date": "2024-01-01", "genres": [{"id": 28}], "runtime": 100})
    monkeypatch.setattr(tmdb.requests, "get", get)

def test_movies_pipeline(tmp_path, monkeypatch, capsys):
    fake_tmdb(monkeypatch)
    monkeypatch.setattr(movies.pipeline, "MovieTelegramApiClient", FakeUpload)
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    for name in ["Good (2024) {tmdb-1}.mkv", "Wrong id (2020) {tmdb-404}.mkv", "Flaky network (2021) {tmdb-7}.mkv",
                 "Network down (2022) {tmdb-99}.mkv", "No tag (2019).mkv"]:
        (source / name).write_bytes(b"movie")
    config = SimpleNamespace(source_files_path=str(source), destination_files_path=str(destination),
                             telegram_size_limit_mb=4000, telegram_group="group",
                             mkv_parts_enabled=False, mkv_parts_telegram_group=None)

    shared_state.items.extend(movies.pipeline.read_items(config))
    input_queue = Queue()
    stages = movies.pipeline.create_stages(config, input_queue)
    for movie in shared_state.items:
        input_queue.put(movie)
    input_queue.put(None)
    for stage in stages:
        stage.start()
    for stage in stages:
        stage.join(timeout=30)
        assert not stage.is_alive(), f"{stage.log_name} did not finish"

    statuses = {movie.tmdb_id: movie.status for movie in shared_state.items}
    assert statuses == {"1": FileStatus.UPLOADED, "7": FileStatus.UPLOADED, "404": FileStatus.ERROR, "99": FileStatus.ERROR}
    good = next(movie for movie in shared_state.items if movie.tmdb_id == "1")
    assert (good.title, good.year, good.genres, good.duration) == ("Película 1", "2024", ["Acción"], 100)
    assert good.destination_path == str(destination / "Good (2024) {tmdb-1}")

    capsys.readouterr()
    print_summary(movies.pipeline.ITEM_LABEL)
    output = capsys.readouterr().out
    assert "Uploaded: 2 of 5 movies" in output
    assert "ERRORS (3)" in output
    assert "No {tmdb-<id>} tag in the file name" in output
    assert "Movie not found in TMDB" in output
    assert "Connection aborted (failed after 3 attempts)" in output

def test_mkv_stage_only_runs_when_enabled():
    config = SimpleNamespace(destination_files_path="", telegram_size_limit_mb=4000, telegram_group="group",
                             mkv_parts_enabled=False, mkv_parts_telegram_group=None)
    assert not any(isinstance(stage, MkvSplitter) for stage in movies.pipeline.create_stages(config, Queue()))

    config.mkv_parts_enabled, config.mkv_parts_telegram_group, config.mkvmerge_path = True, "mkv group", "mkvmerge"
    stages = movies.pipeline.create_stages(config, Queue())
    assert [type(stage).__name__ for stage in stages] == ["MovieTmdbApiClient", "FileSplitter", "MkvSplitter", "MovieTelegramApiClient"]
    assert stages[-1].mkv_parts_telegram_group == "mkv group"
    # Splitting waits for the uploads, so the parts of many movies do not fill the disk
    assert stages[1].output_queue.maxsize == stages[2].output_queue.maxsize == 1
