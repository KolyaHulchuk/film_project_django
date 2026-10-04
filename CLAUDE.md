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

# Lint/format (ruff; config in pyproject.toml — not pinned in requirements.txt, install manually if missing)
pip install ruff pre-commit
ruff check .              # lint
ruff check . --fix        # lint, auto-fixing what's safe to fix
ruff format .              # format (line-length 120, double quotes)
pre-commit install         # optional: wire ruff into a git pre-commit hook (.pre-commit-config.yaml)
```

Ruff (`pyproject.toml`) is configured with `E`, `W`, `F`, `I`, `UP`, `B`, `C4`, `DJ` rule sets, `E501` ignored (formatter handles most line-length, and long strings/URLs are left alone on purpose), migrations excluded from linting. `.pre-commit-config.yaml` runs `ruff check --fix` + `ruff format` (rev pinned to match the installed ruff version — bump both together).

**First full-repo run** (2026-09-05): `ruff check . --fix` + `ruff format .` fixed 226 auto-fixable issues (mostly `I001` unsorted imports, `F401` unused imports, `W291`/`W293` trailing whitespace) across 43 files; existing suite still 33 passed / 4 pre-existing failures (same ones noted below), `python manage.py check` clean. 12 issues remain, not auto-fixable — worth a manual pass:
- `movies/views.py` — `from .utils import *` (flagged `F403`/`F405` for `COUNTRY_CODES` and `normalize_countries`) — pre-existing star import, works fine but ruff can't verify the names; fix would be switching to explicit imports.
- `movies/models.py:17-18` — `DJ001`: `null=True` on `TextField`/`URLField` (Django convention is `blank=True` alone for optional string fields, since Django already treats `""` as "empty" for strings — `null=True` here just creates a second, redundant "no value" state). Pre-existing, would need a migration to change.
- `movies/tmdb_service.py:160` — `B904`: `raise ValueError("Uknown")` inside an `except` block should be `raise ValueError("Uknown") from err` (or `from None`) to preserve/suppress the original traceback correctly.
- A handful of pre-existing test-only issues: `E712` (`== True`/`== False` instead of truthy/falsy asserts) and `B017` (`pytest.raises(Exception)` too broad) in `users/tests/test_models_watchlist.py`, `users/tests/test_watchlist.py`, `movies/tests/test_search_view.py`, `movies/tests/test_models_moivies.py`; one unused variable (`F841`) in `movies/tests/test_get_or_create_media.py`.

## Environment

Config is loaded via `python-dotenv` from a `.env` file at the repo root (no `.env.example` currently checked in). Required variables, per `config/settings.py`:

- `SECRET_KEY` — Django secret key
- `DATABASE_URL` — parsed with `dj_database_url`; **must** be set (`dj_database_url.parse(None)` raises, so there's no automatic sqlite fallback despite `db.sqlite3` existing in the repo — that file is currently just a leftover, wired to nothing). The value in `.env` points at Render's production Neon Postgres and is what Render itself uses, and what any command run directly on the host outside Docker (`venv/bin/python manage.py ...`) hits too. **Docker Compose does not use this value** — see "Local Postgres" below.
- `TMDB_API_KEY` — TMDB API access
- `GROQ_API_KEY` — Groq API access for the AI recommendation feature
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` — comma-separated
- `EMAIL_USER`, `EMAIL_PASS` — Gmail SMTP for password reset emails
- `REDIS_URL` — Redis connection for both Celery (`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`) and the TMDB list cache (`movies/redis_services.py`); defaults to `redis://localhost:6379/0` if unset. Docker Compose overrides it to `redis://redis:6379/0` (its own `redis` service) in `web`'s `environment:` block.
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — Google OAuth client, read by `SOCIALACCOUNT_PROVIDERS["google"]` for django-allauth social login (see Authentication below)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — local-only, **not** used by Render; these seed/authenticate Docker Compose's own `db` (Postgres 16) service (see "Local Postgres, isolated from prod" below)

### Local Postgres, isolated from prod (2026-09-30)

