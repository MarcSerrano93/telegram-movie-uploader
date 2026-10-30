"""
A movie file with its TMDB info and its status in the pipeline.
"""
import os
import re

from core.constants import FileStatus
from core.tmdb import parse_tmdb_id

CAPTION_MAX_GENRES = 5
INVALID_FILE_NAME_CHARS = r'[<>:"/\\|?*]'

def make_general_caption(caption, topic_link):
    """
    Returns the text for the General topic from the text of a poster message in markdown:
    every line in bold except the first one (the title, which has its own format), and a link to the topic.
    """
    title, *lines = f"{caption}\n\n👉 | [¡Ir a la película!]({topic_link})".split("\n")
    return "\n".join([title, *(f"**{line}**" if line and "**" not in line else line for line in lines)])

class Movie:
    def __init__(self, file_full_path):
        self.file_full_path = file_full_path
        self.file_name = os.path.basename(file_full_path)
        self.destination_path = ""
        self.zip_parts_path = ""    # Only for movies split into zip parts
        self.mkv_parts_path = ""    # Only for movies split into MKV parts
        self.title = ""
        self.title_en = ""
        self.year = ""
        self.tmdb_id = self.get_tmdb_id_from_path()
        self.genres = []
        self.duration = 0
        self.poster_path = ""
        self.status = FileStatus.NONE

    def get_tmdb_id_from_path(self):
        # File names look like "Movie (2024) {tmdb-112233}.mkv"
        return parse_tmdb_id(self.file_name)

    def set_movie_metadata(self, title, title_en, year, genres, duration_min, poster_path):
        self.title = title
        self.title_en = title_en
        self.year = year
        self.genres = genres
        self.duration = duration_min
        self.poster_path = poster_path
        self.status = FileStatus.PARSED

    def get_file_title(self):
        """
        Returns the base name of the parts of the movie: "Title (Year)", without characters not allowed in file names.
        """
        return f"{re.sub(INVALID_FILE_NAME_CHARS, '.', self.title)} ({self.year})"

    def generate_telegram_poster_caption(self, topic_link=None):
        """
        Returns the text of the poster message: titles, year, runtime, up to 5 genres as hashtags and the TMDB link.
        If the Spanish title already contains "(English title)", it is removed so it is not shown twice.
        With topic_link, the text for the General topic (see make_general_caption).
        """
        regex = r"\(\s*" + re.escape(self.title_en) + r"\s*\)"
        title_es = re.sub(regex, "", self.title).rstrip()
        title = f"🎬| **{title_es}** __({self.title_en})__"
        year = f"📆| {self.year}"
        hours, minutes = divmod(self.duration, 60)
        duration = f"⏱| {hours}h {minutes}m"
        tmdb_link = f"🌐 | [TMDB](https://www.themoviedb.org/movie/{self.tmdb_id})"
        genres = "".join(f"\n🎭| #{genre}" for genre in self.genres[:CAPTION_MAX_GENRES])
        caption = f"{title}\n\n{year}\n{duration}{genres}\n\n{tmdb_link}"
        return make_general_caption(caption, topic_link) if topic_link else caption

    def __repr__(self):
        return (
            f"Movie(\n"
            f"    id={self.tmdb_id},\n"
            f"    name='{self.title}',\n"
            f"    year='{self.year}',\n"
            f"    poster_path='{self.poster_path}',\n"
            f"    genres='{self.genres}',\n"
            f")"
        )
