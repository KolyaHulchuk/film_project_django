import os
import json
import logging
import time

import redis

logger = logging.getLogger(__name__)

r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)


class TMDBFetchError(Exception):
    """Raised by a fetch_function to signal TMDB failed to return real data.

    Carries the fallback value that should be handed back to the caller
    without ever being written to the cache.
    """

    def __init__(self, fallback):
        self.fallback = fallback
        super().__init__("TMDB fetch failed")


def _cache_aside(cache_key, fetch_function, ttl):
    lookup_start = time.perf_counter()
    cached = None
    try:
        cached = r.get(cache_key)
    except redis.exceptions.RedisError:
        logger.warning("Redis unavailable, skipping cache lookup for %s", cache_key)
    lookup_ms = (time.perf_counter() - lookup_start) * 1000
    logger.debug("[cache] GET %s -> %s in %.1fms", cache_key, "HIT" if cached is not None else "MISS", lookup_ms)

    if cached is not None:
        return json.loads(cached)

    fetch_start = time.perf_counter()
    try:
        result = fetch_function()
    except TMDBFetchError as exc:
        fetch_ms = (time.perf_counter() - fetch_start) * 1000
        logger.debug("[cache] TMDB fallback for %s FAILED after %.1fms", cache_key, fetch_ms)
        return exc.fallback
    fetch_ms = (time.perf_counter() - fetch_start) * 1000
    logger.debug("[cache] TMDB fetch for %s took %.1fms", cache_key, fetch_ms)

    try:
        r.set(cache_key, json.dumps(result), ex=ttl)
    except redis.exceptions.RedisError:
        logger.warning("Redis unavailable, skipping cache store for %s", cache_key)

    return result


def cache_data_movie(endpoint, page, fetch_function, **kwargs):
    cache_kwargs = {k: v for k, v in kwargs.items() if k != "max_page"}
    params_str = "&".join(f"{k}={v}" for k, v in sorted(cache_kwargs.items()))
    cache_key = f"movies:list:v1:{endpoint}:{page}:{params_str}"
    return _cache_aside(cache_key, fetch_function, ttl=900)


def cache_item_detail(kind, media_type, tmdb_id, fetch_function):
    cache_key = f"movies:{kind}:v1:{media_type}:{tmdb_id}"
    return _cache_aside(cache_key, fetch_function, ttl=21600)


def cache_genres(media_type, fetch_function):
    cache_key = f"movies:genres:v1:{media_type}"
    # TTL is much longer than even cache_item_detail's: TMDB's genre list is
    # effectively static, unlike per-item ratings/details.
    return _cache_aside(cache_key, fetch_function, ttl=86400)
