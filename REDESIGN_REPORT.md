# Redesign report (Movies.hub design → Django templates)

Branch: `redesign` (nothing pushed, `main` untouched). Source of truth: `design/design-source/*.dc.html`, `design/HANDOFF.md`.

## What was ported
| Step | Pages / URLs | Main files |
|---|---|---|
| 1 Chrome | fixed glass header (real nav, search, auth-aware buttons, mobile drawer), slim footer, floating Cinema Assistant | `movies/base.html`, `partials/chrome/*`, `static/movies/main.css`, `chrome.js` |
| 2 Catalog | Movies, TV, Anime, Doramas, Cartoons (with filters) and Popular, TV Popular, Top Rated, Now Playing, Upcoming | `movies/catalog.html` (+ thin `type/*.html`, `category/*.html`), `partials/poster_card.html`, `filter_toolbar.html`, `active_filters.html`, `movie_list.html`, `pagination.html`, `catalog.js` |
| 3 Home | `/movies/` | `movies/home.html`, `partials/media_card.html`, `section_header.html`, `actor_card.html`, `home.css`, `home.js` |
| 4 Detail | `/movies/movie/<id>/<type>/` incl. comments (HTMX partials restyled) | `movies_detail.html`, `partials/comments/*`, `detail.css`, `detail.js` |
| 5 Watchlist + Profile | `/users/watchlist/`, `/users/profile/` (kept as two URLs, shared header/tabs) | `users/watchlist.html`, `profile.html`, `partials/profile_header.html`, `watchlist_result.html`, `profile.css`, `profile.js` |
| 6 Search (+ Popular Actors) | `/movies/search/`, `/movies/popular-actors/` | `search.html`, `popular_actors.html`, `results.css`, `people.css`, `search.js` |
| 7 Auth | login, register, password reset (form / sent / new password / invalid link / done), allauth pages (`/accounts/...`), reset email | `users/auth_card_base.html`, `login.html`, `register.html`, `password_reset*.html`, `partials/auth_field.html`, `allauth/layouts/base.html` + `allauth/elements/*`, `auth.css`, `auth.js`, `password_reset_email.html` |

Design CSS is split into: `main.css` (tokens + shared components: buttons, badges, section header, header/drawer/footer, assistant, catalog grid/filters/pagination, flash messages), and per-page files scoped by a body class (`home-page`, `detail-page`, `pf-page`, `results-page`, `people-page`, `auth-page`) so class names from the design (`.hero`, `.track`, `.card`…) don't collide.
Old templates that were replaced are in `templates_old/` (outside the template path). Old static CSS (`movie_detail.css`, `comments.css`, `search.css`, `test.css`, `users/{login,register,profile,allauth_theme,test_watchlist}.css`, …) is no longer referenced by any template but is left on disk.

## Hard rules check
- No view, URL, model, form, migration or `tmdb_service.py` change. Added only a template-tag module `movies/templatetags/catalog_tags.py` (year/countdown/date helpers, a static TMDB genre-id→name map, `qs_without` for filter chips).
- Bootstrap, Bootstrap Icons and every old stylesheet were removed from `base.html` (nothing needs them any more); Alpine + HTMX are still used (assistant, comments, watchlist filters/remove/watched).
- All forms keep their field names / POST targets / `{% csrf_token %}`; watchlist toggle still goes through `watchlist_toggle.js` (`data-watchlist-form`); filter and pagination query params are unchanged (`genre_search`, `years_search`, `country_search`, `rating_search`, `page`, `q`).
- Blocks with no data are NOT hidden any more: they render as grey skeletons / inert controls (see "Restored placeholder blocks" below and `MISSING_DATA.md`).

## Behaviour that differs from the old site
- Catalog: genre/country/year are single-choice radios (as the old backend only accepted one value); filters apply immediately on desktop and via "Show results" in the mobile sheet; filtering is now a normal GET (no HTMX swap) so URLs are shareable. Active filters are removable chips.
- Catalog cards: the old "watched" checkbox (which posted the TMDB id to the toggle URL) is replaced by a "Watched" toggle that posts the real watchlist id; it only appears for titles already in the watchlist.
- Home: Trending, Movie of the Week, Topic of the Day and the mood picks row are skeleton blocks; mood chips link to the catalog; "Popular Right Now" has All / Movies / TV / In Theaters tabs.
- Detail: emoji icons replaced by line icons; the rating widget is an inert placeholder (the old page had none); "Add to Watchlist" for guests now goes to login with `?next=`.
- Profile: the profile form now shows field errors; the avatar preview script was fixed (it referenced a missing element).
- Search: tabs All/Movies/TV/People; All/Movies/TV filter the already-returned results in the browser, People is a skeleton.
- Auth: login field is e-mail (unchanged); register shows the checklist (informational, Django validators still decide).
- Flash messages are toasts under the header (no Bootstrap alerts).
- The 72px header is taller than the old 56px navbar; page spacing comes from the design, not the old `.main-default` margins.