Docker Compose's `web`/`worker` services build their own `DATABASE_URL` (`postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}`, pointed at the compose file's `db` service) instead of reading `DATABASE_URL` from `.env`. Previously they didn't — `web`/`worker`'s `environment:` block explicitly set `DATABASE_URL=${DATABASE_URL}`, which resolved to the same Neon URL as `.env`'s top-level value, meaning **local `docker compose up` and the deployed Render site were reading/writing the same production database** (a stray local `migrate`, test run, or manual shell poke could touch real user data). The `db` service in `docker-compose.yml` had existed the whole time but was never actually wired up.

`db`'s own Postgres cluster/volume (`pgdata`) already contained a fully-migrated `film_db` database with real local data from an earlier point when this *was* wired up correctly — nothing was lost in the fix, just reconnected. Local Postgres has its own superuser (`KolyaHV`, promoted via `is_staff`/`is_superuser`) separate from both Neon (0 superusers) and the unrelated, unused `db.sqlite3` file (its own separate superuser, also `KolyaHV`, different password).

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

### Authentication (`users/`, `config/settings.py`, django-allauth)

The site's own username/password login/register/password-reset views (`users/views.py`, `users/forms.py`, `users/templates/users/{login,register}.html`) are unchanged and remain the primary flow — plain `django.contrib.auth`, no custom `AUTH_USER_MODEL`.

**Google login added (2026-09-30)** via `django-allauth` (already pinned in `requirements.txt` before this; the `[socialaccount]` extra plus explicit `cryptography`/`PyJWT`/`oauthlib` pins were added since base `django-allauth` doesn't declare them and Google's id_token verification needs them at runtime, not install time):
- `INSTALLED_APPS` gained `django.contrib.sites` + the four `allauth`/`allauth.socialaccount.providers.google` apps; `SITE_ID = 1`; `MIDDLEWARE` gained `allauth.account.middleware.AccountMiddleware`; `AUTHENTICATION_BACKENDS` now lists `ModelBackend` alongside allauth's own backend.
- `SOCIALACCOUNT_PROVIDERS["google"]["APP"]` reads `client_id`/`secret` from `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (env only — no `SocialApp` DB row; allauth errors if both exist). `SOCIALACCOUNT_LOGIN_ON_GET = True` skips allauth's intermediate confirmation page.
- `config/urls.py` mounts `path("accounts/", include("allauth.urls"))` — this adds allauth's *own* parallel login/signup/logout pages (`/accounts/login/`, `/accounts/signup/`, etc.) alongside the site's `/users/...` ones; a signed-in-via-Google user with no matching local account lands on `/accounts/3rdparty/signup/` to pick a username.
- Under `if not DEBUG`: `SECURE_PROXY_SSL_HEADER`/`ACCOUNT_DEFAULT_HTTP_PROTOCOL` set to `https`, since Render terminates TLS at its proxy and forwards plain HTTP — without this allauth builds an `http://` OAuth callback and Google rejects it. The redirect URI itself is derived from the incoming request (host + this proxy header), never from the `Site` row.
- "Sign in/up with Google" button added to `users/templates/users/{login,register}.html`, styled to match their existing dark theme (`.btn-google` in `users/static/users/{login,register}.css`).
- `users/templates/allauth/` overrides allauth's own bare-bones pages (no CSS at all by default) via its "elements" system (`allauth/elements/*.html`: `h1`, `p`, `form`, `fields`, `field`, `button`, `provider`, ...) plus `allauth/layouts/base.html`, so `/accounts/login/`, `/accounts/signup/`, `/accounts/3rdparty/signup/`, `/accounts/logout/`, password/email management all get the same `.login-page`/`.login-card` look — styled via the new `users/static/users/allauth_theme.css`. This layout deliberately does **not** extend `movies/base.html`: both templates declare a block named `content`, and allauth's own leaf pages hardcode overriding that same block name, so nesting them collides — see the comment at the top of `allauth/layouts/base.html`.
- `users/migrations/0003_set_default_site.py` seeds the `Site` row (id=1) — originally hardcoded to the production domain, because at the time local dev and prod shared one Neon database (see "Local Postgres, isolated from prod" above) and there was only one row to get right. `0004_site_domain_per_environment.py` (added once local dev got its own database) splits this back to per-`DEBUG`: `localhost:8001` locally, the Render domain in prod. `0003`'s hardcoded value stays correct on Neon since Django never re-runs an already-applied migration there.

