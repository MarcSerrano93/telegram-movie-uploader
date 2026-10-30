from conftest import error_reasons, warning_reasons
from tv.folder_reader import ShowFolderReader

MB = 1024 * 1024

def make_folder(source, name, files, size=10):
    folder = source / name
    folder.mkdir()
    for file_name in files:
        (folder / file_name).write_bytes(b"x" * size)
    return folder

def read(source, limit_mb=4000):
    return ShowFolderReader(str(source), limit_mb).read()

def test_episodes_are_grouped_by_season_in_order(tmp_path):
    make_folder(tmp_path, "Show (2020) {tmdb-1}", ["2x01 - C.mkv", "1x10 - B.mkv", "1x02 - A.mkv", "0x01 - Special.mkv"])

    [show] = read(tmp_path)

    assert show.tmdb_id == "1"
    assert show.file_name == "Show (2020) {tmdb-1}"
    assert show.episodes == {0: ["0x01 - Special.mkv"], 1: ["1x02 - A.mkv", "1x10 - B.mkv"], 2: ["2x01 - C.mkv"]}

def test_files_that_are_not_episodes_are_skipped_with_a_warning(tmp_path):
    make_folder(tmp_path, "Show {tmdb-1}", ["1x01 - A.mkv", "cover.jpg"])

    [show] = read(tmp_path)

    assert show.episodes == {1: ["1x01 - A.mkv"]}
    assert warning_reasons() == [("READ", "Show {tmdb-1}", "\"cover.jpg\" is not an episode (no \"1x01 - \" in the name), skipped")]

def test_folder_without_tag_fails(tmp_path):
    make_folder(tmp_path, "Show (2020)", ["1x01 - A.mkv"])

    assert read(tmp_path) == []
    assert error_reasons() == [("READ", "Show (2020)", "No {tmdb-<id>} tag in the folder name")]

def test_folder_without_episodes_fails(tmp_path):
    make_folder(tmp_path, "Show {tmdb-1}", [])

    assert read(tmp_path) == []
    assert error_reasons()[0][2].startswith("No episodes in the folder")

def test_episode_bigger_than_the_limit_skips_the_whole_show(tmp_path):
    make_folder(tmp_path, "Big {tmdb-1}", ["1x01 - A.mkv"], size=2 * MB)
    make_folder(tmp_path, "Small {tmdb-2}", ["1x01 - A.mkv"], size=MB)

    shows = read(tmp_path, limit_mb=1)

    assert [show.tmdb_id for show in shows] == ["2"]
    assert error_reasons() == [("READ", "Big {tmdb-1}", "\"1x01 - A.mkv\" (2.0 MB) is bigger than the Telegram limit, show skipped")]

def test_filter_only_reads_the_matching_folders_in_any_case(tmp_path):
    make_folder(tmp_path, "Breaking Bad {tmdb-1}", ["1x01 - A.mkv"])
    make_folder(tmp_path, "Other {tmdb-2}", ["1x01 - A.mkv"])

    shows = ShowFolderReader(str(tmp_path), 4000, "BREAKING").read()

    assert [show.tmdb_id for show in shows] == ["1"]

def test_folders_outside_the_filter_report_nothing(tmp_path):
    make_folder(tmp_path, "No tag", ["cover.jpg"])
    make_folder(tmp_path, "Breaking Bad {tmdb-1}", ["1x01 - A.mkv"])

    ShowFolderReader(str(tmp_path), 4000, "breaking").read()

    assert error_reasons() == []
    assert warning_reasons() == []

def test_files_in_the_source_folder_are_ignored(tmp_path):
    (tmp_path / "1x01 - Loose.mkv").write_bytes(b"x")
    make_folder(tmp_path, "Show {tmdb-1}", ["1x01 - A.mkv"])

    assert len(read(tmp_path)) == 1
