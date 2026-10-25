# MISSING_DATA — design blocks that have no data in the project yet

Rule used during the port: views, URLs, models, forms and `tmdb_service.py` were not touched, so a block is either
mapped onto data the existing views already pass, replaced by the closest real thing, or hidden when showing it
would mean inventing data. This file lists every block that is **not** a 1:1 port, and what it would need.

## Home (`movies/home.html`, view `HomeView`)
| Block | State now | Needs |
|---|---|---|
| Hero — runtime | hidden | `movie/{id}` details (runtime) |
| Hero — "Watch Trailer" | links to the detail page (`#trailer`, where the trailer already plays) | `movie/{id}/videos` (trailer key) in the home context to open the modal directly |
| Hero label | says "Popular now" (design: "Trending now") because the list is `movie/popular` | `trending/movie/day` |
| Trending (Today / This Week toggle) | shown as **Popular Movies** row (no toggle) | `trending/all/day` + `trending/all/week` |
| Coming Soon — Trailer button | "Details" button instead | videos per upcoming title |
| Coming Soon — "Release calendar" link | omitted (no such page) | a calendar page/route |
| Movie of the Week | **hidden** (editor's pick, week number, tagline, cast would all be invented) | curated tmdb id (DB/setting) + `movie/{id}` + `credits` |
| Popular Right Now tabs | All / In Theaters / TV (client-side filter). Design also has "Movies" | — (data = `now_playing` minus popular, `tv/popular`) |
| Pick by Mood — poster row | **hidden**; mood chips are real links into the catalog (`?genre_search=<id>`) | `discover/movie?with_genres=` per mood |
| All-Time Greats | real (`movie/top_rated`, first 10) | — |
| Stars of the Week | shows **Popular Actors** (`person/popular`), cards are not links (no person page) | `trending/person/week`, a person detail page |
| Topic of the Day | **hidden** | `keyword/{id}/movies` |
| TV & Categories | featured + 6 minis from `tv/popular`; Doramas / Anime / Cartoons are links to their catalog pages, not in-place tabs | one `discover/tv` call per category in the home view |
| Watchlist state on home cards | cards always show "Watchlist" (add); adding an item already saved is handled by the existing add view | watchlist ids in the `HomeView` context |

## Catalog (`movies/catalog.html`, `AllMoviesView`)
| Block | State now | Needs |
|---|---|---|
| "N titles" counter, "N results" | hidden | `total_results` from TMDB in the context |
| Sort control | hidden | a `sort`/`sort_by` param in `AllMoviesView.search_filter_movie` |
| Genre multi-select, year range, country multi-select, rating slider with vote threshold | single genre (radio), single year, single country, minimum rating; they use the existing `genre_search / years_search / country_search / rating_search` params | multi-value filters in the view |
| Filters on Popular / TV Popular / Top Rated / Now Playing / Upcoming | no toolbar (those views never supported filters, as before) | filter support in those views |
| Loading skeletons | not used (server-rendered pages) | — |

## Detail (`movies/movies_detail.html`, `MoviesDetailView`)
| Block | State now | Needs |
|---|---|---|
| Tagline, status badge, runtime, vote count | hidden | `movie/{id}` / `tv/{id}` fields stored on `Movies` or passed in context |
| Keywords | hidden | `keywords` endpoint |
| Production companies / networks, countries | only `Movies.author` (studio) and `Movies.country` | full details in context |
| Your rating + community rating widget | **hidden** (only the community average is shown when ratings exist) | a session-authenticated POST endpoint for ratings (the existing one is the JWT API) and the vote count |
| Watched (eye) button | hidden | `Watchlist.watched` for this movie in the context (only `watchlist_id` is passed) |
| Posters tab | hidden (stills only) | `images.posters` |
| Seasons / episodes (TV) | hidden | `tv/{id}/season/{n}` |
| Collection (movies) | hidden | `belongs_to_collection` + `collection/{id}` |
| You may also like | hidden | `/recommendations` or `/similar` |
| Cast: "View full cast", person pages | cards are not links | person route/view |
| Comment replies / threads | none (model has no parent); like **and** dislike are kept (design: like only) | `parent` FK on `Comment` |

## Profile / Watchlist (`users/watchlist.html`, `users/profile.html`)
| Block | State now | Needs |
|---|---|---|
| Stat tiles (watched, avg rating, hours watched) | only "Saved titles" (paginator count) | counts/aggregates in `WatchlistView` context |
| Stats tab (favourite genres, watched per year, movies vs TV) | **hidden** | aggregates over `Watchlist` (+ watched date) |
| Status filter All / To watch / Watched, Sort | hidden | `watched` filter + ordering in `search_watchlist` |
| Edit profile / tabs | two separate pages (`/users/watchlist/`, `/users/profile/`) share header + tabs | — |
| Delete account, Disconnect Google | hidden | routes/views |
| Photo size limit text ("up to 5 MB") | generic hint | validation rule in `ProfileUpdateForm` |
| Filtering via HTMX returns an unpaginated list (as before); the page pagination stays visible below it | unchanged behaviour | pagination in `search_watchlist` |

## Search (`movies/search.html`, `SerachView`)
| Block | State now | Needs |
|---|---|---|
| People tab, Anime / K-Drama chips | hidden | `search/person` (or `search/multi` people) |
| Sort (relevance / popularity / rating / newest) | hidden | sort param in the view |
| Live dropdown under the header search (results, recent, keyboard hints) | not built: header search submits a normal GET to `/movies/search/` | a lightweight suggestions endpoint |
| Counters per tab, "Showing x–y of N", pagination | counts computed in the browser from the page's results; no pagination (view returns the full list) | `total_results` + paging in the view |

## Auth
| Block | State now | Needs |
|---|---|---|
| "I agree to Terms / Privacy" checkbox | omitted | Terms and Privacy pages + a form field |
| "Resend" with cooldown on the "check your email" screen | omitted (link to "Try again" instead) | a resend endpoint |
| Reset email (HTML) | template ported at `users/templates/users/password_reset_email.html` but **not wired** — Django still sends the plain text body | `html_email_template_name="users/password_reset_email.html"` on `PasswordResetView` in `users/urls.py` (route config, out of scope) |
| Reset link lifetime text | "limited time" (design says one hour; `PASSWORD_RESET_TIMEOUT` is the Django default, 3 days) | — |
| Login by "username or email" | email only (the existing `EmailLoginForm`) | — |

## Global
| Block | State now | Needs |
|---|---|---|
| Footer links Privacy / Terms / Contact | omitted | the pages |
| Cinema Assistant | unchanged behaviour (Celery flow); guests see a login gate | — |
