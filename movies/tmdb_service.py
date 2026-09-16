import logging
import time
from datetime import datetime

import requests
from django.conf import settings

from .redis_services import TMDBFetchError, cache_data_movie, cache_genres, cache_item_detail, cache_items_detail


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

    def __init__(self, api_key=None, languages=None):
        self.api_key = api_key or settings.TMDB_API_KEY
        self.languages = languages or ["en"]

    def _request(self, endpoint, params=None):
        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {}
        params["api_key"] = self.api_key
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            logging.warning(f"TMDB API error {response.status_code} for endpoint '{endpoint}")
        # Empty dict on failure, not an exception: callers (get_list/enrich_item/etc.)
        # check for missing keys and raise TMDBFetchError themselves, which is what
        # keeps a failed TMDB call from ever being written to the Redis cache.
        return {}

    def get_movie_by_tmdb_id(self, tmdb_id):
        return self._request(f"movie/{tmdb_id}")

    def get_tv_by_tmdb_id(self, tmdb_id):
        return self._request(f"tv/{tmdb_id}")

    def get_discover_tv(self, **kwargs):
        return self._request("discover/tv", **kwargs)

    def get_discover_movie(self, **kwargs):
        return self._request("discover/movie", **kwargs)

    def get_genres(self, media_type):
        def fetch():
            endpoint = "genre/tv/list" if media_type == "tv" else "genre/movie/list"
            data = self._request(endpoint)
            if not data or "genres" not in data:
                raise TMDBFetchError([])
            return data["genres"]

        return cache_genres(media_type, fetch)

    # Priority order for _select_trailer(): (video "type", "official" flag).
    # Checked top to bottom; the first (type, official) pair with a matching
    # YouTube video wins. "Clip" has no official/unofficial distinction in
    # the spec, so it's handled separately as the final fallback.
    _TRAILER_PRIORITY = (("Trailer", True), ("Trailer", False), ("Teaser", True), ("Teaser", False))

    @staticmethod
    def _select_trailer(videos):
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
    def _select_backdrops(images, limit=6):
        """Return up to `limit` full-size URLs from a TMDB images.backdrops list."""
        backdrops = images.get("backdrops", []) if images else []
        return [
            f"https://image.tmdb.org/t/p/w780{backdrop['file_path']}"
            for backdrop in backdrops[:limit]
            if backdrop.get("file_path")
        ]

    def get_credit(self, tmdb_id, media_type):
        # append_to_response bundles videos/images into the same request this
        # view already makes for cast/crew, instead of adding extra TMDB calls
        # just to look up the trailer and gallery backdrops.
        def fetch():
            data = self._request(
                f"{media_type}/{tmdb_id}",
                {"append_to_response": "credits,videos,images", "include_image_language": "en,null"},
            )
            if not data:
                raise TMDBFetchError({"cast": [], "crew": [], "trailer": None, "backdrops": []})

            credits = data.get("credits", {})
            videos = data.get("videos", {}).get("results", [])
            images = data.get("images", {})

            return {
                "cast": credits.get("cast", []),
                "crew": credits.get("crew", []),
                "trailer": self._select_trailer(videos),
                "backdrops": self._select_backdrops(images),
            }

        return cache_item_detail("credits", media_type, tmdb_id, fetch)

    def get_person(self, page=1):
        return self._request("person/popular", {"page": page})

    def get_popular_actors(self, page=1):
        data = self.get_person(page)

        total_pages = min(data.get("total_pages", 1), 50)
        persons = data.get("results", [])
        page = max(1, min(page, total_pages))

        actors = []
        for person in persons:
            if person.get("known_for_department") == "Acting":
                actors.append(person)

        return {
            "actors": actors,
            "current_page": page,
            "total_pages": total_pages,
            "page_range": range(max(1, page - 3), min(total_pages + 1, page + 3)),
        }

    def _type_items(self, items):
        for item in items:
            path = item.get("poster_path")
            item["poster_url"] = f"https://image.tmdb.org/t/p/w500{path}" if path else None

            media_type = item.get("media_type", "movie")
            item["title"] = item.get("title") if media_type == "movie" else item.get("name")
            item["release_date"] = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
            item["rating"] = item.get("vote_average")

        return items

    def get_list(self, endpoint, page=1, **kwargs):
        # `fetch` is only ever invoked by cache_data_movie() below on a cache
        # miss, so its return value is exactly what ends up written to Redis.
        # Raising TMDBFetchError instead of returning on failure is what tells
        # _cache_aside() to hand the fallback straight back to the caller
        # without caching it (see redis_services.TMDBFetchError).
        def fetch():
            data = self._request(endpoint, {"language": "en", "page": page, **kwargs})

            max_page = kwargs.get("max_page", 10)
            if not data or "results" not in data:
                raise TMDBFetchError({"results": [], "page": page, "total_pages": 1})

            # TMDB can repeat the same item across discover pages when filters
            # overlap; drop duplicates by id before normalizing.
            uniq_results = []
            seen_id = set()

            for result in data["results"]:
                if result["id"] not in seen_id:
                    seen_id.add(result["id"])
                    uniq_results.append(result)

            uniq_results = self._type_items(uniq_results)

            return {
                "results": uniq_results,
                "page": data.get("page", page),
                "total_pages": min(data.get("total_pages", 1), max_page),
            }

        start = time.perf_counter()
        result = cache_data_movie(endpoint, page, fetch, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logging.debug(f"[get_list] {endpoint} page={page} total {elapsed_ms:.1f}ms")
        return result

    def search_movies(self, query):
        seen_ids = set()
        combined = []

        for lang in self.languages:
            data = self._request("search/multi", {"query": query, "language": lang})

            for item in data.get("results", []):
                media_type = item.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue
                if item["id"] not in seen_ids:
                    combined.append(item)
                    seen_ids.add(item["id"])

        return self._type_items(combined)

    @staticmethod
    def get_release_date(details, media_type):
        raw_date = details.get("release_date") if media_type == "movie" else details.get("first_air_date")

        if not raw_date:
            return None

        try:
            date_obj = datetime.strptime(raw_date, "%Y-%m-%d")
            return date_obj.strftime("%d.%m.%Y")
        except (TypeError, ValueError) as err:
            raise ValueError("Uknown") from err

    def _enrichment_fetcher(self, tmdb_id, media_type):
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

    def enrich_item(self, item, media_type):
        tmdb_id = item["id"]
        enrichment = cache_item_detail("item", media_type, tmdb_id, self._enrichment_fetcher(tmdb_id, media_type))
        item.update(enrichment)
        return item

    def enrich_items(self, items, media_type):
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

    def annotate_items(self, items, media_type, genres):
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
