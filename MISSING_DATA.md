# MISSING_DATA — design blocks rendered as grey skeletons / inert controls

Rule: no block from `design/design-source` is hidden. Where the project has no data or endpoint, the block keeps its layout, title,
eyebrow, "View all" link, tabs and controls, and shows grey pulsing skeletons (`movies/components/skeleton_cards.html`,
`skeleton_people.html`, or inline `.sk.pulse`). Controls inside such blocks are visible but inert (`aria-disabled`) or point to the
closest real page. Every one is marked in the templates with `{# PLACEHOLDER: needs … #}` (`grep -rn PLACEHOLDER movies users`).
No views, URLs, models, forms or `tmdb_service.py` were changed to build these.

| Page | Block (what the user sees) | Needs (data) | Suggested TMDB endpoint / change |
|---|---|---|---|
| Header (all pages) | Search dropdown: Recent searches + Suggestions rows (skeleton), keyboard hints | suggestions + a recent-searches store | `search/multi` (debounced JSON endpoint), localStorage/DB for recents |
| Footer (all pages) | Privacy · Terms · Contact links (point to `#`) | the three pages | — |
| Home | Hero (grey fallback only if `now_popular` is empty); runtime missing in hero meta | runtime | `movie/{id}` |
| Home | "Watch Trailer" / "Trailer" buttons open the detail page (`#trailer`) | trailer key in context | `movie/{id}/videos` |
| Home | **Trending** row + Today / This Week toggle (skeleton cards, inert toggle) | trending titles | `trending/all/day`, `trending/all/week` |
| Home | Coming Soon: "Release calendar" link goes to the upcoming list | a calendar page | — |
| Home | **Movie of the Week** (full skeleton card) | curated tmdb id + details + top 4 cast | DB/setting + `movie/{id}`, `movie/{id}/credits` |
| Home | Pick by Mood — picks row (skeleton cards; chips are real links into the catalog) | movies per mood | `discover/movie?with_genres={id}` |
| Home | Stars of the Week — real data is *popular* actors (not weekly); cards not links | weekly trending people, person pages | `trending/person/week` + a person route |
| Home | **Topic of the Day** (full skeleton banner) | topic/keyword + its movies | `keyword/{id}/movies` |
| Home | TV & Categories — only TV Shows has data; Doramas / Anime / Cartoons tabs are links to their catalog pages | per-category lists in the home view | `discover/tv?with_original_language=…&with_genres=…` |
| Home | Cards' watchlist state (always "Watchlist") | watchlist ids in `HomeView` context | — |
| Catalog (all) | "N titles" next to the title; "N results" in the filters row (skeleton pills) | `total_results` | TMDB list response field |
| Catalog (all) | Sort chip (inert, "Popularity") | sort param in `AllMoviesView` | `sort_by` |
| Catalog (Popular, TV Popular, Top Rated, Now Playing, Upcoming) | Filter toolbar shown but disabled (those views ignore filters) | filter support in those views | `discover/*` params |
| Catalog (type pages) | Filters are single-choice (genre / year / country / min rating) | multi-value + year range | `with_genres=a,b`, `primary_release_date.gte/lte` |
| Detail | Tagline, runtime, status badge (skeleton in hero meta) | tagline, runtime, status | `movie/{id}`, `tv/{id}` |
| Detail | Genre chips when the title has none (skeleton) | genres | — |
| Detail | TMDB badge vote count; Community badge (skeleton when no ratings, plus rating count) | `vote_count`; number of ratings | `movie/{id}`; `Rating` count |
| Detail | **Your rating** button + popover / mobile "Your rating" card (inert) | a session-auth "rate" endpoint (ratings exist only in the JWT API) | new view (out of scope) |
| Detail | Watched (eye) button (inert) | `Watchlist.watched` for the title in context | — |
| Detail | Keywords row (skeleton chips) | keywords | `movie/{id}/keywords` |
| Detail | Credits: Writer, Producer; crew row: Writer, Music (skeleton) | more roles from credits | `credits.crew` |
| Detail | Details card: Original title, Language, Certification (skeleton rows) | those fields | `movie/{id}`, release dates |
| Detail | Trailer duration pill; Posters tab (+ count) with skeleton grid; Stills skeleton when no backdrops | duration; posters | `movie/{id}/videos`, `images.posters` |
| Detail | "View full cast" link (inert); cast skeleton when no credits | full cast page | `credits.cast` |
| Detail | **Seasons / episodes** (TV) and **Collection** (movies) | seasons + episodes; collection parts | `tv/{id}/season/{n}`, `belongs_to_collection` + `collection/{id}` |
| Detail | **You may also like** (+ "View all", skeleton cards) | recommendations | `movie/{id}/recommendations` |
| Detail | Comments: Reply button (inert) and threads | `Comment.parent` | model/migration (out of scope) |
| Profile / Watchlist | Stat tiles Watched, Avg. rating, Hours watched (skeleton; "In watchlist" is real) | aggregates | queries over `Watchlist`, `Rating`, runtime |
| Profile / Watchlist | **Stats tab** content (top-genre/highest-rated/most-recent cards, genre bars, watched-per-year columns, Movies-vs-TV donut) | aggregates | queries over `Watchlist` |
| Profile / Watchlist | Sort chip (inert); status filter "To watch" / "Watched" + counts (inert / skeleton) | sort + watched filter in `search_watchlist` | — |
| Profile / Settings | "Disconnect" Google, "Delete account" (inert) | routes/views | — |
| Search | **People** tab, People section + "View all people" (skeleton grid, count skeleton) | people results | `search/person` |
| Search | Sort chip (inert, "Relevance") | sort param | `search/multi` has none → client/DB sort |
| Search | Pagination (static page 1/1, "Go to page" disabled); counts are the page's own result count | `total_results` + paging in `SerachView` | `page` param |
| Auth | Register: "I agree to Terms and Privacy Policy" checkbox (inert, links `#`) | Terms/Privacy pages + consent field | — |
| Auth | Reset sent: "Resend" returns to the reset form; no cooldown timer | resend endpoint with cooldown | — |
| Auth | Reset e-mail (HTML) exists but is not sent | `html_email_template_name` on `PasswordResetView` | `users/urls.py` one-liner (out of scope) |