## Verification done
- `docker compose exec web python manage.py check` clean.
- Every affected URL requested as guest (HTTP 200, no template errors): home, 10 catalog pages incl. filter/page combinations, 3 detail pages (movie/TV), search (hit/no hit/empty), popular actors, login, register, 4 password-reset screens, `/accounts/login|signup|password/reset`.
- Logged-in rendering via Django test client for home, catalog, detail (movie/TV), watchlist (+ HTMX filter endpoint), profile.
- Browser (Chrome, desktop width): home (hero next, tabs filter), catalog (genre filter submits, active chip), detail (hero, stills, cast, comments as guest), login/register (incl. red CTA), logged-in watchlist/profile/search rendered as static snapshots; no console errors on home.
- Test suite in Docker: **138 passed, 2 failed** — `test_tmdb_service.py::test_genres` and `::test_get_list_without_data`. Both fail because the tests share the dev Redis with the running site (the first test writes `[{"id":1,"name":"Action"}]` into `movies:genres:v1:movie`, which the site then serves as the genre list; if the key is empty the test sees real genres). Neither test renders a template (they mock TMDB and call the service); `test_get_list_without_data` was already failing at the end of step 1, and I did not check it on the commit before the redesign. Recommended fix: isolate the cache in those tests. After running tests, clear `movies:genres:*` in local Redis if the catalog shows a single genre.
- Two existing comment tests assert exact copy ("Log in</a> to leave a comment", "No comments yet."), so those strings were kept in the new markup.

## Not verified / known gaps
- Real logged-in interactions in the browser (watchlist toggle, comment post/vote/delete, watched toggle, assistant chat, Google sign-in, password reset e-mail delivery) — no credentials were used; only server-side rendering was checked.
- Mobile / tablet layouts: CSS and breakpoints were ported from the design, but the browser window could not be resized in this session, so they were not looked at.
- Keyboard/screen-reader pass (focus order in popovers, lightbox, trailer modal) was implemented following the design but not tested with assistive tech.
- `password_reset_email.html` (HTML e-mail) exists but is not sent (see MISSING_DATA).
- Hero carousel autoplay timings, reduced-motion handling and the TMDB hot-linked images are untested under slow networks.

## Restored placeholder blocks (second pass: "never hide a block")
Everything below was hidden or reduced in the first pass and is now present as in the design, with skeletons / inert controls and a
`{# PLACEHOLDER: needs … #}` comment. Full list with suggested endpoints: `MISSING_DATA.md`.

| Page | Restored block | What data it needs |
|---|---|---|
| Header | Search dropdown (recent + suggestions rows, key hints) | suggestions endpoint, recent-searches store |
| Footer | Privacy · Terms · Contact links | those pages |
| Home | Trending row + Today/This Week toggle | trending/all day+week |
| Home | Movie of the Week | curated id, movie details, cast |
| Home | Pick by Mood poster row | discover/movie per genre |
| Home | Topic of the Day | keyword/{id}/movies |
| Home | Popular Right Now "Movies" tab; Coming Soon "Release calendar" link and "Trailer" buttons | (tab uses popular; trailer keys; calendar page) |
| Home | Stars of the Week title/eyebrow (real popular actors, skeleton when empty); TV&Categories skeleton fallback | trending/person/week; tv lists |
| Catalog | "N titles" counter, "N results", Sort chip, toolbar on list pages (disabled) | total_results, sort param, filter support |
| Detail | Tagline, runtime, status, vote counts, community badge, Your rating, Watched eye | movie/tv details, ratings endpoint, watched flag |
| Detail | Keywords, Writer/Producer/Music, extra Details rows | keywords, crew, details |
| Detail | Posters tab, trailer duration, View full cast | images.posters, videos, full cast page |
| Detail | Seasons/episodes (TV) / Collection (movies) | tv/{id}/season/{n}; collection |
| Detail | You may also like | recommendations |
| Detail | Comment Reply | Comment.parent |
| Profile/Watchlist | Edit profile button (links to Settings), 3 stat tiles, Stats tab content, Sort chip, status filter (To watch / Watched) | aggregates, sort + watched filter |
| Profile/Settings | Disconnect Google, Delete account | routes |
| Search | People tab + section + "View all people", Sort chip, Showing x–y line (real), pagination (static) | people search, sort, total_results/paging |
| Auth | Terms/Privacy checkbox (register), Resend (reset sent), legal links in e-mail | pages, resend endpoint |

