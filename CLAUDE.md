# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Django movie/TV discovery app ("Movies.hub") backed by the TMDB API. Server-rendered frontend (Django templates + plain CSS/JS, with HTMX 1.9.4 and Alpine.js 3.12.0 loaded from unpkg in `movies/base.html`; no Bootstrap, no build step) plus a parallel DRF REST API with JWT auth. Features: Home page rows from TMDB (trending Today/This Week, hero trailers, Movie of the Week, Pick by Mood, Topic of the Day, TV showcase), category/discover catalogs with filters and sorting, search with live header suggestions, a Detail page (cast, trailer/stills, seasons, collection, recommendations), personal watchlists with watched/unwatched state, ratings, comments with likes/dislikes, popular actors, email + Google login with email verification, and a Groq-powered AI recommendation assistant.

`crispy_forms`/`crispy_bootstrap4` are still in `INSTALLED_APPS` and `requirements.txt`, but no template uses them anymore.

## Current state (2026-11-14)

- **Branches:** `main` (= `origin/main`) is ~31 commits behind `redesign`. `redesign` (local only, no upstream) holds the whole Movies.hub port, the TMDB wiring and the finished no-behavior-change backend refactor: `refactor/backend-cleanup` was branched from `redesign` @ `8d34cca`, refactored `movies/tmdb_service.py`, `movies/redis_services.py`, `movies/views.py` and `users/views.py` (each with its characterization tests committed before the refactor), and was fast-forwarded back into `redesign` on 2026-11-14.
- **Tests:** 497 tests, all passing. They don't touch the dev Redis (see "Testing conventions").
- **Lint:** `ruff check .` is clean (ruff 0.16.6 — same rev as `.pre-commit-config.yaml`).
- **Production runs `runserver`**, not gunicorn: see "Deploy (Render)".
- **Private local docs, not in git:** `REFACTOR_PLAN.md` (excluded via `.git/info/exclude` and `.dockerignore`) — rules and decisions of the backend refactor, plus its section 6: bugs found during it that were left alone because fixing them changes behavior; `FUTURE_NOTES.md` (in `.gitignore`) — e.g. the hidden profile Stats tab; `qa-report/REPORT.md` — the 2026-11-07 health check (1 critical / 9 major / 26 minor), its `screenshots/auth__*` contain personal data, never publish them. `REQUESTS_SESSION_NOTES.md` and `.claude/` are untracked too.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # note: pytest/pytest-django/pytest-mock are used by tests but NOT pinned here — install manually if missing
python manage.py migrate
python manage.py runserver

# Tests (pytest.ini sets DJANGO_SETTINGS_MODULE=config.settings)
# ALWAYS run tests inside the `web` container (local Postgres), NEVER bare `pytest` on the host:
# the host reads DATABASE_URL from .env = production Neon, and pytest would CREATE DATABASE test_neondb there.
docker compose exec web pytest                                  # full suite
docker compose exec web pytest movies/tests/test_movie_view.py  # single file
docker compose exec web pytest movies/tests/test_movie_view.py::test_name -v   # single test

# Django's own test runner also works against the same test modules (same rule: only inside the container)
docker compose exec web python manage.py test

# Lint/format (ruff; config in pyproject.toml — not pinned in requirements.txt, install manually if missing)
pip install ruff pre-commit
ruff check .              # lint
ruff check . --fix        # lint, auto-fixing what's safe to fix
ruff format .              # format (line-length 120, double quotes)
pre-commit install         # optional: wire ruff into a git pre-commit hook (.pre-commit-config.yaml)
```

Ruff (`pyproject.toml`) is configured with `E`, `W`, `F`, `I`, `UP`, `B`, `C4`, `DJ` rule sets, `E501` ignored (formatter handles most line-length, and long strings/URLs are left alone on purpose), migrations excluded from linting. `.pre-commit-config.yaml` runs `ruff check --fix` + `ruff format` (rev pinned to match the installed ruff version — bump both together).

Other useful checks: `docker compose exec web python manage.py check`, `... makemigrations --check --dry-run`, `... check --deploy` (with `DEBUG=False`). Lint can run on the host (`venv/bin/ruff check .`, `venv/bin/ruff format --check .`) — ruff doesn't touch the DB. The dev server is at `http://localhost:8001`.

`REFACTOR_PLAN.md` additionally runs the suite against a disposable `redis:7-alpine` container on the compose network (`docker run -d --rm --name refactor-redis-tests --network film_project_django_default redis:7-alpine`, then `docker compose exec -T -e REDIS_URL=redis://refactor-redis-tests:6379/0 web pytest -q`). That's an extra safety net only — the test fixtures already isolate the cache.

