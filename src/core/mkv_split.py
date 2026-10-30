"""
Splits an MKV into playable MKV parts with mkvmerge, from MKVToolNix (an external program).
"""
import os
import re
import shutil
import subprocess

from core.utils import check_path_length

WINDOWS_MKVMERGE_PATH = r"C:\Program Files\MKVToolNix\mkvmerge.exe"   # The Windows installer may not add it to PATH
MKVMERGE_OK_CODES = (0, 1)   # 1 means finished with warnings, the parts are fine
PART_NUMBER_REGEX = re.compile(r" pt(\d+)\.mkv$")

def find_mkvmerge():
    """
    Returns the path of mkvmerge, or None if it is not installed.
    """
    path = shutil.which("mkvmerge")
    if path:
        return path
    return WINDOWS_MKVMERGE_PATH if os.path.isfile(WINDOWS_MKVMERGE_PATH) else None

def list_mkv_parts(folder):
    """
    Returns the names of the MKV parts of the folder, in order by number (pt2 before pt10).
    """
    names = [name for name in os.listdir(folder) if PART_NUMBER_REGEX.search(name)]
    return sorted(names, key=lambda name: int(PART_NUMBER_REGEX.search(name).group(1)))

def create_mkv_parts(mkvmerge, source_path, folder, base_name, part_size_mb):
    """
    Splits source_path with the mkvmerge program at keyframes into parts in folder: "<base_name> pt1.mkv", "<base_name> pt2.mkv"...
    Returns the paths of the parts, in order. A part can end over part_size_mb, by up to the distance between keyframes.
    base_name must not contain %: mkvmerge replaces %d in the output name with the number of the part.
    """
    check_path_length(os.path.join(folder, f"{base_name} pt99.mkv"))
    # Run from the folder, so only the file name is read as a format, not the rest of the path
    result = subprocess.run([mkvmerge, "--output", f"{base_name} pt%d.mkv", "--split", f"size:{part_size_mb}M", os.path.abspath(source_path)],
                            cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode not in MKVMERGE_OK_CODES:
        # mkvmerge writes its errors to stdout, the last line says what happened
        lines = result.stdout.strip().splitlines()
        raise RuntimeError(f"mkvmerge failed: {lines[-1] if lines else f'exit code {result.returncode}'}")
    parts = list_mkv_parts(folder)
    if not parts:
        raise RuntimeError(f"mkvmerge finished but there are no \"{base_name} ptN.mkv\" files in {folder}")
    return [os.path.join(folder, name) for name in parts]
