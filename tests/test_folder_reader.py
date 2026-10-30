from conftest import error_reasons
from movies.folder_reader import FolderReader

def test_reads_tagged_mkv_files(tmp_path):
    for name in ["A (2024) {tmdb-1}.mkv", "B (2024) {tmdb-2}.MKV", "C (2024) {tmdb-3}.mp4", "D {tmdb-4}.mkv.txt"]:
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "Folder {tmdb-5}.mkv").mkdir()

    movies = FolderReader(str(tmp_path)).read()

    assert sorted(movie.tmdb_id for movie in movies) == ["1", "2"]
    assert error_reasons() == []

def test_reports_files_without_tag(tmp_path):
    (tmp_path / "A (2024) {tmdb-1}.mkv").write_bytes(b"")
    (tmp_path / "No tag (2024).mkv").write_bytes(b"")

    movies = FolderReader(str(tmp_path)).read()

    assert [movie.tmdb_id for movie in movies] == ["1"]
    assert error_reasons() == [("READ", "No tag (2024).mkv", "No {tmdb-<id>} tag in the file name")]

def test_filter_only_reads_the_matching_files_in_any_case(tmp_path):
    (tmp_path / "Matrix (1999) {tmdb-1}.mkv").write_bytes(b"")
    (tmp_path / "Other (2024) {tmdb-2}.mkv").write_bytes(b"")

    movies = FolderReader(str(tmp_path), "MATRIX").read()

    assert [movie.tmdb_id for movie in movies] == ["1"]

def test_files_outside_the_filter_report_nothing(tmp_path):
    (tmp_path / "No tag (2024).mkv").write_bytes(b"")

    assert FolderReader(str(tmp_path), "matrix").read() == []
    assert error_reasons() == []

def test_filter_still_reports_a_matching_file_without_tag(tmp_path):
    (tmp_path / "Matrix.mkv").write_bytes(b"")

    assert FolderReader(str(tmp_path), "matrix").read() == []
    assert error_reasons() == [("READ", "Matrix.mkv", "No {tmdb-<id>} tag in the file name")]

def test_empty_folder(tmp_path):
    assert FolderReader(str(tmp_path)).read() == []
