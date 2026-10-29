"""
Entry point: "python src/main.py <mode>". Loads config.json and .env, reads the source folder of the mode
and runs its pipeline stages in parallel threads, then prints the summary.
"""
import argparse
import os
from queue import Queue

from dotenv import load_dotenv

import movies.pipeline
import tv.pipeline
from core import shared_state
from core.config import Config, ConfigError, MODES
from core.constants import PROJECT_ROOT
from core.utils import print_summary

PIPELINES = {"movies": movies.pipeline, "tv": tv.pipeline}

def main():
    parser = argparse.ArgumentParser(description="Uploads media to a Telegram forum group, one topic per item.")
    parser.add_argument("mode", choices=MODES, help="what to upload")
    mode = parser.parse_args().mode

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    try:
        config = Config(mode)
    except ConfigError as e:
        print(f"Invalid config file: {e}")
        return
    pipeline = PIPELINES[mode]
    shared_state.items.extend(pipeline.read_items(config))

    # Each stage passes the items it processed successfully to the next one through a queue
    input_queue = Queue()
    stages = pipeline.create_stages(config, input_queue)
    for item in shared_state.items:
        input_queue.put(item)
    input_queue.put(None)   # End of the list

    for stage in stages:
        stage.start()
    for stage in stages:
        stage.join()

    print_summary(pipeline.ITEM_LABEL)

if __name__ == "__main__":
    main()
