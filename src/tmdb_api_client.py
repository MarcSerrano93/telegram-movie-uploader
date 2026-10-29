"""
Stage 1 of the pipeline: fetches the info of each movie from TMDB.
"""
import os
from queue import Queue

import requests
import tmdbsimple as tmdb

from constants import LogColor, Step
from movie import Movie
from pipeline_stage import PipelineStage
from tmdb_constants import GENRES, LANGUAGE_EN, LANGUAGE_ES, POSTER_BASE_URL
from utils import PermanentError, with_retries

class TmdbApiClient(PipelineStage):
    step = Step.TMDB
    log_name = "TmdbApiClient"
    log_color = LogColor.LIGHT_GREEN

    def __init__(self, input_queue: Queue, output_queue: Queue):
        super().__init__(input_queue, output_queue)
        tmdb.API_KEY = os.getenv("API_KEY")

    def _parse_genres(self, genre_ids: list):
        return [GENRES[genre_id] for genre_id in genre_ids if genre_id in GENRES]

    def _get_info(self, tmdb_movie, language):
        try:
            return tmdb_movie.info(language=language)
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code == 404:
                raise PermanentError("Movie not found in TMDB, check the id in the file name") from e
            if status_code == 401:
                raise PermanentError("Invalid TMDB API key") from e
            raise

    def process(self, movie: Movie):
        """
        Fills the movie with its TMDB info. Two requests: Spanish for most fields, English for the second title.
        """
        tmdb_movie = tmdb.Movies(movie.tmdb_id)
        info_es = with_retries(self.step, movie.file_name, lambda: self._get_info(tmdb_movie, LANGUAGE_ES))

        title = info_es.get("title") or info_es.get("original_title") or str(movie.tmdb_id)
        release_date = info_es.get("release_date") or ""
        year = release_date[:4]
        genre_ids = [genre["id"] for genre in info_es.get("genres", []) if "id" in genre]
        genres = self._parse_genres(genre_ids)
        poster_path = info_es.get("poster_path")
        poster = POSTER_BASE_URL + poster_path if poster_path else ""
        duration_min = info_es.get("runtime") or 0

        info_en = with_retries(self.step, movie.file_name, lambda: self._get_info(tmdb_movie, LANGUAGE_EN))
        title_en = info_en.get("title") or info_en.get("original_title") or title
        self.log(f"Info obtained for the movie {movie.tmdb_id} - {title}")
        movie.set_movie_metadata(title, title_en, year, genres, duration_min, poster)
