"""
A TV show folder with its episodes grouped by season, its TMDB info and its status in the pipeline.
"""
import os

from core.constants import FileStatus
from core.tmdb import parse_tmdb_id

BACKDROP_CAPTION_START = "🇪🇸 |"   # Start of the backdrop caption, how it is found in the topic

class Season:
    def __init__(self, number, episode_count=0, poster_path=""):
        self.number = number
        self.episode_count = episode_count
        self.poster_path = poster_path

    def generate_telegram_caption(self):
        return f"**..--== Temporada {self.number} ==--..\n..--== ({self.episode_count} episodios) ==--..**"

    def __repr__(self):
        return f"Season(number={self.number}, episode_count={self.episode_count}, poster_path='{self.poster_path}')"

class Show:
    def __init__(self, folder_path, episodes):
        """
        episodes: {season number: [episode file names, in order]}
        """
        self.folder_path = folder_path
        self.file_name = os.path.basename(folder_path)   # Shown in the logs and the summary
        self.tmdb_id = parse_tmdb_id(self.file_name)
        self.episodes = episodes
        self.name = ""      # English, used for the topic
        self.name_es = ""
        self.year = ""
        self.backdrop_path = ""
        self.poster_path = ""
        self.seasons = {}   # {season number: Season}, from TMDB
        self.status = FileStatus.NONE

    def set_show_metadata(self, name, name_es, year, backdrop_path, poster_path, seasons):
        self.name = name
        self.name_es = name_es
        self.year = year
        self.backdrop_path = backdrop_path
        self.poster_path = poster_path
        self.seasons = seasons
        self.status = FileStatus.PARSED

    def get_season(self, number):
        """
        Returns the season from TMDB or, if TMDB does not have it, one without poster and with the local episode count.
        """
        return self.seasons.get(number) or Season(number, len(self.episodes.get(number, [])))

    def generate_telegram_caption(self, topic_link=None):
        """
        Returns the text of the backdrop message in the topic and, with topic_link, of the poster in the General topic.
        """
        caption = (
            f"{BACKDROP_CAPTION_START} {self.name_es}\n"
            f"🇬🇧 | {self.name}\n"
            f"📅 | {self.year}\n"
            f"🌐 | [TMDB](https://www.themoviedb.org/tv/{self.tmdb_id})"
        )
        if topic_link:
            caption += f"\n\n👉 | [¡Ir a la serie!]({topic_link})"
        return f"**{caption}**"

    def __repr__(self):
        return f"Show(id={self.tmdb_id}, name='{self.name}', year='{self.year}', seasons={sorted(self.episodes)})"
