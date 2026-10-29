"""
Stage 1 of the TV pipeline: fetches the info of each show and its seasons from TMDB.
"""
from queue import Queue

from core import tmdb
from core.constants import LogColor, Step
from core.pipeline_stage import PipelineStage
from core.utils import with_retries
from tv.show import Season, Show

NOT_FOUND_MESSAGE = "Show not found in TMDB, check the id in the folder name"

class ShowTmdbApiClient(PipelineStage):
    step = Step.TMDB
    log_name = "ShowTmdbApiClient"
    log_color = LogColor.LIGHT_GREEN

    def __init__(self, input_queue: Queue, output_queue: Queue):
        super().__init__(input_queue, output_queue)

    def _get_info(self, show: Show, language):
        return with_retries(self.step, show.file_name, lambda: tmdb.get_info(f"tv/{show.tmdb_id}", language, NOT_FOUND_MESSAGE))

    def process(self, show: Show):
        """
        Fills the show with its TMDB info. Two requests: English for everything (the topic is named in English),
        Spanish for the Spanish name.
        """
        info_en = self._get_info(show, tmdb.LANGUAGE_EN)
        name = info_en.get("name") or info_en.get("original_name") or str(show.tmdb_id)
        year = (info_en.get("first_air_date") or "")[:4]
        backdrop = tmdb.image_url(tmdb.BACKDROP_BASE_URL, info_en.get("backdrop_path"))
        poster = tmdb.image_url(tmdb.POSTER_BASE_URL, info_en.get("poster_path"))
        seasons = {}
        for season in info_en.get("seasons") or []:
            number = season.get("season_number")
            if number is not None:
                seasons[number] = Season(number, season.get("episode_count") or 0, tmdb.image_url(tmdb.POSTER_BASE_URL, season.get("poster_path")))

        info_es = self._get_info(show, tmdb.LANGUAGE_ES)
        name_es = info_es.get("name") or name
        self.log(f"Info obtained for the show {show.tmdb_id} - {name}")
        show.set_show_metadata(name, name_es, year, backdrop, poster, seasons)
