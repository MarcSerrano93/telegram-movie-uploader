"""
Base class of the pipeline stages (see PipelineStage).
"""
import threading
from queue import Queue

from core.constants import FileStatus, LogColor, Step
from core.utils import report_failure

class PipelineStage(threading.Thread):
    """
    Base class of the pipeline threads (e.g. TMDB -> split -> upload).

    Takes items (movies...) from input_queue, processes them and passes the successful ones to output_queue.
    Items must have file_name (shown in logs and in the summary) and status.
    A failed item is reported and dropped, and the stage goes on with the next one.
    A None in the queue marks the end of the list: it is passed to the next stage and the thread finishes.
    An item is only in one stage at a time, so its fields are changed without locking.
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

    def process(self, item):
        raise NotImplementedError

    def fail(self, item, error):
        report_failure(self.step, item.file_name, error)
        item.status = FileStatus.ERROR

    def run(self):
        while (item := self.input_queue.get()) is not None:
            try:
                self.process(item)
            except Exception as e:
                self.fail(item, e)
                continue
            self.output_queue.put(item)
        self.output_queue.put(None)
        self.log("Closing thread")
