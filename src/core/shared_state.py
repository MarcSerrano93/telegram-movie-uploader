"""
State shared by the stage threads, used for the final summary. Lock mutex to access it.
"""
from threading import Lock

mutex = Lock()
items = []      # Every item (movie...) read from the source folder
errors = []     # (step, file name, reason) of every error, shown in the final summary
warnings = []   # (step, file name, reason) of every warning, shown in the final summary
