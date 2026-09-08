import json
import logging
import os
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
    except redis.exceptions.RedisError as exc:
        logger.warning("Redis unavailable, skipping cache lookup for %s: %r", cache_key, exc)
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
    except redis.exceptions.RedisError as exc:
        logger.warning("Redis unavailable, skipping cache store for %s: %r", cache_key, exc)

    return result


def cache_data_movie(endpoint, page, fetch_function, **kwargs):
    cache_kwargs = {k: v for k, v in kwargs.items() if k != "max_page"}
    params_str = "&".join(f"{k}={v}" for k, v in sorted(cache_kwargs.items()))
    cache_key = f"movies:list:v1:{endpoint}:{page}:{params_str}"
    return _cache_aside(cache_key, fetch_function, ttl=900)


def cache_item_detail(kind, media_type, tmdb_id, fetch_function):
    cache_key = f"movies:{kind}:v1:{media_type}:{tmdb_id}"
    return _cache_aside(cache_key, fetch_function, ttl=21600)


def cache_items_detail(kind, media_type, items):
    """Batched sibling of cache_item_detail() for enrich_items().

    items: list of (tmdb_id, fetch_function) pairs. Returns a dict
    tmdb_id -> result, in the same shape cache_item_detail() would return
    per item.

    Instead of one GET/SET round trip per item, this does a single MGET for
    every key up front, then - for whatever misses - fetches from TMDB
    (still one call per miss, that part isn't Redis) and writes all of the
    fresh results back with a single pipelined round trip. On a page of N
    items this turns ~N sequential Redis round trips into ~1-2, which is
    what actually matters when Redis is a hosted service reached over the
    network (e.g. Upstash from Render) rather than a container on the same
    docker network.
    """
    if not items:
        return {}

    ttl = 21600
    cache_keys = [f"movies:{kind}:v1:{media_type}:{tmdb_id}" for tmdb_id, _ in items]

    lookup_start = time.perf_counter()
    try:
        cached_values = r.mget(cache_keys)
    except redis.exceptions.RedisError as exc:
        logger.warning("Redis unavailable, skipping batch cache lookup for %d items: %r", len(items), exc)
        cached_values = [None] * len(items)
    lookup_ms = (time.perf_counter() - lookup_start) * 1000
    hits = sum(1 for v in cached_values if v is not None)
    logger.debug("[cache] MGET %d keys -> %d hits in %.1fms", len(cache_keys), hits, lookup_ms)

    results = {}
    to_write = {}

    for (tmdb_id, fetch_function), cache_key, cached in zip(items, cache_keys, cached_values, strict=True):
        if cached is not None:
            results[tmdb_id] = json.loads(cached)
            continue

        try:
            result = fetch_function()
        except TMDBFetchError as exc:
            results[tmdb_id] = exc.fallback
            continue

        results[tmdb_id] = result
        to_write[cache_key] = result

    if to_write:
        write_start = time.perf_counter()
        try:
            # pipe.set() only queues the command locally; nothing goes over
            # the network until execute() sends every queued SET as one
            # batch and reads back all the replies in a single round trip.
            pipe = r.pipeline()
            for cache_key, result in to_write.items():
                pipe.set(cache_key, json.dumps(result), ex=ttl)
            pipe.execute()
        except redis.exceptions.RedisError as exc:
            logger.warning("Redis unavailable, skipping batch cache store for %d items: %r", len(to_write), exc)
        write_ms = (time.perf_counter() - write_start) * 1000
        logger.debug("[cache] pipelined SET %d keys in %.1fms", len(to_write), write_ms)

    return results


def cache_genres(media_type, fetch_function):
    cache_key = f"movies:genres:v1:{media_type}"
    # TTL is much longer than even cache_item_detail's: TMDB's genre list is
    # effectively static, unlike per-item ratings/details.
    return _cache_aside(cache_key, fetch_function, ttl=86400)
