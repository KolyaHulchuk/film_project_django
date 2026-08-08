import os
import json
import logging

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


def cache_data_movie(endpoint, page, fetch_function, **kwargs):
    cache_kwargs = {k: v for k, v in kwargs.items() if k != "max_page"}
    params_str = "&".join(f"{k}={v}" for k, v in sorted(cache_kwargs.items()))
    cache_key = f"movies:list:v1:{endpoint}:{page}:{params_str}"

    try:
        cached = r.get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except redis.exceptions.RedisError:
        logger.warning("Redis unavailable, skipping cache lookup for %s", cache_key)

    try:
        result = fetch_function()
    except TMDBFetchError as exc:
        return exc.fallback

    try:
        r.set(cache_key, json.dumps(result), ex=900)
    except redis.exceptions.RedisError:
        logger.warning("Redis unavailable, skipping cache store for %s", cache_key)

    return result
