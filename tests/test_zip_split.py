import os
import subprocess
import zipfile

import pytest

from core.constants import PROJECT_ROOT
from core.zip_split import create_split_zip

REAL_SEVEN_ZIP = os.path.join(PROJECT_ROOT, "7z.exe")

@pytest.fixture
def source(tmp_path):
    path = tmp_path / "Movie (2024) {tmdb-1}.mkv"
    path.write_bytes(os.urandom(250_000))
    return path

def join_parts(parts, path):
    with open(path, "wb") as joined:
        for part in parts:
            with open(part, "rb") as f:
                joined.write(f.read())
    return path

def test_parts_have_the_size_and_names_asked(tmp_path, source):
    parts = create_split_zip(str(source), str(tmp_path / "Película (2024).zip"), 100_000)

    assert [os.path.basename(part) for part in parts] == ["Película (2024).zip.001", "Película (2024).zip.002", "Película (2024).zip.003"]
    assert [os.path.getsize(part) for part in parts[:2]] == [100_000, 100_000]
    assert 0 < os.path.getsize(parts[2]) <= 100_000

def test_joined_parts_are_a_zip_with_the_original_file(tmp_path, source):
    parts = create_split_zip(str(source), str(tmp_path / "Película (2024).zip"), 100_000)

    with zipfile.ZipFile(join_parts(parts, tmp_path / "joined.zip")) as archive:
        [info] = archive.infolist()
        assert info.filename == source.name
        assert info.compress_type == zipfile.ZIP_STORED
        assert archive.read(info) == source.read_bytes()

def test_small_file_gives_one_part(tmp_path, source):
    parts = create_split_zip(str(source), str(tmp_path / "Small.zip"), 10 * 1024 * 1024)
    assert [os.path.basename(part) for part in parts] == ["Small.zip.001"]

@pytest.mark.skipif(not os.path.isfile(REAL_SEVEN_ZIP), reason="7z.exe not in the project root")
def test_7zip_opens_the_parts(tmp_path, source):
    # The parts must open with 7-Zip, as the people in the group do
    parts = create_split_zip(str(source), str(tmp_path / "Película (2024).zip"), 100_000)

    result = subprocess.run([REAL_SEVEN_ZIP, "t", parts[0]], capture_output=True, text=True)

    assert result.returncode == 0
    assert "Everything is Ok" in result.stdout
