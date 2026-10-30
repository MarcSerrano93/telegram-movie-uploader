from movies.movie import Movie

def test_movie_reads_id_from_file_name_not_folder():
    movie = Movie("C:/Movies {tmdb-999}/Movie (2024) {tmdb-5}.mkv")
    assert movie.file_name == "Movie (2024) {tmdb-5}.mkv"
    assert movie.tmdb_id == "5"

def make_caption(title, title_en, genres=(), duration=136):
    movie = Movie("Movie {tmdb-603}.mkv")
    movie.set_movie_metadata(title, title_en, "1999", list(genres), duration, "")
    return movie.generate_telegram_poster_caption()

def test_caption_format():
    assert make_caption("Matrix", "The Matrix", ["Acción", "CienciaFicción"]) == (
        "🎬| **Matrix** __(The Matrix)__\n"
        "\n"
        "📆| 1999\n"
        "⏱| 2h 16m\n"
        "🎭| #Acción\n"
        "🎭| #CienciaFicción\n"
        "\n"
        "🌐 | [TMDB](https://www.themoviedb.org/movie/603)"
    )

def test_caption_removes_english_title_from_spanish_one():
    assert make_caption("Matrix (The Matrix)", "The Matrix").startswith("🎬| **Matrix** __(The Matrix)__")

def test_caption_keeps_both_titles_when_equal():
    assert make_caption("Up", "Up").startswith("🎬| **Up** __(Up)__")

def test_caption_shows_up_to_5_genres():
    caption = make_caption("Matrix", "The Matrix", ["a", "b", "c", "d", "e", "f"])
    assert caption.count("🎭|") == 5
    assert "#f" not in caption

def test_caption_starts_like_telegram_client_expects():
    # MovieTelegramApiClient detects an already sent text poster by this start
    from movies.telegram_api_client import POSTER_CAPTION_START
    assert make_caption("Matrix", "The Matrix").startswith(POSTER_CAPTION_START)

def test_general_caption_is_bold_except_the_title():
    movie = Movie("Movie {tmdb-603}.mkv")
    movie.set_movie_metadata("Matrix", "The Matrix", "1999", ["Acción"], 136, "")

    assert movie.generate_telegram_poster_caption("https://t.me/c/1/2") == (
        "🎬| **Matrix** __(The Matrix)__\n"
        "\n"
        "**📆| 1999**\n"
        "**⏱| 2h 16m**\n"
        "**🎭| #Acción**\n"
        "\n"
        "**🌐 | [TMDB](https://www.themoviedb.org/movie/603)**\n"
        "\n"
        "**👉 | [¡Ir a la película!](https://t.me/c/1/2)**"
    )

def test_topic_caption_stays_without_bold():
    assert "**📆" not in make_caption("Matrix", "The Matrix")
