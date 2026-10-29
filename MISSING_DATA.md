# MISSING_DATA — design blocks rendered as grey skeletons / inert controls

Rule: no block from `design/design-source` is hidden. Where the project has no data or endpoint, the block keeps its layout, title,
eyebrow, "View all" link, tabs and controls, and shows grey pulsing skeletons (`movies/components/skeleton_cards.html`,
`skeleton_people.html`, or inline `.sk.pulse`). Controls inside such blocks are visible but inert (`aria-disabled`) or point to the
closest real page. Every one is marked in the templates with `{# PLACEHOLDER: … #}` (`grep -rn PLACEHOLDER movies users`).

Since the TMDB wiring pass (2026-10-29, see `REDESIGN_REPORT.md` → "TMDB wiring") the Home, Detail and Catalog blocks get real data.
Their skeletons are now **fallbacks only**: they show when the TMDB request behind the block fails (timeout, error, empty result)
and are marked `{# PLACEHOLDER: shown only when … failed #}`. Those fallbacks are not listed below — only what is still missing.

| Page | Block (what the user sees) | Why it is still missing | What it would need |
|---|---|---|---|
| Header (all pages) | Search dropdown: "Recent searches" rows (skeleton) | no store for recent searches | localStorage or a DB model |
| Footer (all pages) | Privacy · Terms · Contact links (point to `#`) | the pages don't exist | three pages |
| Home | Coming Soon: "Release calendar" links to the Upcoming list | no calendar page | a page |
| Home | Topic of the Day: "Explore collection" opens the topic's top film | no keyword page | a URL + view over `keyword/{id}/movies` (new URL, out of scope) |
| Home | Stars of the Week cards are not links; "known for" line is empty | no person page (out of scope); `trending/person/week` has no `known_for` | person route; `person/{id}/combined_credits` |
| Home | Cards' watchlist state (always "Watchlist") | `HomeView` doesn't pass the user's watchlist ids | a Watchlist lookup in `HomeView` (data exists, not wired in this pass) |
| Catalog (Popular, TV Popular, Top Rated, Now Playing, Upcoming) | Filter toolbar + Sort chip shown but disabled | those pages use TMDB's fixed lists, which take no filters / `sort_by` | switch them to `discover/*` |
| Catalog (type pages) | Filters are single-choice (genre / year / country / min rating) | old backend params take one value | `with_genres=a,b`, `primary_release_date.gte/lte` |
| Detail | **Your rating** button + popover / mobile "Your rating" card (inert) | ratings exist only in the JWT API | a session-auth "rate" view (out of scope) |
| Detail | Watched (eye) button for titles **not** in the watchlist (inert) | `Watchlist.watched` lives on the watchlist row | a "watched" flow that also creates the row |
| Detail | Community badge skeleton when nobody rated the title | no `Rating` rows for it (count + average are real otherwise) | — |
| Detail | Trailer duration pill | TMDB videos carry no length | YouTube Data API |
| Detail | "View full cast" link (inert) | no full-cast page | a page over `credits.cast` |
| Detail | "View all" in "You may also like" (inert) | no recommendations page | a page over `/recommendations` |
| Detail | Collection: "View collection" opens the first film | no collection page | a page over `collection/{id}` |
| Detail | Keyword chips are not links | no keyword page | same as Topic of the Day |
| Detail | Comments: Reply button (inert) and threads | `Comment.parent` | model/migration (out of scope) |
| Profile / Watchlist | Stat tiles Watched, Avg. rating, Hours watched (skeleton; "In watchlist" is real) | aggregates not computed | queries over `Watchlist`, `Rating`, runtime |
| Profile / Watchlist | **Stats tab** content (top-genre/highest-rated/most-recent cards, genre bars, watched-per-year, Movies-vs-TV donut) | aggregates not computed | queries over `Watchlist` |
| Profile / Watchlist | Sort chip (inert); status filter "To watch" / "Watched" + counts (inert / skeleton) | not in `search_watchlist` | sort + watched filter |
| Profile / Settings | "Disconnect" Google, "Delete account" (inert) | no routes | views |
| Search | **People** tab, People section + "View all people" (skeleton grid) | search endpoints are a separate task | `search/person` |
| Search | Sort chip (inert, "Relevance") | separate task | `search/multi` has no sort → client/DB sort |
| Search | Pagination (static page 1/1); counts are the page's own result count | separate task | `total_results` + `page` in `SerachView` |
| Auth | Register: "I agree to Terms and Privacy Policy" checkbox (inert, links `#`) | no pages / consent field | pages + form field |
| Auth | Reset sent: "Resend" returns to the reset form; no cooldown timer | no resend endpoint | endpoint with cooldown |
| Auth | Reset e-mail (HTML) exists but is not sent | `html_email_template_name` not set | `users/urls.py` one-liner (out of scope) |

## Resolved by the TMDB wiring pass (2026-10-29)
Home: Trending (day/week), Stars of the Week (`trending/person/week`), Coming Soon trailers, Movie of the Week, Pick by Mood row,
Topic of the Day, TV & Categories tabs (Doramas / Anime / Cartoons), All-Time Greats, Popular Right Now. Detail: tagline, runtime /
seasons count, status, TMDB vote count, genres fallback, keywords, writer / producer / music / creator, original title, language,
certification, posters tab, recommendations, seasons + episodes, collection, community rating count, watched toggle (titles in the
watchlist). Catalog: "N titles" / "N results", Sort chip on the discover pages.