## Environment

Config is loaded via `python-dotenv` from a `.env` file at the repo root. `.env.example` is checked in as a template — but its comment saying an unset `DATABASE_URL` falls back to `db.sqlite3` is wrong, and it lacks `DEBUG`/`POSTGRES_*`. Variables, per `config/settings.py`:

- `SECRET_KEY` — Django secret key
- `DEBUG` — `"True"` enables debug; anything else / unset = `False`
- `DATABASE_URL` — parsed with `dj_database_url`; **must** be set (`dj_database_url.parse(None)` raises, so there's no automatic sqlite fallback despite `db.sqlite3` existing in the repo — that file is currently just a leftover, wired to nothing). The value in `.env` points at Render's production Neon Postgres and is what Render itself uses, and what any command run directly on the host outside Docker (`venv/bin/python manage.py ...`) hits too. **Docker Compose does not use this value** — see "Local Postgres" below.
- `TMDB_API_KEY` — TMDB API access
- `GROQ_API_KEY` — Groq API access for the AI recommendation feature
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` — comma-separated
- `EMAIL_USER`, `EMAIL_PASS` — Gmail SMTP for password reset / verification emails
- `DEFAULT_FROM_EMAIL` — optional; default `Movies.hub <EMAIL_USER>` (Gmail rewrites the address anyway, only the display name is ours). Also used as `SERVER_EMAIL`.
- `REDIS_URL` — one Redis for Celery (`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`), Django's `CACHES["default"]` (sessions, DRF throttles, allauth rate limits, `cache_tmdb`) and the raw TMDB cache client in `movies/redis_services.py`; defaults to `redis://localhost:6379/0` if unset. A `rediss://` URL turns on TLS options for Celery (hosted Redis). Docker Compose overrides it to `redis://redis:6379/0` (its own `redis` service) in `web`'s `environment:` block.
- `LOG_LEVEL` — level of the project's own loggers (`movies`, `users`, `api`); default `INFO`, `DEBUG` adds catalog timings and Redis cache hits/misses. See "Logging".
- `ADMINS` — optional comma-separated emails that get a mail for every unhandled 500 while `DEBUG=False` (sent through the Gmail SMTP above).
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — Google OAuth client, read by `SOCIALACCOUNT_PROVIDERS["google"]` for django-allauth social login (see Authentication below)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — local-only, **not** used by Render; these seed/authenticate Docker Compose's own `db` (Postgres 16) service (see "Local Postgres, isolated from prod" below)

### Local Postgres, isolated from prod (2026-09-30)

Docker Compose's `web`/`worker` services build their own `DATABASE_URL` (`postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}`, pointed at the compose file's `db` service) instead of reading `DATABASE_URL` from `.env`. Previously they didn't — `web`/`worker`'s `environment:` block explicitly set `DATABASE_URL=${DATABASE_URL}`, which resolved to the same Neon URL as `.env`'s top-level value, meaning **local `docker compose up` and the deployed Render site were reading/writing the same production database** (a stray local `migrate`, test run, or manual shell poke could touch real user data). The `db` service in `docker-compose.yml` had existed the whole time but was never actually wired up.

`db`'s own Postgres cluster/volume (`pgdata`) already contained a fully-migrated `film_db` database with real local data from an earlier point when this *was* wired up correctly — nothing was lost in the fix, just reconnected. Local Postgres has its own superuser (`KolyaHV`, promoted via `is_staff`/`is_superuser`) separate from both Neon (0 superusers) and the unrelated, unused `db.sqlite3` file (its own separate superuser, also `KolyaHV`, different password).

## Architecture

Four Django apps:

- **`movies/`** — core domain: `Movies`, `Genre`, `Rating`, `Comment`, `CommentVote` models; home/category/search/detail views; all TMDB integration.
- **`users/`** — `Profile` (avatar, auto-resized to 300x300 on save) and `Watchlist` (user↔movie join with `watched` flag, unique per user/movie); registration, login/logout, password reset, email verification, watchlist CRUD views.
- **`api/`** — DRF layer wrapping the same models/services for JSON+JWT consumers. Mirrors the template views' functionality (movies, genres, ratings, profile, watchlist, AI recommendations, popular actors, comments) but is a separate set of views/serializers/urls — changes to core behavior typically need to be made in both `movies`/`users` views and the corresponding `api` views.
- **`config/`** — settings, root URLconf, WSGI/ASGI, Celery app bootstrap (`config/celery.py`).

