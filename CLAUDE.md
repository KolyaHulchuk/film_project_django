# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Django movie/TV discovery app backed by the TMDB API. Server-rendered frontend (Django templates + HTMX + Bootstrap) plus a parallel DRF REST API with JWT auth. Features: browsing/search/filtering, personal watchlists with watched/unwatched state, ratings, comments, popular actors, and a Groq-powered AI recommendation assistant.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # note: pytest/pytest-django/pytest-mock are used by tests but NOT pinned here — install manually if missing
python manage.py migrate
python manage.py runserver

# Tests (pytest.ini sets DJANGO_SETTINGS_MODULE=config.settings)
pytest                                  # full suite
pytest movies/tests/test_movie_view.py  # single file
pytest movies/tests/test_movie_view.py::test_name -v   # single test

# Django's own test runner also works against the same test modules
python manage.py test
```

There is no configured linter/formatter in this repo (no lint config files present).

## Environment

Config is loaded via `python-dotenv` from a `.env` file at the repo root (no `.env.example` currently checked in). Required variables, per `config/settings.py`:

- `SECRET_KEY` — Django secret key
- `DATABASE_URL` — parsed with `dj_database_url`; Docker Compose runs Postgres 16, but SQLite (`db.sqlite3`) is used for local/non-Docker dev
- `TMDB_API_KEY` — TMDB API access
- `GROQ_API_KEY` — Groq API access for the AI recommendation feature
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` — comma-separated
- `EMAIL_USER`, `EMAIL_PASS` — Gmail SMTP for password reset emails

Celery/Redis config (`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`) is hardcoded to `redis://localhost:6379/0` in settings, not env-driven.

## Architecture

Four Django apps:

- **`movies/`** — core domain: `Movies`, `Genre`, `Rating`, `Comment` models; category/search/detail views; all TMDB integration.
- **`users/`** — `Profile` (avatar, auto-resized to 300x300 on save) and `Watchlist` (user↔movie join with `watched` flag, unique per user/movie); registration, login/logout, password reset, watchlist CRUD views.
- **`api/`** — DRF layer wrapping the same models/services for JSON+JWT consumers. Mirrors the template views' functionality (movies, genres, ratings, profile, watchlist, AI recommendations, popular actors) but is a separate set of views/serializers/urls — changes to core behavior typically need to be made in both `movies`/`users` views and the corresponding `api` views.
- **`config/`** — settings, root URLconf, WSGI/ASGI, Celery app bootstrap (`config/celery.py`).

### TMDB integration (`movies/tmdb_service.py`)

`TMDBClient` wraps the TMDB REST API (`_request` does the raw HTTP call). Key methods:
- `get_list()` — paginated discover/list endpoints, dedupes results by id, normalizes items via `_type_items` (adds `poster_url`, unified `title`/`release_date`).
- `enrich_item(s)` — fetches full details for an item (genres, rating, country, language) to back detail pages.
- `get_popular_actors()` — filters TMDB "popular people" down to actors and paginates.

`movies/views.py`'s `AllMoviesView` is the shared base class for every category page (popular, top rated, now playing, upcoming, anime, doramas, cartoons, TV, movie-only); subclasses set `item_func`, `template_name`, `media_type`, etc. It cross-references the logged-in user's `Watchlist` to annotate each item with watched state.

Local `Movies` DB records are separate from live TMDB data — TMDB is the source of truth for browsing/search, while local `Movies` rows exist to attach `Rating`, `Comment`, and `Watchlist` entries (linked via `tmdb_id`).

### AI recommendations (`movies/services.py`)

`get_ai(user, message, media_type)` builds a prompt from the user's `Watchlist` (title + watched status) and calls Groq's `llama-3.3-70b-versatile` with a fixed system prompt that enforces a strict output format and restricts answers to movies/TV topics. Used by both the template view (`movies/views.py: ai_recomendations`) and the API (`api/views.py: RecommendationsAiView`).

### In-progress / untracked work

`config/celery.py`, `movies/tasks.py`, and `movies/redis_services.py` are new, not-yet-committed files introducing Celery task queueing and direct Redis caching for movie data — currently stubs/incomplete. Check their contents before assuming any caching or async task behavior is active.

## Testing conventions

Tests live under `movies/tests/` and `users/tests/` (one file per view/service/model, e.g. `test_movie_view.py`, `test_tmdb_service.py`). Pattern used throughout: `pytest.mark.django_db` for DB-touching tests, `pytest-mock`'s `mocker.patch` to stub `TMDBClient` (and its methods) rather than hitting the real TMDB API, `RequestFactory` for view-level tests.
