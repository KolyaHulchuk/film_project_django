import logging
import time
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import partial
from typing import Any

import requests
from django.conf import settings

from .redis_services import (
    TTL_DETAIL,
    TMDBFetchError,
    cache_data_movie,
    cache_genres,
    cache_item_detail,
    cache_items_detail,
    cache_tmdb,
)

# A decoded TMDB JSON object (or a dict shaped from one).
TMDBData = dict[str, Any]

IMAGE_BASE = "https://image.tmdb.org/t/p"

# One request for everything the detail page shows (see TMDBClient.get_details).
DETAIL_APPEND = {
    "movie": "videos,credits,images,keywords,recommendations,release_dates",
    "tv": "videos,credits,images,keywords,recommendations,content_ratings",
}

# Crew roles the detail page shows, by TMDB credits.crew "job".
CREW_ROLES = {
    "Director": "director",
    "Screenplay": "writer",
    "Writer": "writer",
    "Story": "writer",
    "Novel": "writer",
    "Producer": "producer",
    "Original Music Composer": "music",
    "Music": "music",
}

# Media types shown as cards (search results, recommendations); "person" is dropped.
CARD_MEDIA_TYPES = ("movie", "tv")

# How much of each appended block the detail page keeps.
CAST_LIMIT = 20
KEYWORD_LIMIT = 12
RECOMMENDATION_LIMIT = 14
BACKDROP_LIMIT = 6
POSTER_LIMIT = 12

# Fields kept per entry when trimming TMDB responses before caching.
CAST_FIELDS = ("id", "name", "character", "profile_path")
EPISODE_FIELDS = ("episode_number", "name", "overview", "air_date", "runtime", "still_path", "vote_average")
COLLECTION_PART_FIELDS = ("id", "title", "release_date", "poster_url", "vote_average", "vote_count")

# release_dates "type" for a theatrical release, preferred for the US certification.
THEATRICAL_RELEASE = 3

# Pagination caps: TMDB reports far more pages than are worth browsing.
DEFAULT_LIST_MAX_PAGE = 10
POPULAR_ACTORS_MAX_PAGES = 50

TRENDING_MEDIA_TYPES = ("all", "movie", "tv", "person")
TRENDING_WINDOWS = ("day", "week")


def fetch_parallel(tasks: dict[Hashable, Callable[[], Any]], max_workers: int = 10) -> dict[Hashable, Any]:
    """Run independent TMDB calls concurrently.

    tasks: {name: zero-argument callable}. Returns {name: result}; a call that
    raises is logged and comes back as None, so one failed block never takes
    the page down. The callables must not touch the database (threads get
    their own DB connections that nobody closes).
    """
    if not tasks:
        return {}
    results = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                logging.exception("TMDB call %s failed", name)
                results[name] = None
    return results


def _require(data: TMDBData, key: str, fallback: Any) -> None:
    """Raise TMDBFetchError(fallback) unless `data` is a non-empty response containing `key`.

    Used inside the cache `fetch()` closures: _request() returns {} on any
    failure, and raising here is what keeps that failure out of the cache.
    """
    if not data or key not in data:
        raise TMDBFetchError(fallback)


def _image_url(path: str, size: str) -> str:
    """Full TMDB image URL for a file_path/poster_path, e.g. size="w500"."""
    return f"{IMAGE_BASE}/{size}{path}"