Note: `users/apps.py`'s `ready()` must import `users/signals.py` — that's what registers the `post_save` signal creating a `Profile` for every new `User` (without it, new users hit a 500 on `/users/profile/`; fixed 2026-09-09).

### TMDB integration (`movies/tmdb_service.py`)

`TMDBClient` wraps the TMDB REST API. Key methods:
- `_request()` — the raw HTTP call; returns `{}` on any failure (non-200, timeout, bad JSON), never raises; `TIMEOUT = (3.05, 10)`. Callers use `_require(data, key, fallback)` to turn a missing key into `TMDBFetchError`, which is what keeps failures out of the cache.
- `get_list(endpoint, page, ttl=None, **filters)` — any paginated list (category, discover, trending, keyword); dedupes results by id, normalizes items via `_type_items` (adds `poster_url`, unified `title`/`release_date`). `max_page` (default `DEFAULT_LIST_MAX_PAGE = 10`) caps `total_pages` and is kept out of the cache key, but is still sent to TMDB (known, left as is).
- `get_trending(media_type, time_window)`, `get_keyword(id)` / `get_keyword_movies(id)`, `get_list_with_trailers()` / `attach_trailers()` (Home hero + Coming Soon), `get_genres(media_type)`.
- `get_details(tmdb_id, media_type)` — the whole detail page in **one** request (`DETAIL_APPEND`: videos, credits, images, keywords, recommendations, release_dates/content_ratings), trimmed by `_shape_details()` before caching. Also used for Movie of the Week and trailers.
- `get_season(tv_id, n)`, `get_collection(id)` — detail page Seasons tab / collection block.
- `search_movies(query)` (search page, `search/multi`, movies + TV only) and `suggest(query)` (header dropdown; raises on TMDB failure so the UI can show an error → `search_suggest` view returns 502).
- `annotate_items(items, media_type, genres)` — category-page card fields derived from the list response itself, zero TMDB calls.
- `get_popular_actors()` — filters TMDB "popular people" down to actors and paginates.
- `enrich_item(s)` — per-item detail fetch (genres, rating, country, language). **Has no callers**, kept on purpose (commit `a130ea0`) for a future caller that needs `country`; don't delete it.
- `fetch_parallel(tasks)` (module-level) — runs a dict of callables in a thread pool; `HomeView` uses it for ~25 parallel requests in two rounds.

Tests: `movies/tests/test_tmdb_details.py` and `test_tmdb_service.py` characterize this module.

### Views (`movies/views.py`)

`AllMoviesView` is the shared base class for every category page (popular, top rated, now playing, upcoming, anime, doramas, cartoons, TV, movie-only); `AllMoviesView.get` calls `self.item_func(page)` and cross-references the logged-in user's `Watchlist` to annotate each item with watched state. Two declarative bases fill in `item_func`:
- `ListCatalogView` — one fixed TMDB list, subclasses set `list_endpoint` (+ `media_type`, `template_name`, ...): `PopularMoviesView`, `TVPopularView`, `TopRatedView`, `NowPlayingsView`, `UpcomingView`.
- `DiscoverCatalogView` — `discover/*`, subclasses set `discover_endpoint` and `base_filters`; `sortable = True`: `TVViews`, `AnimeTVView`, `DoramTVView`, `CartoonTVView`, `MovieView`. It builds TMDB filters from the query string in `search_filter_movie()` (years / rating / genre / country / `sort` from `CATALOG_SORTS`; `vote_count.gte = MIN_VOTES` for rating/title sorts or a rating filter; "newest" gets an upper date bound of today) and merges them as `{**base_filters, **extra_filters}`. The base filters are module constants (`TV_DISCOVER_FILTERS`, `ANIME_TV_FILTERS`, `DORAMA_TV_FILTERS`, `CARTOON_TV_FILTERS`, `MOVIE_DISCOVER_FILTERS`); the dorama/anime/cartoon ones are also used by the home TV showcase, so never mutate them.

`?page` is parsed by `_parse_page()` (invalid → 1) in both `AllMoviesView` and `PopularActorView`. `HX-Request` renders only `movies/partials/movie_list.html`. `AllMoviesView.get` logs its step timings with `logger.debug("[timing] ...")` (visible with `LOG_LEVEL=DEBUG`); there are no `print()` calls left in the views.

Public names with typos are interface — **don't rename them**: `SerachView`, `ai_recomendations` (URL name `ai-recomendations` is used by the frontend), `parials_name`, `GerneSerializer`, URL names `api-movie-datail`, `token_obtian`. Tests patch `movies.views.TMDBClient` and `users.views.get_or_create_media`, so `get_or_create_media` must stay in `movies/views.py` and keep resolving `TMDBClient` from its globals.