### Comments (`movies/comments.py`, 2026-09-30)

Comment block under "Cast" on the movie detail page. A user can leave any number of comments per movie; comments can't be edited, only deleted by their author. Likes/dislikes via `CommentVote` (`value` ±1, unique per comment/user; voting on your own comment is refused). `movies/comments.py` holds the shared query (`annotate_comments`: `likes`/`dislikes`/`user_vote` in one query) and `toggle_vote()` rules, used by both:
- template side — HTMX fragment views `comment_*` in `movies/views.py` + `movies/templates/movies/partials/comments/`. Errors come back with `HX-Retarget: #cm-flash`; 422 = form re-rendered with errors (see the `htmx:beforeSwap` handler in `section.html`). "Show more" paginates by offset (count of comments already on screen), not page number.
- API — `api/movie/<movie_id>/comments/`, `api/comments/<pk>/`, `api/comments/<pk>/vote/`.
Rate limits: `CommentCreateThrottle` (10/hour) and `CommentVoteThrottle` (60/min) in `movies/throttling.py`. UI copy is English, like the rest of the site. Tests: `movies/tests/test_comments.py` (switches the cache to locmem, so no Redis needed).

### AI recommendations (`movies/services.py`)

`get_ai(user, message, media_type)` builds a prompt from the user's `Watchlist` (title + watched status) and calls Groq's `openai/gpt-oss-120b` with a fixed system prompt that enforces a strict output format and restricts answers to movies/TV topics. Used by the API (`api/views.py: RecommendationsAiView`) directly, and by the template flow asynchronously via Celery (below).

**Template AI flow is now async (Celery)**: `movies/views.py: ai_recomendations` no longer calls `get_ai()` inline — it enqueues `movies/tasks.py: get_ai_recommendation_task` (`.delay(user_id, message, media_type)`) and immediately returns `{"task_id": ...}`. A new `ai_recommendation_status(request, task_id)` view polls `AsyncResult` and returns `{"status": "pending"}`, `{"status": "done", "result": {...}}`, or `{"status": "failed", "error": ...}`. The Alpine.js chat panel in `movies/templates/movies/base.html` polls `ai/status/<task_id>/` every 1.5s (up to ~45s) after posting a message. `docker-compose.yml` has a dedicated `worker` service (`celery -A config worker --loglevel=info`) alongside `web`; `config/__init__.py` now imports `celery_app` so Celery autodiscovers `movies/tasks.py`. The API's `RecommendationsAiView` is unchanged — still synchronous.

**Verified manually** (2026-09-05): full round trip via `docker compose up` — enqueue → `worker` picks up the task (confirmed in `docker compose logs worker`) → status endpoint returns `done` with the real result. Confirmed both the "no watchlist" error path and a real Groq call reach the worker.

**Model fixed** (2026-09-05): `llama-3.3-70b-versatile` no longer appears in Groq's `/models` list and 404s — Groq dropped the Llama 3.x chat line entirely. Checked the account's current `/models` and `console.groq.com/docs/rate-limits`: every model available to this key (`openai/gpt-oss-120b`/`20b`, `qwen/qwen3.6-27b`/`3.8-27b`, `groq/compound`/`compound-mini`, plus the whisper/prompt-guard/orpheus models) is on the **free tier** (rate-limited, $0 cost) — there's no paid tier mixed in to avoid. Switched to `openai/gpt-oss-120b` (closest general-purpose size/quality match, same 30 RPM/1K RPD free-tier limit) and confirmed with a real `chat.completions.create` call.

### Redis caching (`movies/redis_services.py`, `movies/tmdb_service.py`)

Cache-aside logic lives in a shared private helper, `_cache_aside(cache_key, fetch_function, ttl)` (Redis GET → on miss call `fetch_function()` → Redis SET), used by three public functions with different key schemes:

