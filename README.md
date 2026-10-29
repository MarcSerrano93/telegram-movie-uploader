# telegram-movie-uploader

Uploads a folder of movies to a Telegram forum group, one topic per movie.

For each `.mkv` file in the source folder, the program:

1. Reads the TMDB id from the file name.
2. Fetches the movie info from TMDB (Spanish title, English title, year, genres, runtime, poster).
3. Moves the file to its own folder inside the destination folder or, if it is bigger than
   `telegram_size_limit_mb`, splits it there into a multi-part zip with 7-Zip.
4. Finds the movie's topic in the Telegram group, or creates it, posts the poster with a caption
   and uploads the file or parts.
5. Once uploaded, moves the original of a split file next to its parts.

At the end it prints a summary with every file that failed and the step where it failed, plus
warnings (e.g. a movie without a poster in TMDB). Temporary errors (network, locked files...) are
retried up to 3 times.

## Requirements

- Windows (it runs `7z.exe` and the setup commands are for PowerShell)
- Python 3.11+ (tested with 3.12)
- `7z.exe` (7-Zip command line) in the project root
- A Telegram account and API credentials from https://my.telegram.org
  (Telegram Premium is needed to upload files bigger than 2000 MB)
- A Telegram supergroup with topics enabled, where your account can create topics
- A TMDB API key from https://www.themoviedb.org/settings/api

## File naming

Every movie file must include its TMDB id in the name with this format:

```
Movie Title (2024) {tmdb-112233}.mkv
```

The extension is matched in any case (`.mkv`, `.MKV`...). Files without the `{tmdb-<id>}` tag are
skipped and shown as `READ` errors in the summary.

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
    "source_files_path": "E:/Movies/ToUpload/",
    "destination_files_path": "E:/Movies/Uploaded/",
    "telegram_size_limit_mb": 4000,
    "telegram_movie_group": "https://t.me/+yourGroupInviteLink"
}
```

| Field | Description |
|---|---|
| `source_files_path` | Folder with the `.mkv` files to upload |
| `destination_files_path` | Folder where files are moved or split (must exist) |
| `telegram_size_limit_mb` | Telegram upload limit of your account, in MB (4000 with Premium, 2000 without). Bigger files are split into parts of this size |
| `telegram_movie_group` | Invite link or @username of the Telegram group (your account must be a member) |

## Usage

With the virtual environment activated, from the project root:

```
python src/main.py
```

`config.json`, `.env`, `7z.exe` and `uploader.session` are always read from the project root, so the
script also works when started from another folder. If something is missing or wrong in `config.json`
or `.env`, it stops before doing anything and says what, e.g. `Invalid config file: API_KEY is missing in .env`.

On the first run Telegram asks for the login code sent to your account (and your password, if
two-step verification is enabled). The session is then saved in `uploader.session`, so later runs
log in automatically.

> `.env`, `config.json` and `uploader.session` are private (account access and group invite links):
> they are in `.gitignore`, never commit or share them.

### Result

Each movie gets a folder in the destination named after the source file. Split parts are named after
the TMDB title:

```
Uploaded/
  Movie Title (2024) {tmdb-112233}/
    Título (2024).zip.001
    Título (2024).zip.002
    Movie Title (2024) {tmdb-112233}.mkv    <- original, moved here after the upload
```

In Telegram, each movie has a topic named `Title (Year) {tmdb-112233}` with the poster message and
one message with all the files (in albums of up to 10 files, Telegram's limit).

### Running it again after a failure

Fix the problem shown in the summary and run the script again. Already processed work is not repeated:

- Files already split (their folder exists in the destination) are not split again.
- The existing topic is found by its `{tmdb-<id>}` tag and reused, no duplicate is created.
- The poster and any files already in the topic are skipped; only the missing ones are uploaded.

Files uploaded on a resumed run arrive as a separate message, not inside the original album.

## Running the tests

The tests run offline: TMDB and Telegram are replaced by fakes, so no `.env`, `config.json` or account is
needed. The test that splits with the real 7-Zip is skipped if `7z.exe` is not in the project root.

```
pip install -r requirements-dev.txt
pytest
```

## Project structure

| File | Description |
|---|---|
| `src/main.py` | Entry point: loads the config and runs the pipeline stages |
| `src/config.py` | Loads and validates `config.json` and `.env` |
| `src/folder_reader.py` | Lists the `.mkv` files of the source folder |
| `src/tmdb_api_client.py` | Stage 1: fetches the movie info from TMDB |
| `src/tmdb_constants.py` | TMDB languages, poster URL and genre names |
| `src/file_splitter.py` | Stage 2: moves or splits the file into the destination folder |
| `src/telegram_api_client.py` | Stage 3: creates the topic and uploads the poster and files |
| `src/pipeline_stage.py` | Base class of the stages, each one a thread connected by queues |
| `src/movie.py` | Movie data and the Telegram caption |
| `src/utils.py` | Retries, error/warning reporting and the final summary |
| `src/constants.py` | Shared constants |
| `src/shared_state.py` | Movies, errors and warnings shared by the stages, for the final summary |
| `tests/` | Offline tests of every stage and of the whole pipeline (`pytest`) |
