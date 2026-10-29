"""
Reads the TV source folder, before the pipeline starts: one subfolder per show, with the episodes inside.
"""
import os
import re

from core.constants import Step
from core.tmdb import parse_tmdb_id
from core.utils import format_size, report_failure, report_warning
from tv.show import Show

EPISODE_REGEX = re.compile(r"(\d+)x(\d+)\s-")    # "1x01 - Pilot.mkv": season 1, episode 1

class ShowFolderReader:
    def __init__(self, folder_path: str, telegram_size_limit_mb):
        self.folder_path = folder_path
        self.size_limit = telegram_size_limit_mb * 1024 * 1024

    def read(self):
        """
        Returns a Show for each subfolder. Shows without the {tmdb-<id>} tag, without episodes or with an episode
        bigger than the Telegram limit are reported as READ errors and skipped.
        """
        shows = []
        for entry in sorted(os.scandir(self.folder_path), key=lambda entry: entry.name):
            if entry.is_dir():
                show = self._read_show(entry)
                if show:
                    shows.append(show)
        return shows

    def _read_show(self, folder):
        if parse_tmdb_id(folder.name) is None:
            report_failure(Step.READ, folder.name, "No {tmdb-<id>} tag in the folder name")
            return None
        episodes = {}
        for entry in os.scandir(folder.path):
            if not entry.is_file():
                continue
            match = EPISODE_REGEX.search(entry.name)
            if not match:
                report_warning(Step.READ, folder.name, f"\"{entry.name}\" is not an episode (no \"1x01 - \" in the name), skipped")
                continue
            if entry.stat().st_size > self.size_limit:
                report_failure(Step.READ, folder.name, f"\"{entry.name}\" ({format_size(entry.stat().st_size)}) is bigger than the Telegram limit, show skipped")
                return None
            episodes.setdefault(int(match.group(1)), []).append((int(match.group(2)), entry.name))

        if not episodes:
            report_failure(Step.READ, folder.name, "No episodes in the folder (named like \"1x01 - Title.mkv\")")
            return None
        # Seasons in order, and the episodes of each season in order: {1: ["1x01 - ...", "1x02 - ..."], 2: [...]}
        return Show(folder.path, {season: [name for _, name in sorted(files)] for season, files in sorted(episodes.items())})