- `cache_data_movie(endpoint, page, fetch_function, **kwargs)` — used by `TMDBClient.get_list()` (category/discover list endpoints). Key is `movies:list:v1:{endpoint}:{page}:{sorted filter kwargs}` — built from the already-normalized kwargs passed to `get_list`, not the raw querystring, so blank/omitted params and param order don't fragment the cache. `max_page` is excluded (it's a local pagination clamp, not a real TMDB filter). TTL 900s (15 min).
- `cache_item_detail(kind, media_type, tmdb_id, fetch_function)` — used by `TMDBClient.enrich_item()` (`kind="item"`) and `get_credit()` (`kind="credits"`) for per-item detail data (genres, rating, release date, cast/crew). Key is `movies:{kind}:v1:{media_type}:{tmdb_id}`. TTL 21600s (6h) — much longer than the list cache since item detail data is far more static than list rankings/pagination.
- `cache_genres(media_type, fetch_function)` — used by `TMDBClient.get_genres()` (once-per-page-load, not once-per-item, so it isn't part of `cache_item_detail` above). Key is `movies:genres:v1:{media_type}`. TTL 86400s (24h) — longer than either of the above since TMDB's genre list is effectively static.

Shared behavior for all three:
- Caching happens *below* `AllMoviesView`'s per-user `Watchlist` annotation, so no per-user state is ever cached.
- Fallback behavior: a Redis outage (`RedisError`) or a TMDB fetch failure (`TMDBFetchError`, raised by each `fetch()` closure) is never cached and never breaks page rendering — falls straight through to an uncached fetch.
- Debug instrumentation: `print()` timing logs in `_cache_aside` (cache GET hit/miss + duration) and in `get_list`/`AllMoviesView.get()` (per-step and total call duration) — intentionally left in for profiling; remove or convert to `logger.debug` before considering this done.

**enrich_item() bug fixed**: the pre-existing `enrich_item()` called `cache_data_movie(fetch, item, media_type)` — positionally mismatched against `cache_data_movie`'s real `(endpoint, page, fetch_function, **kwargs)` signature, binding `media_type` (a string) as `fetch_function`. This crashed with `TypeError: 'str' object is not callable` on any real cache miss (confirmed by direct reproduction in a container shell). Rewritten to build a small enrichment-fields dict via `cache_item_detail` and `item.update(...)` it in; also dropped a second latent bug where the `get_discover_movie/tv` fallback passed a positional arg into a `**kwargs`-only method.

**Verified manually**: cache hit/miss cycle for both list and item/credits caches, canonical key collapsing, TTLs (confirmed via `redis-cli TTL`), Redis-down fallback (stopped the `redis` container, page still rendered, just uncached/slower), TMDB-failure-not-cached fallback, and end-to-end via `docker compose up`/`restart` (confirmed `web` reaches the `redis` service, pagination goes through this same path). Real measured impact on `/movies/popular-movies/`: cold request ~3.7-4.9s (dominated by `enrich_items`, ~90% of total), repeat request with warm item cache **~100ms**. Existing suite (`pytest movies/tests users/tests`, excluding `test_tmdb_service.py`'s pre-existing unrelated `@pytest.fixturejson` typo): as of 2026-09-09, all 37 tests pass — the 4 previously-failing tests (`users/tests` profile/watchlist, `test_view_actor.py`) were fixed, including a real bug found along the way: `users/apps.py`'s `ready()` never imported `users/signals.py`, so the `post_save` signal that creates a `Profile` for new `User`s never registered — every newly registered user had no `Profile` and hit a 500 on `/users/profile/`.

**Fixed (2026-09-09)**: `config/settings.py` used to unconditionally `print()` the full `DATABASE_URL` — including the Postgres username/password — to stdout on every dev-server start/reload (visible in `docker compose logs web`). That print has been removed. Separately, `DEBUG` was hardcoded `True` regardless of environment (so Render's `DEBUG=False` env var had no effect); it's now read via `DEBUG = os.getenv("DEBUG", "False") == "True"`.

## Testing conventions

Tests live under `movies/tests/` and `users/tests/` (one file per view/service/model, e.g. `test_movie_view.py`, `test_tmdb_service.py`). Pattern used throughout: `pytest.mark.django_db` for DB-touching tests, `pytest-mock`'s `mocker.patch` to stub `TMDBClient` (and its methods) rather than hitting the real TMDB API, `RequestFactory` for view-level tests.