def _dedupe_by_id(items: list[TMDBData]) -> list[TMDBData]:
    """Keep the first item for each "id", preserving order."""
    seen_ids = set()
    unique = []
    for item in items:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique.append(item)
    return unique


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
    TIMEOUT = (3.05, 10)  # (connect, read) seconds

    def __init__(self, api_key: str | None = None, languages: list[str] | None = None) -> None:
        self.api_key = api_key or settings.TMDB_API_KEY
        self.languages = languages or ["en"]

    # ------------------------------------------------------------------ HTTP

    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> TMDBData:
        url = f"{self.BASE_URL}/{endpoint}"
        params = dict(params or {})
        params["api_key"] = self.api_key
        try:
            response = requests.get(url, params=params, timeout=self.TIMEOUT)
            if response.status_code == 200:
                return response.json()
            logging.warning(f"TMDB API error {response.status_code} for endpoint '{endpoint}'")
        except (requests.RequestException, ValueError) as exc:
            # Timeouts, connection errors and invalid JSON all end up as "no data".
            logging.warning(f"TMDB request failed for endpoint '{endpoint}': {exc!r}")
        # Empty dict on failure, not an exception: callers (get_list/enrich_item/etc.)
        # check for missing keys and raise TMDBFetchError themselves, which is what
        # keeps a failed TMDB call from ever being written to the Redis cache.
        return {}

    # ------------------------------------------------------------------ Raw lookups

    def get_movie_by_tmdb_id(self, tmdb_id: int) -> TMDBData:
        return self._request(f"movie/{tmdb_id}")

    def get_tv_by_tmdb_id(self, tmdb_id: int) -> TMDBData:
        return self._request(f"tv/{tmdb_id}")

    def get_genres(self, media_type: str) -> list[TMDBData]:
        def fetch():
            endpoint = "genre/tv/list" if media_type == "tv" else "genre/movie/list"
            data = self._request(endpoint)
            _require(data, "genres", [])
            return data["genres"]

        return cache_genres(media_type, fetch)

    # ------------------------------------------------------------------ Trailers and images

    # Priority order for _select_trailer(): (video "type", "official" flag).
    # Checked top to bottom; the first (type, official) pair with a matching
    # YouTube video wins. "Clip" has no official/unofficial distinction in
    # the spec, so it's handled separately as the final fallback.
    _TRAILER_PRIORITY = (("Trailer", True), ("Trailer", False), ("Teaser", True), ("Teaser", False))

    @staticmethod
    def _select_trailer(videos: list[TMDBData]) -> TMDBData | None:
        """Pick the single most relevant YouTube video from a TMDB videos.results list.

        Priority: official Trailer > Trailer > official Teaser > Teaser > Clip.
        Returns None if nothing matches.
        """
        youtube_videos = [v for v in videos if v.get("site") == "YouTube"]

        for video_type, official in TMDBClient._TRAILER_PRIORITY:
            for video in youtube_videos:
                if video.get("type") == video_type and bool(video.get("official")) == official:
                    return video

        for video in youtube_videos:
            if video.get("type") == "Clip":
                return video

        return None

    @staticmethod
    def _select_backdrops(images: TMDBData | None, limit: int = BACKDROP_LIMIT) -> list[str]:
        """Return up to `limit` full-size URLs from a TMDB images.backdrops list."""
        backdrops = images.get("backdrops", []) if images else []
        return [
            _image_url(backdrop["file_path"], "w780") for backdrop in backdrops[:limit] if backdrop.get("file_path")
        ]

    @staticmethod
    def _select_posters(images: TMDBData | None, limit: int = POSTER_LIMIT) -> list[dict[str, str]]:
        """Return up to `limit` {thumb, full} URL pairs from a TMDB images.posters list."""
        posters = images.get("posters", []) if images else []
        return [
            {
                "thumb": _image_url(poster["file_path"], "w342"),
                "full": _image_url(poster["file_path"], "w780"),
            }
            for poster in posters[:limit]
            if poster.get("file_path")
        ]

    def get_list_with_trailers(self, endpoint: str, page: int, media_type: str, limit: int = 5) -> list[TMDBData]:
        # List endpoints (popular, trending, ...) don't include videos, so the
        # trailer comes from each item's (cached) detail request. Only the first
        # `limit` items (the home hero slides) get one.
        result = self.get_list(endpoint, page)["results"][:limit]
        return self.attach_trailers(result, media_type)

    def attach_trailers(self, items: list[TMDBData], media_type: str) -> list[TMDBData]:
        """Set item["trailer"] from get_details() for every item, fetched in parallel.

        One detail request per item is unavoidable here (list endpoints can't
        append videos), so callers keep `items` short; the detail responses are
        cached and shared with the detail page.
        """
        details = fetch_parallel({item["id"]: partial(self.get_details, item["id"], media_type) for item in items})
        for item in items:
            item["trailer"] = (details.get(item["id"]) or {}).get("trailer")
        return items

    # ------------------------------------------------------------------ Detail page

    @staticmethod
    def _empty_details() -> TMDBData:
        return {
            "cast": [],
            "crew": {},
            "trailer": None,
            "backdrops": [],
            "posters": [],
            "keywords": [],
            "recommendations": [],
            "certification": None,
            "language": None,
        }

    def get_details(self, tmdb_id: int, media_type: str) -> TMDBData:
        """Everything the detail page needs from TMDB in ONE request.

        movie/{id} or tv/{id} with append_to_response (see DETAIL_APPEND). The raw
        response is ~100-150KB (full crew, every image), so it is trimmed before
        caching: the top-level fields stay as TMDB sends them (title, tagline,
        runtime, status, belongs_to_collection, seasons, ...), the appended
        blocks are replaced by the short lists below.
        """
        append = DETAIL_APPEND.get(media_type)
        if append is None:
            return self._empty_details()

        def fetch():
            data = self._request(
                f"{media_type}/{tmdb_id}",
                {"language": "en", "append_to_response": append, "include_image_language": "en,null"},
            )
            _require(data, "id", self._empty_details())
            return self._shape_details(data, media_type)

        return cache_tmdb(f"movies:details:v1:{media_type}:{tmdb_id}", fetch, TTL_DETAIL)

    def _shape_details(self, data: TMDBData, media_type: str) -> TMDBData:
        """Replace the appended blocks of a detail response with the trimmed lists (mutates `data`)."""
        credits = data.pop("credits", None) or {}
        videos = (data.pop("videos", None) or {}).get("results", [])
        images = data.pop("images", None) or {}
        keywords = data.pop("keywords", None) or {}
        recommendations = (data.pop("recommendations", None) or {}).get("results", [])
        release_dates = (data.pop("release_dates", None) or {}).get("results", [])
        content_ratings = (data.pop("content_ratings", None) or {}).get("results", [])

        crew = self._extract_crew(credits, data.get("created_by", []), media_type)

        data.update(
            {
                "cast": [
                    {key: person.get(key) for key in CAST_FIELDS} for person in credits.get("cast", [])[:CAST_LIMIT]
                ],
                "crew": crew,
                "trailer": self._select_trailer(videos),
                "backdrops": self._select_backdrops(images),
                "posters": self._select_posters(images),
                "keywords": self._extract_keywords(keywords),
                "recommendations": self._type_items(
                    [r for r in recommendations if r.get("media_type", media_type) in CARD_MEDIA_TYPES][
                        :RECOMMENDATION_LIMIT
                    ]
                ),
                "certification": self._certification(media_type, release_dates, content_ratings),
                "language": self._language_name(data),
            }
        )
        return data

    @staticmethod
    def _extract_crew(credits: TMDBData, created_by: list[TMDBData], media_type: str) -> dict[str, list[str]]:
        """{role: [names]} for CREW_ROLES (deduplicated, TMDB order), plus "creator" for TV."""
        crew = {}
        for person in credits.get("crew", []):
            role = CREW_ROLES.get(person.get("job"))
            if role and person["name"] not in crew.setdefault(role, []):
                crew[role].append(person["name"])
        if media_type == "tv":
            crew["creator"] = [person["name"] for person in created_by]
        return crew

    @staticmethod
    def _extract_keywords(keywords: TMDBData) -> list[dict[str, Any]]:
        """First KEYWORD_LIMIT keywords as {id, name}."""
        # Movies list keywords under "keywords", TV under "results".
        keyword_list = keywords.get("keywords") or keywords.get("results") or []
        return [{"id": k["id"], "name": k["name"]} for k in keyword_list[:KEYWORD_LIMIT]]

    @staticmethod
    def _certification(
        media_type: str, release_dates: list[TMDBData], content_ratings: list[TMDBData], country: str = "US"
    ) -> str | None:
        """US age rating: release_dates (movies, theatrical release first) / content_ratings (TV)."""
        if media_type == "tv":
            return next(
                (r["rating"] for r in content_ratings if r.get("iso_3166_1") == country and r.get("rating")), None
            )
        for entry in release_dates:
            if entry.get("iso_3166_1") != country:
                continue
            dates = sorted(entry.get("release_dates", []), key=lambda d: d.get("type") != THEATRICAL_RELEASE)
            return next((d["certification"] for d in dates if d.get("certification")), None)
        return None

    @staticmethod
    def _language_name(data: TMDBData) -> str | None:
        code = data.get("original_language")
        for language in data.get("spoken_languages", []):
            if language.get("iso_639_1") == code:
                return language.get("english_name") or language.get("name")
        return code.upper() if code else None

    def get_season(self, tv_id: int, season_number: int) -> TMDBData | None:
        """tv/{id}/season/{n}, trimmed to what the Seasons tab shows (the raw one carries crew/guest stars)."""

        def fetch():
            data = self._request(f"tv/{tv_id}/season/{season_number}", {"language": "en"})
            _require(data, "episodes", None)
            episodes = [{key: episode.get(key) for key in EPISODE_FIELDS} for episode in data["episodes"]]
            return {
                "season_number": data.get("season_number"),
                "name": data.get("name"),
                "air_date": data.get("air_date"),
                "episodes": episodes,
            }

        return cache_tmdb(f"movies:season:v1:{tv_id}:{season_number}", fetch, TTL_DETAIL)

    def get_collection(self, collection_id: int) -> TMDBData | None:
        """collection/{id}: name + parts sorted by release date (unreleased parts last)."""

        def fetch():
            data = self._request(f"collection/{collection_id}", {"language": "en"})
            _require(data, "parts", None)
            parts = self._type_items(sorted(data["parts"], key=lambda p: p.get("release_date") or "9999"))
            return {
                "id": data["id"],
                "name": data.get("name"),
                "overview": data.get("overview"),
                "parts": [{key: part.get(key) for key in COLLECTION_PART_FIELDS} for part in parts],
            }

        return cache_tmdb(f"movies:collection:v1:{collection_id}", fetch, TTL_DETAIL)

    def get_keyword(self, keyword_id: int) -> TMDBData | None:
        """keyword/{id} -> {"id", "name"}; keyword/{id}/movies doesn't carry the name."""

        def fetch():
            data = self._request(f"keyword/{keyword_id}")
            _require(data, "name", None)
            return {"id": data["id"], "name": data["name"]}

        return cache_tmdb(f"movies:keyword:v1:{keyword_id}", fetch, TTL_DETAIL)

    # ------------------------------------------------------------------ Lists

    def get_keyword_movies(self, keyword_id: int, page: int = 1) -> TMDBData:
        return self.get_list(f"keyword/{keyword_id}/movies", page)

    def get_trending(self, media_type: str = "all", time_window: str = "day", page: int = 1) -> TMDBData:
        """trending/{media_type}/{time_window}: media_type all|movie|tv|person, time_window day|week."""
        if media_type not in TRENDING_MEDIA_TYPES or time_window not in TRENDING_WINDOWS:
            raise ValueError(f"Unsupported trending list: {media_type}/{time_window}")
        return self.get_list(f"trending/{media_type}/{time_window}", page)

    def get_person(self, page: int = 1) -> TMDBData:
        """Raw person/popular page (all departments, not cached); {} if TMDB fails."""
        return self._request("person/popular", {"page": page})

    def get_popular_actors(self, page: int = 1) -> dict[str, Any]:
        """One page of popular people filtered to actors, plus pagination for the template.

        total_pages is capped at POPULAR_ACTORS_MAX_PAGES and current_page is
        clamped into [1, total_pages] after the request; page_range is a
        `range` (template pagination), not JSON-serializable.
        """
        data = self.get_person(page)

        total_pages = min(data.get("total_pages", 1), POPULAR_ACTORS_MAX_PAGES)
        persons = data.get("results", [])
        page = max(1, min(page, total_pages))

        actors = [person for person in persons if person.get("known_for_department") == "Acting"]

        return {
            "actors": actors,
            "current_page": page,
            "total_pages": total_pages,
            "page_range": range(max(1, page - 3), min(total_pages + 1, page + 3)),
        }

    @staticmethod
    def _type_items(items: list[TMDBData]) -> list[TMDBData]:
        """Add card fields in place: poster_url, title/release_date unified across movie/TV, rating.

        Items without "media_type" are treated as movies.
        """
        for item in items:
            path = item.get("poster_path")
            item["poster_url"] = _image_url(path, "w500") if path else None

            media_type = item.get("media_type", "movie")
            item["title"] = item.get("title") if media_type == "movie" else item.get("name")
            item["release_date"] = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
            item["rating"] = item.get("vote_average")

        return items

    def get_list(self, endpoint: str, page: int = 1, ttl: int | None = None, **kwargs: Any) -> TMDBData:
        """A paginated TMDB list (category, discover, trending, keyword, ...), Redis-cached.

        kwargs are TMDB query filters. `max_page` caps the returned total_pages
        (default DEFAULT_LIST_MAX_PAGE) and is kept out of the cache key; note it
        is currently also passed through to TMDB, which ignores it. `ttl`
        overrides the TTL cache_data_movie() would pick. Results are deduplicated
        by id and normalized with _type_items().
        """

        # `fetch` is only ever invoked by cache_data_movie() below on a cache
        # miss, so its return value is exactly what ends up written to Redis.
        # Raising TMDBFetchError instead of returning on failure is what tells
        # _cache_aside() to hand the fallback straight back to the caller
        # without caching it (see redis_services.TMDBFetchError).
        def fetch():
            data = self._request(endpoint, {"language": "en", "page": page, **kwargs})

            max_page = kwargs.get("max_page", DEFAULT_LIST_MAX_PAGE)
            _require(data, "results", {"results": [], "page": page, "total_pages": 1, "total_results": 0})

            # TMDB can repeat the same item across discover pages when filters
            # overlap; drop duplicates by id before normalizing.
            results = self._type_items(_dedupe_by_id(data["results"]))

            return {
                "results": results,
                "page": data.get("page", page),
                "total_pages": min(data.get("total_pages", 1), max_page),
                "total_results": data.get("total_results", 0),
            }

        start = time.perf_counter()
        result = cache_data_movie(endpoint, page, fetch, ttl=ttl, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logging.debug(f"[get_list] {endpoint} page={page} total {elapsed_ms:.1f}ms")
        return result

    # ------------------------------------------------------------------ Search

    def search_movies(self, query: str) -> list[TMDBData]:
        """search/multi in every configured language: movies and TV only, first hit per id wins.

        Not cached here (the search view caches its own result). A failed
        request just contributes no results.
        """
        found = []
        for lang in self.languages:
            data = self._request("search/multi", {"query": query, "language": lang})
            found.extend(item for item in data.get("results", []) if item.get("media_type") in CARD_MEDIA_TYPES)

        return self._type_items(_dedupe_by_id(found))

    def suggest(self, query: str, limit: int = 6) -> list[TMDBData]:
        # Header search dropdown: one search/multi call, movies + TV only. Unlike
        # search_movies(), a failed TMDB call raises so the UI can show an error
        # instead of "No results found".
        data = self._request("search/multi", {"query": query, "language": self.languages[0]})
        _require(data, "results", [])
        items = [i for i in data["results"] if i.get("media_type") in CARD_MEDIA_TYPES]
        return self._type_items(items[:limit])

    # ------------------------------------------------------------------ Card helpers

    @staticmethod
    def get_release_date(details: TMDBData, media_type: str) -> str | None:
        """release_date (movie) / first_air_date (TV) as "dd.mm.YYYY".

        None if the date is missing or empty; ValueError if it isn't YYYY-MM-DD.
        """
        raw_date = details.get("release_date") if media_type == "movie" else details.get("first_air_date")

        if not raw_date:
            return None

        try:
            date_obj = datetime.strptime(raw_date, "%Y-%m-%d")
            return date_obj.strftime("%d.%m.%Y")
        except (TypeError, ValueError) as err:
            raise ValueError("Unknown") from err

    def _enrichment_fetcher(self, tmdb_id: int, media_type: str) -> Callable[[], TMDBData]:
        # Same TMDBFetchError pattern as get_list(): only the enrichment
        # fields get cached (per tmdb_id, not per list/page), so every
        # category page sharing an item reuses the same cache entry.
        def fetch():
            details = self.get_movie_by_tmdb_id(tmdb_id) if media_type == "movie" else self.get_tv_by_tmdb_id(tmdb_id)
            if not details:
                raise TMDBFetchError(
                    {
                        "tmdb_id": tmdb_id,
                        "release_date": None,
                        "tmdb_rating": None,
                        "original_language": None,
                        "country": None,
                        "genres": [],
                        "media_type": media_type,
                    }
                )
            return {
                "tmdb_id": tmdb_id,
                "release_date": self.get_release_date(details, media_type),
                "tmdb_rating": details.get("vote_average"),
                "original_language": details.get("original_language"),
                "country": details.get("origin_country") if media_type == "tv" else details.get("production_countries"),
                "genres": [genre["name"] for genre in details.get("genres", [])],
                "media_type": media_type,
            }

        return fetch

    def enrich_item(self, item: TMDBData, media_type: str) -> TMDBData:
        tmdb_id = item["id"]
        enrichment = cache_item_detail("item", media_type, tmdb_id, self._enrichment_fetcher(tmdb_id, media_type))
        item.update(enrichment)
        return item

    def enrich_items(self, items: list[TMDBData], media_type: str) -> list[TMDBData]:
        # Batched: one Redis MGET for every item's cache key up front, then
        # one pipelined write for whatever missed - see cache_items_detail()
        # for why this matters a lot more against a hosted Redis than a
        # local one.
        #
        # Superseded by annotate_items() for category/type pages (AllMoviesView):
        # every field this produces (except `country`) is already present in
        # the TMDB list response, so annotate_items() derives them locally
        # instead of firing one detail request per item. Kept here, unused,
        # only for a caller that genuinely needs `country` (none currently do).
        lookups = [(item["id"], self._enrichment_fetcher(item["id"], media_type)) for item in items]
        enrichment_by_id = cache_items_detail("item", media_type, lookups)

        for item in items:
            item.update(enrichment_by_id[item["id"]])
        return items

    def annotate_items(self, items: list[TMDBData], media_type: str, genres: list[TMDBData]) -> list[TMDBData]:
        """Derive card-display fields for a list of items from data the list
        response already carries, plus an already-fetched genre list. Makes
        zero TMDB calls - unlike enrich_items(), which fetches full detail
        per item for the same fields.

        Does NOT set `country`: category/type-page cards never render it
        (only the detail page does, from the local Movies row). A caller
        that needs `country` should use enrich_item/enrich_items instead.
        """
        genre_by_id = {genre["id"]: genre["name"] for genre in genres}

        for item in items:
            item["tmdb_id"] = item["id"]
            item["media_type"] = media_type
            item["tmdb_rating"] = item.get("vote_average")
            try:
                item["release_date"] = self.get_release_date(item, media_type)
            except ValueError:
                item["release_date"] = None
            item["genres"] = [genre_by_id[gid] for gid in item.get("genre_ids", []) if gid in genre_by_id]

        return items
