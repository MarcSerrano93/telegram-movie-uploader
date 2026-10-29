"""
Base class of the pipeline stages (see PipelineStage).
"""
import threading
from queue import Queue

from constants import FileStatus, LogColor, Step
from movie import Movie
from utils import report_failure

class PipelineStage(threading.Thread):
    """
    Base class of the pipeline threads (TMDB -> split -> upload).

    Takes movies from input_queue, processes them and passes the successful ones to output_queue.
    A failed movie is reported and dropped, and the stage goes on with the next one.
    A None in the queue marks the end of the list: it is passed to the next stage and the thread finishes.
    A movie is only in one stage at a time, so its fields are changed without locking.
    """
    step = Step.UNKNOWN
    log_name = ""
    log_color = LogColor.END

    def __init__(self, input_queue: Queue, output_queue: Queue | None = None):
        super().__init__()
        self.input_queue = input_queue
        self.output_queue = output_queue

    def log(self, message):
        print(f"{self.log_color}[{self.log_name}] {message}{LogColor.END}")

    def process(self, movie: Movie):
        raise NotImplementedError

    def fail(self, movie: Movie, error):
        report_failure(self.step, movie.file_name, error)
        movie.status = FileStatus.ERROR

    def run(self):
        while (movie := self.input_queue.get()) is not None:
            try:
                self.process(movie)
            except Exception as e:
                self.fail(movie, e)
                continue
            self.output_queue.put(movie)
        self.output_queue.put(None)
        self.log("Closing thread")
