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
- `REDIS_URL` — Redis connection for both Celery (`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`) and the TMDB list cache (`movies/redis_services.py`); defaults to `redis://localhost:6379/0` if unset. Docker Compose overrides it to `redis://redis:6379/0` (its own `redis` service) in `web`'s `environment:` block.

## Architecture

Four Django apps:

- **`movies/`** — core domain: `Movies`, `Genre`, `Rating`, `Comment` models; category/search/detail views; all TMDB integration.
- **`users/`** — `Profile` (avatar, auto-resized to 300x300 on save) and `Watchlist` (user↔movie join with `watched` flag, unique per user/movie); registration, login/logout, password reset, watchlist CRUD views.
- **`api/`** — DRF layer wrapping the same models/services for JSON+JWT consumers. Mirrors the template views' functionality (movies, genres, ratings, profile, watchlist, AI recommendations, popular actors) but is a separate set of views/serializers/urls — changes to core behavior typically need to be made in both `movies`/`users` views and the corresponding `api` views.
- **`config/`** — settings, root URLconf, WSGI/ASGI, Celery app bootstrap (`config/celery.py`).

### TMDB integration (`movies/tmdb_service.py`)

`TMDBClient` wraps the TMDB REST API (`_request` does the raw HTTP call). Key methods:
- `get_list()` — paginated discover/list endpoints, dedupes results by id, normalizes items via `_type_items` (adds `poster_url`, unified `title`/`release_date`).
- `enrich_item(s)` — fetches full details for an item (genres, rating, country, language) to back detail pages; per-item Redis-cached (see Redis caching below).
- `get_credit()` — cast/crew for a detail page; also per-item Redis-cached.
- `get_popular_actors()` — filters TMDB "popular people" down to actors and paginates.

`movies/views.py`'s `AllMoviesView` is the shared base class for every category page (popular, top rated, now playing, upcoming, anime, doramas, cartoons, TV, movie-only); subclasses set `item_func`, `template_name`, `media_type`, etc. It cross-references the logged-in user's `Watchlist` to annotate each item with watched state.

Local `Movies` DB records are separate from live TMDB data — TMDB is the source of truth for browsing/search, while local `Movies` rows exist to attach `Rating`, `Comment`, and `Watchlist` entries (linked via `tmdb_id`).

### AI recommendations (`movies/services.py`)

`get_ai(user, message, media_type)` builds a prompt from the user's `Watchlist` (title + watched status) and calls Groq's `llama-3.3-70b-versatile` with a fixed system prompt that enforces a strict output format and restricts answers to movies/TV topics. Used by the API (`api/views.py: RecommendationsAiView`) directly, and by the template flow asynchronously via Celery (below).

**Template AI flow is now async (Celery)**: `movies/views.py: ai_recomendations` no longer calls `get_ai()` inline — it enqueues `movies/tasks.py: get_ai_recommendation_task` (`.delay(user_id, message, media_type)`) and immediately returns `{"task_id": ...}`. A new `ai_recommendation_status(request, task_id)` view polls `AsyncResult` and returns `{"status": "pending"}`, `{"status": "done", "result": {...}}`, or `{"status": "failed", "error": ...}`. The Alpine.js chat panel in `movies/templates/movies/base.html` polls `ai/status/<task_id>/` every 1.5s (up to ~45s) after posting a message. `docker-compose.yml` has a dedicated `worker` service (`celery -A config worker --loglevel=info`) alongside `web`; `config/__init__.py` now imports `celery_app` so Celery autodiscovers `movies/tasks.py`. The API's `RecommendationsAiView` is unchanged — still synchronous.

**Verified manually** (2026-09-05): full round trip via `docker compose up` — enqueue → `worker` picks up the task (confirmed in `docker compose logs worker`) → status endpoint returns `done` with the real result. Confirmed both the "no watchlist" error path and a real Groq call reach the worker.