## TMDB wiring (2026-10-29)
Every TMDB call goes through `TMDBClient._request` (timeout `(3.05, 10)`, request/JSON errors → empty dict → the block's skeleton,
never a 500). New responses are cached with Django's cache framework (`redis_services.cache_tmdb`, same Redis); the existing list
cache (`cache_data_movie`) got endpoint-based TTLs. TTLs: curated lists (trending / popular / top_rated / now_playing / upcoming /
tv lists) 12h, detail + season + collection + keyword 24h, genre lists 36h, filtered `discover/*` 15 min (home rows that use discover
pass 12h). Home runs its ~30 calls in parallel (`fetch_parallel`, ThreadPoolExecutor): measured ~3.6s cold, ~40ms warm locally.
Detail is one `movie|tv/{id}` request with `append_to_response` (+ one season or collection request); the local `Movies` row is
created from that same response.

| Block | Endpoint used | Page | Status |
|---|---|---|---|
| Hero slides + trailers | `movie/popular` + `get_details` per slide (5, parallel) | Home | wired (before this pass) |
| Trending Today / This Week | `trending/all/day`, `trending/all/week` via `get_trending()` | Home | wired |
| Coming Soon (+ Trailer buttons) | `movie/upcoming` minus `movie/now_playing`; trailers from `get_details` (8, parallel) | Home | wired |
| Movie of the Week | #1 of `trending/movie/week` → `movie/{id}` + credits (`get_details`) | Home | wired |
| Popular Right Now | `movie/popular`, `movie/now_playing`, `tv/popular` | Home | wired |
| Pick by Mood | `genre/movie/list` (chip labels) + `discover/movie?with_genres={id}&sort_by=popularity.desc&vote_count.gte=300` per mood (`views.MOODS`) | Home | wired |
| All-Time Greats | `movie/top_rated` | Home | wired |
| Stars of the Week | `trending/person/week` (actors only) | Home | wired (cards not links: no person page) |
| Topic of the Day | `keyword/{id}` + `keyword/{id}/movies`, id rotated daily from `views.TOPIC_KEYWORDS` | Home | wired (CTA → top film; no keyword page) |
| TV & Categories | `tv/popular`; `discover/tv` with the Doramas / Anime / Cartoons catalog filters | Home | wired |
| Tagline, runtime / seasons, status, vote count, genres | `movie|tv/{id}` | Detail | wired |
| Keywords, writer / producer / music / creator | `keywords`, `credits` (appended) | Detail | wired |
| Original title, language, certification | `movie|tv/{id}` + `release_dates` / `content_ratings` (US) | Detail | wired |
| Stills / Posters tabs | `images` (appended, `include_image_language=en,null`) | Detail | wired |
| Trailer | `videos` (appended) | Detail | wired; duration still skeleton (not in TMDB) |
| Cast & Crew | `credits` (appended) | Detail | wired |
| Seasons + episodes | `tv/{id}` seasons + `tv/{id}/season/{n}` for the selected season only (`?season=N`) | Detail | wired |
| Collection | `belongs_to_collection` + `collection/{id}` | Detail | wired; no block when the movie has no collection |
| You may also like | `recommendations` (appended) | Detail | wired ("View all" still inert) |
| Community count, watched eye | local `Rating` count, `Watchlist.watched` | Detail | wired (eye only for titles in the watchlist) |
| Your rating | — (needs a session "rate" view) | Detail | still skeleton / inert |
| "N titles" / "N results" | `total_results` of the page's list | Catalog | wired |
| Sort chip | `discover/movie|tv` `sort_by` (+ `vote_count.gte`, release-date upper bound) | Catalog (type pages) | wired; inert on the fixed-list pages |
| Filters (genre / year / country / min rating) | `with_genres`, `primary_release_year` / `first_air_date_year`, `with_origin_country`, `vote_average.gte` | Catalog (type pages) | wired (before this pass; min rating now adds `vote_count.gte=100`) |

`get_credit()` was replaced by `get_details()` (same caller contract plus the extra fields); `test_comments.py` mocks it accordingly.
Tests in Docker: 143 passed; the 2 known `test_tmdb_service.py` failures (shared dev Redis, see above) are unchanged.