**Home** (`HomeView`): one `fetch_parallel` round for all list rows (`trending/*`, `movie/*`, `tv/popular`, mood rows `discover/movie?with_genres=…` from `MOODS`, TV showcase rows from `TV_SHOWCASE`, Topic of the Day = a keyword from `TOPIC_KEYWORDS` picked by date), then a second round for Coming Soon trailers + Movie of the Week (`#1` of `trending/movie/week`, via `get_details`). `get` is split into `_first_round_tasks`, `_second_round_tasks`, `_moods`, `_topic` and `_tv_showcase`; the round-2 tasks stay lambdas on purpose (they read the round-1 result inside the worker thread), and the key order of the task dicts is pinned by tests.

**Detail** (`MoviesDetailView`, `movie/<pk>/<media_type>/`): `get_details()` + a local `Movies` row (created by `get_or_create_media(pk, media_type, details)` without an extra TMDB call), `cast[:12]`, TV → `_seasons_context` (`?season=N`, default = latest season that has started airing, season 0 / empty seasons skipped), movie → `_collection_context`. Comments, rating count and the watchlist toggle state are rendered server-side.

### Watchlist views (`users/views.py`)

- `AddToWatchlist` (POST) calls `get_or_create_media`, then answers via `_json_response` (fetch() from `watchlist_toggle.js`, detected by `wants_json()` = `X-Requested-With: XMLHttpRequest`) or `_form_response` (flash message + redirect to POST `next`, else home).
- `DeleteWatchlist` handles only HTTP `DELETE` (JSON for fetch(), empty 200 for HTMX, else redirect); `toggle_watched` flips `watched` on POST.
- `search_watchlist` (HTMX filter) uses `_param()` and `_rating_bounds()` (`rating_search=7` → `[7, 8)`).
- `WatchlistView` shows 20 per page, newest first; the filter options come from `WATCHLIST_YEARS`, `WATCHLIST_GENRES` (both hardcoded) and `_split_countries()` over a separate `DISTINCT` query.
- Several known bugs here are pinned as is in `users/tests/test_watchlist_characterization.py` (`# Known bug, pinned as is:`): fixing one means changing its test in the same commit.

**Search** (`SerachView`): TMDB `search_multi` results are cached per normalized query for 7 days (`cache_search_results`), merged with local `Movies` title matches; `search_suggest` (`search/suggest/?q=`) is the JSON for the header dropdown (min 2 chars, max 100, up to 6 results).

Local `Movies` DB records are separate from live TMDB data — TMDB is the source of truth for browsing/search, while local `Movies` rows exist to attach `Rating`, `Comment`, and `Watchlist` entries (linked via `tmdb_id`).

### Authentication (`users/`, `config/settings.py`, django-allauth)

The site's own login/register/password-reset views (`users/views.py`, `users/forms.py`, `users/urls.py`, `users/templates/users/{login,register}.html`) are the primary flow — plain `django.contrib.auth`, no custom `AUTH_USER_MODEL`.

