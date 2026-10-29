"""
Stage 1 of the movies pipeline: fetches the info of each movie from TMDB.
"""
from queue import Queue

from core import tmdb
from core.constants import LogColor, Step
from core.pipeline_stage import PipelineStage
from core.utils import with_retries
from movies.movie import Movie
from movies.tmdb_constants import GENRES

NOT_FOUND_MESSAGE = "Movie not found in TMDB, check the id in the file name"

class MovieTmdbApiClient(PipelineStage):
    step = Step.TMDB
    log_name = "MovieTmdbApiClient"
    log_color = LogColor.LIGHT_GREEN

    def __init__(self, input_queue: Queue, output_queue: Queue):
        super().__init__(input_queue, output_queue)

    def _parse_genres(self, genre_ids: list):
        return [GENRES[genre_id] for genre_id in genre_ids if genre_id in GENRES]

    def _get_info(self, movie: Movie, language):
        return with_retries(self.step, movie.file_name, lambda: tmdb.get_info(f"movie/{movie.tmdb_id}", language, NOT_FOUND_MESSAGE))

    def process(self, movie: Movie):
        """
        Fills the movie with its TMDB info. Two requests: Spanish for most fields, English for the second title.
        """
        info_es = self._get_info(movie, tmdb.LANGUAGE_ES)

        title = info_es.get("title") or info_es.get("original_title") or str(movie.tmdb_id)
        release_date = info_es.get("release_date") or ""
        year = release_date[:4]
        genre_ids = [genre["id"] for genre in info_es.get("genres", []) if "id" in genre]
        genres = self._parse_genres(genre_ids)
        poster = tmdb.image_url(tmdb.POSTER_BASE_URL, info_es.get("poster_path"))
        duration_min = info_es.get("runtime") or 0

        info_en = self._get_info(movie, tmdb.LANGUAGE_EN)
        title_en = info_en.get("title") or info_en.get("original_title") or title
        self.log(f"Info obtained for the movie {movie.tmdb_id} - {title}")
        movie.set_movie_metadata(title, title_en, year, genres, duration_min, poster)