**New issue found, not fixed**: the real Groq call now fails with `HTTP 404 Not Found` from `https://api.groq.com/openai/v1/chat/completions` (caught by `get_ai`'s broad `except Exception`, surfaced to the user as `{"error": "API is unavailable"}`) — most likely `llama-3.3-70b-versatile` has been renamed/decommissioned on Groq's side. Needs a model-name check/update in `movies/services.py`; not caused by and not related to the Celery migration.

### Redis caching (`movies/redis_services.py`, `movies/tmdb_service.py`)

Cache-aside logic lives in a shared private helper, `_cache_aside(cache_key, fetch_function, ttl)` (Redis GET → on miss call `fetch_function()` → Redis SET), used by two public functions with different key schemes:

- `cache_data_movie(endpoint, page, fetch_function, **kwargs)` — used by `TMDBClient.get_list()` (category/discover list endpoints). Key is `movies:list:v1:{endpoint}:{page}:{sorted filter kwargs}` — built from the already-normalized kwargs passed to `get_list`, not the raw querystring, so blank/omitted params and param order don't fragment the cache. `max_page` is excluded (it's a local pagination clamp, not a real TMDB filter). TTL 900s (15 min).
- `cache_item_detail(kind, media_type, tmdb_id, fetch_function)` — used by `TMDBClient.enrich_item()` (`kind="item"`) and `get_credit()` (`kind="credits"`) for per-item detail data (genres, rating, release date, cast/crew). Key is `movies:{kind}:v1:{media_type}:{tmdb_id}`. TTL 21600s (6h) — much longer than the list cache since item detail data is far more static than list rankings/pagination.

Shared behavior for both:
- Caching happens *below* `AllMoviesView`'s per-user `Watchlist` annotation, so no per-user state is ever cached.
- Fallback behavior: a Redis outage (`RedisError`) or a TMDB fetch failure (`TMDBFetchError`, raised by each `fetch()` closure) is never cached and never breaks page rendering — falls straight through to an uncached fetch.
- Debug instrumentation: `print()` timing logs in `_cache_aside` (cache GET hit/miss + duration) and in `get_list`/`AllMoviesView.get()` (per-step and total call duration) — intentionally left in for profiling; remove or convert to `logger.debug` before considering this done.

**enrich_item() bug fixed**: the pre-existing `enrich_item()` called `cache_data_movie(fetch, item, media_type)` — positionally mismatched against `cache_data_movie`'s real `(endpoint, page, fetch_function, **kwargs)` signature, binding `media_type` (a string) as `fetch_function`. This crashed with `TypeError: 'str' object is not callable` on any real cache miss (confirmed by direct reproduction in a container shell). Rewritten to build a small enrichment-fields dict via `cache_item_detail` and `item.update(...)` it in; also dropped a second latent bug where the `get_discover_movie/tv` fallback passed a positional arg into a `**kwargs`-only method.

**Verified manually**: cache hit/miss cycle for both list and item/credits caches, canonical key collapsing, TTLs (confirmed via `redis-cli TTL`), Redis-down fallback (stopped the `redis` container, page still rendered, just uncached/slower), TMDB-failure-not-cached fallback, and end-to-end via `docker compose up`/`restart` (confirmed `web` reaches the `redis` service, pagination goes through this same path). Real measured impact on `/movies/popular-movies/`: cold request ~3.7-4.9s (dominated by `enrich_items`, ~90% of total), repeat request with warm item cache **~100ms**. Existing suite (`pytest movies/tests users/tests`, excluding `test_tmdb_service.py`'s pre-existing unrelated `@pytest.fixturejson` typo): 33 passed, 4 pre-existing failures (`users/tests` profile/watchlist, `test_view_actor.py`) unrelated to caching.

**Not done yet**: `get_genres()` (`movies/tmdb_service.py`) is still uncached — one uncached TMDB call per category-page load (~150-200ms), smaller than the now-fixed `enrich_items` cost but still real. Not part of the per-item cache above since it's once-per-page, not once-per-item.

**Known issue, not fixed**: on every dev-server start/reload, the full `DATABASE_URL` — including the Postgres username/password — is printed to stdout (visible in `docker compose logs web`). Worth moving behind a debug-only guard or removing before this is any less throwaway than local dev.

## Testing conventions

Tests live under `movies/tests/` and `users/tests/` (one file per view/service/model, e.g. `test_movie_view.py`, `test_tmdb_service.py`). Pattern used throughout: `pytest.mark.django_db` for DB-touching tests, `pytest-mock`'s `mocker.patch` to stub `TMDBClient` (and its methods) rather than hitting the real TMDB API, `RequestFactory` for view-level tests.
