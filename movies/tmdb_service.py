import logging
import time
from datetime import datetime

import requests
from django.conf import settings

from .redis_services import TMDBFetchError, cache_data_movie, cache_genres, cache_item_detail


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

    def get_credit(self, tmdb_id, media_type):
        def fetch():
            data = self._request(f"{media_type}/{tmdb_id}/credits")
            if not data:
                raise TMDBFetchError({"cast": [], "crew": []})
            return data

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

        try:
            date_obj = datetime.strptime(raw_date, "%Y-%m-%d")
            return date_obj.strftime("%d.%m.%Y")
        except (TypeError, ValueError) as err:
            raise ValueError("Uknown") from err

    def enrich_item(self, item, media_type):
        tmdb_id = item["id"]

        # Same cache-aside/TMDBFetchError pattern as get_list(): only the
        # enrichment fields get cached (per tmdb_id, not per list/page), so
        # every category page sharing an item reuses the same cache entry.
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

        enrichment = cache_item_detail("item", media_type, tmdb_id, fetch)
        item.update(enrichment)
        return item

    def enrich_items(self, items, media_type):
        return [self.enrich_item(item, media_type) for item in items]
