# telegram-movie-uploader

Uploads a folder of movies or TV shows to a Telegram forum group, one topic per movie or show, with
the info and images from TMDB. It has two modes, one per run:

- `movies`: one `.mkv` file per movie, split into zip parts if it is bigger than the Telegram limit.
- `tv`: one folder per show, uploaded season by season.

At the end it prints a summary with every movie or show that failed and the step where it failed,
plus warnings (e.g. a missing image in TMDB). Temporary errors (network, locked files...) are retried
up to 3 times.

### Movies mode

For each `.mkv` file in the source folder, the program:

1. Reads the TMDB id from the file name.
2. Fetches the movie info from TMDB (Spanish title, English title, year, genres, runtime, poster).
3. If the file is bigger than `telegram_size_limit_mb`, splits it into a multi-part zip (`.zip.001`,
   `.zip.002`...) in a temporary folder inside the destination folder. It is the same format as 7-Zip's
   split archives, opened with 7-Zip or WinRAR.
4. Finds the movie's topic in the Telegram group, or creates it, posts the poster with a caption
   and uploads the file or parts.
5. Once uploaded, moves the original file to its own folder inside the destination folder and deletes
   the parts. Until then everything stays in place, so a failed upload can be run again.

Optionally, each movie also goes to a second group as MKV files that play without unzipping
(`mkv_parts_enabled`, needs [MKVToolNix](https://mkvtoolnix.download)). Movies bigger than the limit are
split into playable parts (` pt1.mkv`, ` pt2.mkv`...), smaller ones are sent as they are. The topic and
poster are the same as in the main group.

### TV mode

For each show folder in the source folder, the program:

1. Reads the TMDB id from the folder name and groups the episodes by season. If an episode is
   bigger than `telegram_size_limit_mb`, the whole show is skipped.
2. Fetches the show info from TMDB (English and Spanish name, year, backdrop, poster, and the
   episode count and poster of each season).
3. Finds the show's topic in the Telegram group, or creates it, named in English, and fills it with:
   - the backdrop with the show info, and the poster in the General topic with a link to the topic
     (only the first time);
   - for each season: its poster with "Temporada N (X episodios)", then its episodes.

The episode files stay in the source folder. If TMDB has no image, or Telegram cannot download it,
a default image from `media/` is sent instead.

## Requirements

- Python 3.11+ (tested with 3.12). The setup commands below are for Windows PowerShell
- A Telegram account and API credentials from https://my.telegram.org
  (Telegram Premium is needed to upload files bigger than 2000 MB)
- A Telegram supergroup with topics enabled, where your account can create topics
- A TMDB API key from https://www.themoviedb.org/settings/api
- Only for `mkv_parts_enabled`: `mkvmerge`, from [MKVToolNix](https://mkvtoolnix.download), installed or
  portable (see `mkvmerge_path` below). On Debian or Ubuntu: `apt-get install mkvtoolnix`

## File naming

Movies and shows are found by their TMDB id, written in the name as `{tmdb-<id>}`. Movies or shows
without the tag are skipped and shown as `READ` errors in the summary.

**Movies:** one file per movie, directly in the source folder. The extension is matched in any case
(`.mkv`, `.MKV`...).

```
Movie Title (2024) {tmdb-112233}.mkv
```

**TV shows:** one folder per show, with all its episodes directly inside (no season subfolders). The
season and episode are read from the `<season>x<episode> - ` part of the name. Other files in the
folder are skipped with a warning.

```
Show Name (2008) {tmdb-1396}/
  1x01 - Pilot.mkv
  1x02 - Cat's in the Bag.mkv
  2x01 - Seven Thirty-Seven.mkv
```

## Setup

Create and activate a virtual environment (PowerShell):

```
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install the dependencies:

```
pip install -r requirements.txt
pip install --no-deps FastTelethonhelper==1.0.7
```

`FastTelethonhelper` (parallel uploads, much faster than plain Telethon for big files) is installed
with `--no-deps` because it depends on `TgCrypto`, which has no prebuilt package for Python 3.12+
and would need the Visual C++ Build Tools to compile. `cryptg`, listed in `requirements.txt`,
replaces it: Telethon uses it automatically for fast encryption.

Create a `.env` file in the project root:

```
# Telegram
API_ID=
API_HASH=
PHONE_NUMBER=

# TMDB
API_KEY=
```

Copy `config.example.json` to `config.json` and fill it in:

```json
{
    "telegram_size_limit_mb": 4000,
    "movies": {
        "source_files_path": "E:/Movies/ToUpload/",
        "destination_files_path": "E:/Movies/Uploaded/",
        "telegram_group": "https://t.me/+yourMoviesGroupInviteLink",
        "mkv_parts_enabled": false,
        "mkv_parts_telegram_group": "https://t.me/+yourMkvGroupInviteLink",
        "mkvmerge_path": "C:/Tools/mkvtoolnix/mkvmerge.exe"
    },
    "tv": {
        "source_files_path": "E:/TV/ToUpload/",
        "telegram_group": "https://t.me/+yourTvGroupInviteLink"
    }
}
```

| Field | Description |
|---|---|
| `telegram_size_limit_mb` | Telegram upload limit of your account, in MB (4000 with Premium, 2000 without). Bigger movies are split into parts of up to this size, shows with a bigger episode are skipped |
| `movies` | Settings of the movies mode |
| `movies.source_files_path` | Folder with the `.mkv` files to upload |
| `movies.destination_files_path` | Folder where parts are created and uploaded files are moved (must exist) |
| `movies.telegram_group` | Invite link or @username of the Telegram group (your account must be a member) |
| `movies.mkv_parts_enabled` | Optional, `false` by default. Also upload each movie as MKV files to a second group |
| `movies.mkv_parts_telegram_group` | The second group, different from `movies.telegram_group`. Only needed if enabled |
| `movies.mkvmerge_path` | Optional. Path of `mkvmerge`, e.g. for a portable copy. Without it, it is looked for in the `PATH` and in `C:\Program Files\MKVToolNix\` |
| `tv` | Settings of the TV mode |
| `tv.source_files_path` | Folder with one subfolder per show |
| `tv.telegram_group` | Invite link or @username of the Telegram group (your account must be a member) |

Only the section of the mode being run is checked, so you only need the sections of the modes you use.

## Usage

With the virtual environment activated, from the project root:

```
python src/main.py movies
python src/main.py tv
```

`config.json`, `.env` and `uploader.session` are always read from the project root, so the
script also works when started from another folder. If something is missing or wrong in `config.json`
or `.env`, it stops before doing anything and says what, e.g. `Invalid config file: API_KEY is missing in .env`.

On the first run Telegram asks for the login code sent to your account (and your password, if
two-step verification is enabled). The session is then saved in `uploader.session`, so later runs
log in automatically.

> `.env`, `config.json` and `uploader.session` are private (account access and group invite links):
> they are in `.gitignore`, never commit or share them.

### Result in movies mode

Each movie gets a folder in the destination named after the source file. Split parts are named after
the TMDB title. While a big movie is being uploaded, its folder has the parts:

```
Uploaded/
  Movie Title (2024) {tmdb-112233}/
    zip_files/
      Título (2024).zip.001
      Título (2024).zip.002
    mkv_parts/                              <- only with mkv_parts_enabled
      Título (2024) {tmdb-112233} pt1.mkv
      Título (2024) {tmdb-112233} pt2.mkv
```

After a successful upload the parts are deleted and only the original is left:

```
Uploaded/
  Movie Title (2024) {tmdb-112233}/
    Movie Title (2024) {tmdb-112233}.mkv
```

Big movies wait for the uploads before being split, so with `mkv_parts_enabled` the parts of up to 5
movies can be on disk at once, at different stages. For 5 GB movies, keep about 40 GB free in the
destination folder.

On Windows, the full path of each part must fit in 259 characters. If the destination folder, the source
file name and the TMDB title together are too long, the movie stops with a `Path too long` error.

In Telegram, each movie has a topic named `Title (Year) {tmdb-112233}` with the poster message and
one message with all the files (in albums of up to 10 files, Telegram's limit).

### Result in TV mode

Each show has a topic named `Name (Year) {tmdb-1396}`, with the English name, containing the backdrop
message and, for each season, its poster followed by its episodes in albums of up to 10. The General
topic gets the show poster with a "¡Ir a la serie!" link to the topic.

### Running it again after a failure, or with new episodes

Fix the problem shown in the summary and run the script again. Already processed work is not repeated:

- Files already split (their `zip_files` or `mkv_parts` folder exists) are not split again.
- The existing topic is found by its `{tmdb-<id>}` tag and reused, no duplicate is created.
- The posters, backdrop and any files already in the topic are skipped; only the missing ones are uploaded.
  Files are recognized by name, so a renamed file is uploaded again.

To add a new season of a show, put its episodes in the show folder and run the TV mode again: only
the new season's poster and episodes are sent, nothing is posted in General. The episodes already in
the topic can stay in the folder or be removed from it.

Files uploaded on a resumed run arrive as a separate message, not inside the original album.

## Running the tests

The tests run offline: TMDB, Telegram and `mkvmerge` are replaced by fakes, so no `.env`, `config.json`,
account or MKVToolNix is needed. The test that opens the zip parts with the real 7-Zip is skipped if `7z.exe` is not in the
project root.

```
pip install -r requirements-dev.txt
pytest
```

## Project structure

| File | Description |
|---|---|
| `src/main.py` | Entry point: reads the mode, loads the config and runs the pipeline of the mode |
| **`src/core/`** | **Shared by every mode** |
| `config.py` | Loads and validates `config.json` and `.env` |
| `pipeline_stage.py` | Base class of the stages, each one a thread connected by queues |
| `tmdb.py` | TMDB requests and the `{tmdb-<id>}` tag |
| `telegram_api_client.py` | Base of the upload stage: connection, topics, file uploads in albums |
| `zip_split.py` | Creates the multi-part zips |
| `mkv_split.py` | Finds and runs `mkvmerge` to create playable MKV parts |
| `utils.py` | Retries, error/warning reporting and the final summary |
| `constants.py` | Shared constants |
| `shared_state.py` | Items, errors and warnings shared by the stages, for the final summary |
| **`src/movies/`** | **Movies mode** |
| `pipeline.py` | The stages of the mode: TMDB -> zip parts -> MKV parts (optional) -> upload |
| `folder_reader.py` | Lists the `.mkv` files of the source folder |
| `tmdb_api_client.py` | Stage 1: fetches the movie info from TMDB |
| `tmdb_constants.py` | Spanish genre names |
| `file_splitter.py` | Stage 2: splits big movies into zip parts |
| `mkv_splitter.py` | Optional stage 3: splits big movies into MKV parts |
| `telegram_api_client.py` | Last stage: creates the topic, uploads the poster and files in each group and deletes the parts |
| `movie.py` | Movie data and the Telegram caption |
| **`src/tv/`** | **TV mode** |
| `pipeline.py` | The stages of the mode: TMDB -> upload |
| `folder_reader.py` | Lists the show folders and groups their episodes by season |
| `tmdb_api_client.py` | Stage 1: fetches the show and season info from TMDB |
| `telegram_api_client.py` | Stage 2: creates the topic and uploads the images and episodes |
| `show.py` | Show and season data and the Telegram captions |
| `media/` | Default images, sent when TMDB has none |
| `tests/` | Offline tests of every stage and of the whole pipelines (`pytest`) |

## License

[MIT](LICENSE): free to use, modify and share.
