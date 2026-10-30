"""
Reads the movies source folder, before the pipeline starts.
"""
import os

from core.constants import Step
from core.utils import report_failure
from movies.movie import Movie

MOVIE_FILE_EXTENSION = ".mkv"

class FolderReader:
    def __init__(self, folder_path: str, name_filter=""):
        self.folder_path = folder_path
        self.name_filter = name_filter.casefold()

    def read(self):
        """
        Returns a Movie for each .mkv file of the folder (not subfolders) with name_filter in its name, in any case.
        Files without the {tmdb-<id>} tag are reported as READ errors and skipped.
        """
        movies = []
        for entry in os.scandir(self.folder_path):
            if entry.is_file() and entry.name.lower().endswith(MOVIE_FILE_EXTENSION) and self.name_filter in entry.name.casefold():
                movie = Movie(entry.path)
                if movie.tmdb_id is None:
                    report_failure(Step.READ, entry.name, "No {tmdb-<id>} tag in the file name")
                    continue
                movies.append(movie)
        return movies