**Email + password login, email verification (2026-10-09)** — all tested in `users/tests/test_auth_flows.py` and `test_google_login.py` (`users/tests/conftest.py` swaps the cache to locmem and clears it per test, since sessions *and* allauth's verification-email rate limits live in the cache):
- **Login** is by email + password: `EmailLoginForm` (`users/forms.py`) → `users/backends.py: EmailBackend` (`email__iexact` after `normalize_email`; one generic "Invalid email or password." error). `AUTHENTICATION_BACKENDS` = `EmailBackend`, then `ModelBackend` (so `/admin/` and `client.login(username=...)` in tests still use the username), then allauth's backend. allauth's own pages match: `ACCOUNT_LOGIN_METHODS = {"email"}`, email required in `ACCOUNT_SIGNUP_FIELDS`. The JWT API (`/api/token/`) is still username-based.
- **One account per email**: `ACCOUNT_UNIQUE_EMAIL = True`, normalization/checks in `users/adapters.py` and the forms, plus a case-insensitive unique index (`users/migrations/0005_unique_user_email.py`, see Deploy). Tests: `users/tests/test_unique_email.py`.
- **Verification** reuses allauth's `EmailAddress` table and `/accounts/confirm-email/<key>/` links; helpers live in `users/emails.py` (`send_verification`, `is_email_verified`, `mark_email_verified`, `replace_email_address`). `User.email` is the source of truth; the `EmailAddress` row only tracks verification. `ACCOUNT_EMAIL_VERIFICATION = "optional"`: login works before verification (and logging in never verifies). Registration sends the link; changing the email on the profile drops the old rows and re-verifies; the profile shows the status + "Resend verification email" (`resend_verification`) + "Connect Google" (`process=connect`). Completing a password reset marks the email verified (`SitePasswordResetConfirmView`) — following the emailed link proves ownership. Users created before this have no `EmailAddress` row → shown as not verified.
- **Password reset** uses `SitePasswordResetForm`, which (unlike Django's default) also emails users *without* a usable password (Google-only accounts) — with a different text (`users/password_set_email.txt`) offering to set a password. Unknown emails get the same response and no mail. Sender: `DEFAULT_FROM_EMAIL` (see Environment).

**Google login (2026-09-30)** via `django-allauth` (the `[socialaccount]` extra plus explicit `cryptography`/`PyJWT`/`oauthlib` pins in `requirements.txt`, since base `django-allauth` doesn't declare them and Google's id_token verification needs them at runtime, not install time):
- `INSTALLED_APPS` has `django.contrib.sites` + the four `allauth`/`allauth.socialaccount.providers.google` apps; `SITE_ID = 1`; `MIDDLEWARE` has `allauth.account.middleware.AccountMiddleware`.
- `SOCIALACCOUNT_PROVIDERS["google"]["APP"]` reads `client_id`/`secret` from `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (env only — no `SocialApp` DB row; allauth errors if both exist). `SOCIALACCOUNT_LOGIN_ON_GET = True` skips allauth's intermediate confirmation page.
- `config/urls.py` mounts `path("accounts/", include("allauth.urls"))` — this adds allauth's *own* parallel login/signup/logout pages (`/accounts/login/`, `/accounts/signup/`, etc.) alongside the site's `/users/...` ones; a signed-in-via-Google user with no matching local account lands on `/accounts/3rdparty/signup/` to pick a username.
- Under `if not DEBUG`: `SECURE_PROXY_SSL_HEADER`/`ACCOUNT_DEFAULT_HTTP_PROTOCOL` set to `https`, since Render terminates TLS at its proxy and forwards plain HTTP — without this allauth builds an `http://` OAuth callback and Google rejects it. The redirect URI itself is derived from the incoming request (host + this proxy header), never from the `Site` row.
- **Linking Google to an existing account (`users/adapters.py`, fixed 2026-10-05)**: `SocialAccountAdapter.pre_social_login` reads the email from Google's raw payload, normalizes it (`normalize_email`), refuses missing/invalid or `email_verified=false` emails (error + redirect to login, no account created), and `connect()`s to the existing local user with the same email **only if that user's email is verified** — the password is kept, so both login methods work. If the local email is *not* verified (pre-hijacking guard: whoever registered it may not own the address), nothing is linked or created: a verification link is sent to the local address and the user is told to either confirm it and retry Google, or log in with the password and connect Google from the profile (the `process == "connect"` path skips these checks). New emails sign up a Google-only user (no usable password; identity is `SocialAccount.uid` = Google `sub`, so repeat logins don't depend on the email). **Never put a uniqueness check in `AccountAdapter.clean_email`**: allauth also calls it to *validate* provider emails and silently drops the email on `ValidationError` — that's what caused Google logins with an existing email to create an email-less `user` account. Tests: `users/tests/test_google_login.py` (mocked Google payload through allauth's real flow).
- Styling: the site's auth pages (`users/auth_card_base.html`) and allauth's pages (`users/templates/allauth/layouts/base.html` + the "elements" overrides in `allauth/elements/*.html`: `h1`, `p`, `form`, `fields`, `field`, `button`, `provider`, ...) all use `movies/static/movies/auth.css` with `body.mh-body.auth-page`. The allauth layout deliberately does **not** extend `movies/base.html`: both templates declare a block named `content`, and allauth's own leaf pages hardcode overriding that same block name, so nesting them collides — it pulls in the shared chrome (icons, header, footer, `main.css`, `chrome.js`) directly instead; see the comment at its top.
- `Site` row (id=1): `users/migrations/0003_set_default_site.py` seeded it with the production domain (back when local dev and prod shared one Neon database); `0004_site_domain_per_environment.py` splits it per-`DEBUG` (`localhost:8001` locally, the Render domain in prod); `0006_site_name_movies_hub.py` names it "Movies.hub" (used in email subjects/bodies).

### Logging and the security log (2026-11-17)

`LOGGING` in `config/settings.py`: one `console` handler on the root logger writing to stdout (Render keeps it in the service logs); the named loggers have no handlers of their own and propagate to it, which is also what lets pytest's `caplog` see them. `django.request` additionally has `mail_admins` (ERROR = unhandled 500s, only when `DEBUG=False` and `ADMINS` is set). Django's default "mail every ERROR from `django`" (incl. bots' `DisallowedHost`) is deliberately replaced.

`users/security_log.py` writes one line per security event to the `security` logger (always INFO): `<event> key=value ... ip=... [fwd=...] path=...`, string values `repr()`-quoted so a crafted path/header can't forge extra lines. `ip` is `REMOTE_ADDR` (= Render's proxy in prod), `fwd` the raw `X-Forwarded-For`. Events: `login` / `login_failed` / `logout` (Django auth signals — site form, `/admin/`, allauth, Google; JWT failures too), `login backend='jwt'` (`api.serializers.LoggedTokenObtainPairSerializer`, wired via `SIMPLE_JWT["TOKEN_OBTAIN_SERIALIZER"]`), `signup` (site view + allauth `user_signed_up`), `password_reset_requested` (`SitePasswordResetForm.save`, with `emailed_user_ids`), `password_reset_completed`, `password_changed`/`password_set` (allauth pages), `email_changed` (profile + allauth), `email_confirmed`, `google_connected`/`google_disconnected`, `google_login_refused` (`users/adapters.py`, with `reason`), `comment_deleted`/`comment_delete_denied` (template view + API). Never logged: passwords, tokens, session ids; emails/usernames typed into login or reset forms go through `mask()` (`jo***@example.com`). Receivers are registered by `users/apps.py` `ready()`. Tests: `users/tests/test_security_log.py`, `movies/tests/test_catalog_logging.py`.

### Comments (`movies/comments.py`, 2026-09-30)

Comment block under "Cast" on the movie detail page. A user can leave any number of comments per movie; comments can't be edited, only deleted by their author. Likes/dislikes via `CommentVote` (`value` ±1, unique per comment/user; voting on your own comment is refused). `movies/comments.py` holds the shared query (`annotate_comments`: `likes`/`dislikes`/`user_vote` in one query) and `toggle_vote()` rules, used by both:
- template side — HTMX fragment views `comment_*` in `movies/views.py` + `movies/templates/movies/partials/comments/`. Errors come back with `HX-Retarget: #cm-flash`; 422 = form re-rendered with errors (see the `htmx:beforeSwap` handler in `section.html`). "Show more" paginates by offset (count of comments already on screen), not page number.
- API — `api/movie/<movie_id>/comments/`, `api/comments/<pk>/`, `api/comments/<pk>/vote/`.
Rate limits: `CommentCreateThrottle` (10/hour) and `CommentVoteThrottle` (60/min) in `movies/throttling.py`. UI copy is English, like the rest of the site. Tests: `movies/tests/test_comments.py`.

### AI recommendations (`movies/services.py`)

`get_ai(user, message, media_type)` builds a prompt from the user's `Watchlist` (first 20 entries: title + watched status) and calls Groq's `openai/gpt-oss-120b` with a fixed system prompt that enforces a strict output format and restricts answers to movies/TV topics. Used by the API (`api/views.py: RecommendationsAiView`, synchronous) directly, and by the template flow asynchronously via Celery.

**Template flow (Celery)**: `movies/views.py: ai_recomendations` enqueues `movies/tasks.py: get_ai_recommendation_task` (`.delay(user_id, message, media_type)`) and immediately returns `{"task_id": ...}`. `ai_recommendation_status(request, task_id)` polls `AsyncResult` and returns `{"status": "pending"}`, `{"status": "done", "result": {...}}`, or `{"status": "failed", "error": ...}`. The Alpine.js chat panel in `movies/templates/movies/partials/chrome/assistant.html` (included by `base.html`) polls `ai/status/<task_id>/` every 1.5s (up to ~45s) after posting a message. `docker-compose.yml` has a dedicated `worker` service (`celery -A config worker --loglevel=info`); `config/__init__.py` imports `celery_app` so Celery autodiscovers `movies/tasks.py`. Verified end-to-end via `docker compose up` (2026-09-05).

**Rate limit**: the template view and the API share `AIRecommendationThrottle` (10/hour per user, `movies/throttling.py`; the API also has `AIRecommendationAnonThrottle` 3/hour). `ai_recomendations` returns 429 with `{"error": "... try again in N minutes.", "retry_after": seconds}`. Both views are covered in `movies/tests/test_views_characterization.py` (Celery task and `AsyncResult` mocked).

**Model** (2026-09-05): Groq dropped the Llama 3.x chat line (`llama-3.3-70b-versatile` 404s). Every model available to this key is on the free tier (rate-limited, $0); `openai/gpt-oss-120b` was picked as the closest general-purpose match (30 RPM / 1K RPD).

### Redis caching (`movies/redis_services.py`)

The module docstring and `movies/tests/test_redis_services.py` are the source of truth. Two paths to the same Redis:

| Function | Path | Key | TTL |
|---|---|---|---|
| `cache_data_movie(endpoint, page, fetch, ttl=None, **kwargs)` — used by `get_list()` | raw `r`, JSON | `movies:list:v2:{endpoint}:{page}:{sorted k=v, no max_page}` | `ttl` if given, else `TTL_LIST` = 12h for every endpoint (curated, trending, keyword, discover with any filters) |
| `cache_genres(media_type, fetch)` | raw `r`, JSON | `movies:genres:v1:{media_type}` | `TTL_GENRES` = 36h |
| `cache_search_results(query, fetch)` | raw `r`, JSON | `movies:search:v1:{query, whitespace-collapsed, lower()}` | `TTL_SEARCH` = 7 days |
| `cache_item_detail` / `cache_items_detail` (batched MGET + pipelined SET) | raw `r`, JSON | `movies:{kind}:v1:{media_type}:{tmdb_id}` | `TTL_ITEM_DETAIL` = 6h — only used by the unused `enrich_item(s)` |
| `cache_tmdb(key, fetch, ttl)` | Django cache, pickle | `movies:details:v1:{media_type}:{id}`, `movies:season:v1:{tv_id}:{n}`, `movies:collection:v1:{id}`, `movies:keyword:v1:{id}` | `TTL_DETAIL` = 24h |

- The list key is built from the already-normalized kwargs passed to `get_list`, not the raw querystring, so blank/omitted params and param order don't fragment the cache. `ttl` is not part of the key.
- A raw-client hit returns decoded JSON (tuples → lists, int dict keys → strings); a miss returns the fetched object itself. Django-cache hits keep Python types.
- Caching happens *below* the per-user `Watchlist` annotation, so no per-user state is ever cached.
- Fallback: a Redis outage (`RedisError`) or a TMDB fetch failure (`TMDBFetchError`, raised by each `fetch()` closure) is never cached and never breaks page rendering — falls straight through to an uncached fetch (verified by stopping the `redis` container).
- Timing logs in `_cache_aside` are `logger.debug(...)`.
- `r` is created at import time from `os.getenv("REDIS_URL")` — tests replace it with `FakeRedis`.
- Bump the `vN` in a key builder when you change the shape of a cached value, so old entries aren't read back in the new format.

## Testing conventions

Tests live under `movies/tests/` and `users/tests/` (one file per view/service/model, e.g. `test_movie_view.py`, `test_tmdb_service.py`). Pattern used throughout: `pytest.mark.django_db` for DB-touching tests, `pytest-mock`'s `mocker.patch` to stub `TMDBClient` (and its methods) rather than hitting the real TMDB API, `RequestFactory` for view-level tests.

- **Cache isolation (autouse):** `movies/tests/conftest.py` has `isolated_cache` — locmem Django cache + an in-memory `FakeRedis` patched over `movies.redis_services.r`; it returns the `FakeRedis`, so a test can inspect `fake.store` / `fake.ttls` to assert cache keys and TTLs. `users/tests/conftest.py` swaps the Django cache to locmem. So tests never read or overwrite the dev site's Redis.
- **Characterization tests** (pin current behavior before a refactor) are the style reference: `movies/tests/test_tmdb_details.py`, `movies/tests/test_redis_services.py`, `movies/tests/test_views_characterization.py` (catalog, filters, Home, Detail, AI, `get_or_create_media`, incl. SQL query counts) and `users/tests/test_watchlist_characterization.py`. They are committed **separately and before** the refactor commit, so history shows they passed on the old code. A test that pins a known bug says so in a `# Known bug, pinned as is:` comment.
- **Gaps:** `api/tests.py` is empty — the DRF layer has no tests apart from the comment endpoints covered in `movies/tests/test_comments.py`.
- Other test files: `test_search_suggest.py`, `test_unique_email.py`, `test_auth_flows.py`, `test_google_login.py`, `test_security_log.py`, `test_catalog_logging.py`.

## Deploy (Render)

- Render builds and runs **only the `Dockerfile`** as one container. `docker-compose.yml` is local-dev-only (`web` on :8001, `worker`, `db` Postgres 16, `redis` 7) and Render never reads it.
- The Dockerfile `CMD` runs `migrate`, then a Celery worker in the background (`--pool=solo --without-heartbeat --without-gossip --without-mingle`, chosen to save memory and the hosted Redis command quota), then `python manage.py runserver --noreload 0.0.0.0:8000`. So production uses Django's dev server and an unsupervised worker — this is finding **C-1** in `qa-report/REPORT.md` (suggested fix: gunicorn + a supervised/separate worker). `EXPOSE 8001` doesn't match the port actually used (8000).
- `collectstatic` runs at image build time with a throwaway `DATABASE_URL=sqlite:///tmp.db`; static files are served by WhiteNoise.
- Production data stores are external: Neon Postgres (`DATABASE_URL`) and a hosted Redis (`REDIS_URL`, `rediss://` = TLS). `CELERY_BROKER_TRANSPORT_OPTIONS = {"polling_interval": 10.0}` exists because idle BRPOP polling burned the hosted Redis free-tier quota.
- `manage.py check --deploy` still warns about missing `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, HSTS (QA finding M-4).
- `users/migrations/0005_unique_user_email.py` creates a case-insensitive unique index on `auth_user.email` and fails while duplicates exist: run `manage.py find_duplicate_emails` (read-only report) / `--apply` (merges; back up first) before migrating a database that may have duplicates.

## Redesign (Movies.hub)

The static design in `design/design-source/` was ported into Django templates (read `design/HANDOFF.md` for the design itself). Rules that still apply to frontend work:
- No React and no build step. Django templates, plain CSS and plain JavaScript (Alpine.js or HTMX only if really needed).
- `movies/templates/movies/base.html` holds the fixed header, slim footer and floating Cinema Assistant button; every page extends it (except the allauth layout, see Authentication).
- Shared stylesheet in `movies/static/movies/` (apps have their own static dirs; there is no top-level `static/`) using the CSS variables from the design.
- Reuse components via {% include %}: poster card, section header, filter toolbar, pagination, actor card, form card.
- Keep existing views, URLs, models and tmdb_service.py behavior. Change templates/static first (`<app>/templates/`, `<app>/static/`); extend services only when a page needs a new TMDB endpoint.
- Never hide a design block. If data/endpoint is missing, render grey skeletons (`movies/components/skeleton_*.html`, `.sk.pulse`) with inert controls and a `{# PLACEHOLDER: needs … #}` comment; never invent titles/ratings. List them in `MISSING_DATA.md`.
- Work one page at a time, run the dev server, and show what changed before continuing.

### Status
All pages are ported (Home, Catalog family, Detail + comments, Watchlist/Profile, Search, Popular Actors, Auth + allauth pages), and Home/Detail/catalog are wired to real TMDB data (`a12c47d`, `96b40da`, `4a51a5b`). Details, decisions and the TMDB wiring table: `REDESIGN_REPORT.md`; data the design shows but the project can't supply yet: `MISSING_DATA.md`. Replaced templates are kept in `templates_old/` (not on the template path).
- Layout: every page sets `{% block body_class %}mh-body <page-class>{% endblock %}` and `{% block main_class %}mh-main{% endblock %}`, loads its own CSS via `{% block extra_css %}` and JS via `{% block page_js %}`. Shared CSS = `main.css`; per-page CSS is scoped by body class (`home-page`, `detail-page`, `pf-page`, `results-page`, `people-page`, `auth-page`).
- Components: `partials/poster_card.html` (TMDB dicts **and** `Movies` objects), `media_card.html` (home rows), `filter_toolbar.html` + `catalog.js` (also drives the watchlist filter form via `data-htmx`), `pagination.html`, `section_header.html`, `actor_card.html`, `users/partials/auth_field.html`, `profile_header.html`.
- `movies/templatetags/catalog_tags.py`: `year_of`, `genre_names` (static TMDB genre ids), `days_until`, `pretty_date`, `compact_votes`, `qs_without`, `times`, `runtime`. A new templatetags module needs a dev-server restart.
- Base resets in `main.css` use `:where(.mh-body)` (zero specificity) so component classes always win; keep it that way.
- Profile **Stats tab is hidden** (2026-11-04, `00f59f6`): the code is wrapped in `{% comment %}` (search `FUTURE:`), not deleted; Watchlist link removed from the navbar, Profile opens the Watchlist tab. Plan to bring it back: `FUTURE_NOTES.md` (local only).
- Static files that no template references any more (leftovers from the old design, candidates for cleanup — ask the owner before deleting): `movies/static/movies/{actor_section,ai_chat,category,comments,filters,movie_detail,movie_list,popular_actors,search,test}.css`, `users/static/users/{allauth_theme,login,register,test_watchlist}.css`.
