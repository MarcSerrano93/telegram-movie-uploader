"""
Reads the source folder, before the pipeline starts.
"""
import os

from constants import MOVIE_FILE_EXTENSION, Step
from movie import Movie
from utils import report_failure

class FolderReader:
    def __init__(self, folder_path: str):
        self.folder_path = folder_path

    def read(self):
        """
        Returns a Movie for each .mkv file of the folder (not subfolders).
        Files without the {tmdb-<id>} tag are reported as READ errors and skipped.
        """
        movies = []
        for entry in os.scandir(self.folder_path):
            if entry.is_file() and entry.name.lower().endswith(MOVIE_FILE_EXTENSION):
                movie = Movie(entry.path)
                if movie.tmdb_id is None:
                    report_failure(Step.READ, entry.name, "No {tmdb-<id>} tag in the file name")
                    continue
                movies.append(movie)
        return movies
