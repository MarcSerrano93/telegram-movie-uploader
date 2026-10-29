"""
The three stages working together, with fake TMDB responses and a fake upload stage.
"""
from queue import Queue

import requests
import tmdbsimple

import shared_state
from constants import FileStatus, Step
from file_splitter import FileSplitter
from folder_reader import FolderReader
from pipeline_stage import PipelineStage
from tmdb_api_client import TmdbApiClient
from utils import print_summary

class FakeUpload(PipelineStage):
    step = Step.UPLOAD
    log_name = "FakeUpload"

    def process(self, movie):
        movie.status = FileStatus.UPLOADED

def fake_tmdb(monkeypatch):
    """
    Movie 404 does not exist, 99 never answers and 7 fails twice before answering.
    """
    calls = {}
    def info(tmdb_movie, language=None):
        calls[tmdb_movie.id] = calls.get(tmdb_movie.id, 0) + 1
        if tmdb_movie.id == "404":
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404 Client Error", response=response)
        if tmdb_movie.id == "99" or (tmdb_movie.id == "7" and calls[tmdb_movie.id] <= 2):
            raise requests.ConnectionError("Connection aborted")
        return {"title": f"Película {tmdb_movie.id}", "release_date": "2024-01-01", "genres": [{"id": 28}], "runtime": 100}
    monkeypatch.setattr(tmdbsimple.Movies, "info", info)

def test_pipeline(tmp_path, monkeypatch, capsys):
    fake_tmdb(monkeypatch)
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    for name in ["Good (2024) {tmdb-1}.mkv", "Wrong id (2020) {tmdb-404}.mkv", "Flaky network (2021) {tmdb-7}.mkv",
                 "Network down (2022) {tmdb-99}.mkv", "No tag (2019).mkv"]:
        (source / name).write_bytes(b"movie")

    shared_state.movies.extend(FolderReader(str(source)).read())
    tmdb_queue, split_queue, upload_queue, done_queue = Queue(), Queue(), Queue(), Queue()
    for movie in shared_state.movies:
        tmdb_queue.put(movie)
    tmdb_queue.put(None)
    stages = [
        TmdbApiClient(tmdb_queue, split_queue),
        FileSplitter(split_queue, upload_queue, str(destination), 4000),
        FakeUpload(upload_queue, done_queue),
    ]
    for stage in stages:
        stage.start()
    for stage in stages:
        stage.join(timeout=30)
        assert not stage.is_alive(), f"{stage.log_name} did not finish"

    statuses = {movie.tmdb_id: movie.status for movie in shared_state.movies}
    assert statuses == {"1": FileStatus.UPLOADED, "7": FileStatus.UPLOADED, "404": FileStatus.ERROR, "99": FileStatus.ERROR}
    good = next(movie for movie in shared_state.movies if movie.tmdb_id == "1")
    assert (good.title, good.year, good.genres, good.duration) == ("Película 1", "2024", ["Acción"], 100)
    assert (destination / "Good (2024) {tmdb-1}" / "Good (2024) {tmdb-1}.mkv").is_file()

    capsys.readouterr()
    print_summary()
    output = capsys.readouterr().out
    assert "Uploaded: 2 of 5 movies" in output
    assert "ERRORS (3)" in output
    assert "No {tmdb-<id>} tag in the file name" in output
    assert "Movie not found in TMDB" in output
    assert "Connection aborted (failed after 3 attempts)" in output
