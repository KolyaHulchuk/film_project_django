"""Characterization tests for movies/redis_services.py.

They pin down the CURRENT behavior (cache keys, TTLs, serialization, hit/miss
paths, TMDBFetchError fallbacks, swallowed cache errors) so a refactor of the
module can be checked against it. Nothing here asserts what the behavior
*should* be; a few tests pin oddities on purpose and say so.

The autouse `isolated_cache` fixture (movies/tests/conftest.py) swaps Django's
cache for locmem and `redis_services.r` for an in-memory FakeRedis, which it
returns: tests request it by name to inspect `store` / `ttls`.
"""

import json
import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from movies import redis_services
from movies.redis_services import (
    LONG_TTL_LIST_ENDPOINTS,
    TTL_DETAIL,
    TTL_GENRES,
    TTL_LIST,
    TTL_LIST_DEFAULT,
    TMDBFetchError,
    _cache_aside,
    cache_data_movie,
    cache_genres,
    cache_item_detail,
    cache_items_detail,
    cache_search_results,
    cache_tmdb,
)


class CountingFetch:
    """fetch_function stand-in: returns `value` (or raises it if it's an exception) and counts calls."""

    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


def broken_pipeline(error_on):
    """A pipeline() replacement whose set() or execute() raises RedisError."""

    class BrokenPipeline:
        def set(self, key, value, ex=None):
            if error_on == "set":
                raise RedisError("pipeline set failed")
            return self

        def execute(self):
            raise RedisError("pipeline execute failed")

    return BrokenPipeline


# --------------------------------------------------------------------------- constants


def test_ttl_constants():
    assert TTL_LIST_DEFAULT == 900
    assert TTL_LIST == 43200
    assert TTL_DETAIL == 86400
    assert TTL_GENRES == 129600


def test_long_ttl_list_endpoints():
    assert LONG_TTL_LIST_ENDPOINTS == (
        "trending/",
        "movie/upcoming",
        "movie/top_rated",
        "movie/popular",
        "movie/now_playing",
        "tv/popular",
        "tv/top_rated",
        "tv/airing_today",
        "tv/on_the_air",
        "keyword/",
    )
    # A tuple, so it can be passed straight to str.startswith().
    assert isinstance(LONG_TTL_LIST_ENDPOINTS, tuple)


def test_tmdb_fetch_error_carries_fallback():
    fallback = {"results": []}
    exc = TMDBFetchError(fallback)

    assert isinstance(exc, Exception)
    assert exc.fallback is fallback
    assert str(exc) == "TMDB fetch failed"
    assert exc.args == ("TMDB fetch failed",)


# --------------------------------------------------------------------------- _cache_aside


def test_cache_aside_miss_fetches_stores_json_with_ttl(isolated_cache):
    fetch = CountingFetch({"a": 1, "b": [1, 2]})

    result = _cache_aside("k", fetch, ttl=123)

    assert result == {"a": 1, "b": [1, 2]}
    assert fetch.calls == 1
    assert isolated_cache.store["k"] == json.dumps({"a": 1, "b": [1, 2]})
    assert isolated_cache.ttls["k"] == 123


def test_cache_aside_miss_returns_fetch_result_object_itself(isolated_cache):
    value = {"a": (1, 2)}

    result = _cache_aside("k", CountingFetch(value), ttl=1)

    # On a miss the caller gets the very object fetch returned (tuples intact),
    # not a JSON round-tripped copy.
    assert result is value


def test_cache_aside_hit_returns_decoded_json_without_fetching(isolated_cache):
    isolated_cache.store["k"] = json.dumps({"cached": True})
    fetch = CountingFetch({"cached": False})

    assert _cache_aside("k", fetch, ttl=1) == {"cached": True}
    assert fetch.calls == 0


def test_cache_aside_json_round_trip_turns_tuples_into_lists(isolated_cache):
    _cache_aside("k", CountingFetch({"pairs": [(1, "movie")], 1: "int key"}), ttl=1)

    second = _cache_aside("k", CountingFetch("unused"), ttl=1)

    # JSON: tuples come back as lists, int dict keys come back as strings.
    assert second == {"pairs": [[1, "movie"]], "1": "int key"}


def test_cache_aside_none_result_is_cached_and_served_as_hit(isolated_cache):
    # json.dumps(None) == "null" is a non-None string, so a None result is a
    # real cache entry: the next call is a HIT that returns None without fetching.
    _cache_aside("k", CountingFetch(None), ttl=1)
    assert isolated_cache.store["k"] == "null"

    fetch = CountingFetch("fresh")
    assert _cache_aside("k", fetch, ttl=1) is None
    assert fetch.calls == 0


@pytest.mark.parametrize("value", [[], {}, 0, "", False])
def test_cache_aside_falsy_results_are_cached(isolated_cache, value):
    _cache_aside("k", CountingFetch(value), ttl=1)

    fetch = CountingFetch("fresh")
    assert _cache_aside("k", fetch, ttl=1) == value
    assert fetch.calls == 0


def test_cache_aside_tmdb_fetch_error_returns_fallback_and_stores_nothing(isolated_cache):
    fallback = {"results": [], "page": 1}

    result = _cache_aside("k", CountingFetch(TMDBFetchError(fallback)), ttl=1)

    assert result is fallback
    assert isolated_cache.store == {}
    assert isolated_cache.ttls == {}


def test_cache_aside_fallback_is_not_cached_so_next_call_fetches_again(isolated_cache):
    _cache_aside("k", CountingFetch(TMDBFetchError([])), ttl=1)

    fetch = CountingFetch(["real"])
    assert _cache_aside("k", fetch, ttl=1) == ["real"]
    assert fetch.calls == 1
    assert json.loads(isolated_cache.store["k"]) == ["real"]


def test_cache_aside_other_fetch_exceptions_propagate(isolated_cache):
    with pytest.raises(ValueError, match="boom"):
        _cache_aside("k", CountingFetch(ValueError("boom")), ttl=1)
    assert isolated_cache.store == {}


@pytest.mark.parametrize("error", [RedisError("down"), RedisConnectionError("refused")])
def test_cache_aside_redis_get_error_is_swallowed_and_falls_back_to_fetch(isolated_cache, mocker, error):
    mocker.patch.object(isolated_cache, "get", side_effect=error)
    fetch = CountingFetch({"fresh": 1})

    assert _cache_aside("k", fetch, ttl=5) == {"fresh": 1}
    assert fetch.calls == 1
    # The store is still attempted after a failed lookup.
    assert isolated_cache.ttls["k"] == 5


def test_cache_aside_redis_set_error_is_swallowed_and_returns_result(isolated_cache, mocker):
    mocker.patch.object(isolated_cache, "set", side_effect=RedisError("down"))

    assert _cache_aside("k", CountingFetch({"fresh": 1}), ttl=5) == {"fresh": 1}
    assert isolated_cache.store == {}


def test_cache_aside_non_redis_get_error_propagates(isolated_cache, mocker):
    # Only redis.exceptions.RedisError is swallowed on the raw-client path.
    mocker.patch.object(isolated_cache, "get", side_effect=RuntimeError("not redis"))

    with pytest.raises(RuntimeError, match="not redis"):
        _cache_aside("k", CountingFetch("x"), ttl=1)


def test_cache_aside_corrupt_cached_value_raises(isolated_cache):
    isolated_cache.store["k"] = "not json{"

    with pytest.raises(json.JSONDecodeError):
        _cache_aside("k", CountingFetch("x"), ttl=1)


def test_cache_aside_unserializable_result_raises_type_error(isolated_cache):
    with pytest.raises(TypeError):
        _cache_aside("k", CountingFetch({"s": {1, 2}}), ttl=1)
    assert isolated_cache.store == {}


def test_cache_aside_redis_errors_log_warnings(isolated_cache, mocker, caplog):
    get_error, set_error = RedisError("get down"), RedisError("set down")
    mocker.patch.object(isolated_cache, "get", side_effect=get_error)
    mocker.patch.object(isolated_cache, "set", side_effect=set_error)

    with caplog.at_level(logging.WARNING, logger="movies.redis_services"):
        _cache_aside("k", CountingFetch("x"), ttl=1)

    # %r of the exception; redis-py's own repr decides the text (in 8.x it is
    # "server:RedisError", without the message).
    warnings = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING]
    assert warnings == [
        f"Redis unavailable, skipping cache lookup for k: {get_error!r}",
        f"Redis unavailable, skipping cache store for k: {set_error!r}",
    ]


# --------------------------------------------------------------------------- cache_data_movie


def test_cache_data_movie_key_without_kwargs(isolated_cache):
    cache_data_movie("movie/popular", 1, CountingFetch({"results": []}))

    assert list(isolated_cache.store) == ["movies:list:v2:movie/popular:1:"]


def test_cache_data_movie_key_sorts_kwargs(isolated_cache):
    cache_data_movie("discover/movie", 3, CountingFetch({}), with_genres="28", sort_by="popularity.desc", year=2020)

    assert list(isolated_cache.store) == [
        "movies:list:v2:discover/movie:3:sort_by=popularity.desc&with_genres=28&year=2020"
    ]


def test_cache_data_movie_kwarg_order_does_not_change_key(isolated_cache):
    cache_data_movie("discover/tv", 1, CountingFetch({"first": 1}), b="2", a="1")
    fetch = CountingFetch({"second": 1})

    result = cache_data_movie("discover/tv", 1, fetch, a="1", b="2")

    assert result == {"first": 1}
    assert fetch.calls == 0
    assert list(isolated_cache.store) == ["movies:list:v2:discover/tv:1:a=1&b=2"]


def test_cache_data_movie_kwarg_values_are_formatted_with_str(isolated_cache):
    # No URL-encoding or filtering of None: values go through f-string str().
    cache_data_movie("discover/movie", 1, CountingFetch({}), a=None, b=[1, 2], c=1.5, d="x y")

    assert list(isolated_cache.store) == ["movies:list:v2:discover/movie:1:a=None&b=[1, 2]&c=1.5&d=x y"]


def test_cache_data_movie_excludes_max_page_from_key(isolated_cache):
    cache_data_movie("discover/movie", 2, CountingFetch({"v": 1}), max_page=50, with_genres="18")
    fetch = CountingFetch({"v": 2})

    # Same key with a different (or no) max_page -> hit.
    assert cache_data_movie("discover/movie", 2, fetch, max_page=5, with_genres="18") == {"v": 1}
    assert cache_data_movie("discover/movie", 2, fetch, with_genres="18") == {"v": 1}
    assert fetch.calls == 0
    assert list(isolated_cache.store) == ["movies:list:v2:discover/movie:2:with_genres=18"]


def test_cache_data_movie_only_max_page_gives_empty_params(isolated_cache):
    cache_data_movie("movie/popular", 1, CountingFetch({}), max_page=10)

    assert list(isolated_cache.store) == ["movies:list:v2:movie/popular:1:"]


def test_cache_data_movie_page_is_part_of_key(isolated_cache):
    cache_data_movie("movie/popular", 1, CountingFetch({"p": 1}))
    cache_data_movie("movie/popular", 2, CountingFetch({"p": 2}))

    assert sorted(isolated_cache.store) == ["movies:list:v2:movie/popular:1:", "movies:list:v2:movie/popular:2:"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "trending/all/week",
        "trending/movie/day",
        "movie/upcoming",
        "movie/top_rated",
        "movie/popular",
        "movie/now_playing",
        "tv/popular",
        "tv/top_rated",
        "tv/airing_today",
        "tv/on_the_air",
        "keyword/9715/movies",
    ],
)
def test_cache_data_movie_long_ttl_for_curated_endpoints(isolated_cache, endpoint):
    cache_data_movie(endpoint, 1, CountingFetch({}))

    assert isolated_cache.ttls[f"movies:list:v2:{endpoint}:1:"] == TTL_LIST == 43200


@pytest.mark.parametrize(
    "endpoint",
    ["discover/movie", "discover/tv", "search/multi", "person/popular", "movie/550/similar", "trending"],
)
def test_cache_data_movie_short_ttl_for_other_endpoints(isolated_cache, endpoint):
    cache_data_movie(endpoint, 1, CountingFetch({}))

    assert isolated_cache.ttls[f"movies:list:v2:{endpoint}:1:"] == TTL_LIST_DEFAULT == 900


def test_cache_data_movie_long_ttl_match_is_a_plain_prefix(isolated_cache):
    # str.startswith(): anything that merely begins with a listed prefix matches.
    cache_data_movie("movie/popularity", 1, CountingFetch({}))

    assert isolated_cache.ttls["movies:list:v2:movie/popularity:1:"] == TTL_LIST


def test_cache_data_movie_explicit_ttl_overrides_both_defaults(isolated_cache):
    cache_data_movie("discover/movie", 1, CountingFetch({}), ttl=TTL_LIST, with_genres="1")
    cache_data_movie("movie/popular", 1, CountingFetch({}), ttl=60)

    assert isolated_cache.ttls["movies:list:v2:discover/movie:1:with_genres=1"] == TTL_LIST
    assert isolated_cache.ttls["movies:list:v2:movie/popular:1:"] == 60


def test_cache_data_movie_ttl_is_not_part_of_key(isolated_cache):
    cache_data_movie("discover/movie", 1, CountingFetch({"v": 1}), ttl=60)
    fetch = CountingFetch({"v": 2})

    assert cache_data_movie("discover/movie", 1, fetch) == {"v": 1}
    assert fetch.calls == 0
    assert list(isolated_cache.store) == ["movies:list:v2:discover/movie:1:"]


def test_cache_data_movie_explicit_zero_ttl_is_passed_through(isolated_cache):
    # Only `ttl is None` picks a default; 0 is forwarded to Redis as-is.
    cache_data_movie("discover/movie", 1, CountingFetch({}), ttl=0)

    assert isolated_cache.ttls["movies:list:v2:discover/movie:1:"] == 0


def test_cache_data_movie_delegates_to_cache_aside(mocker):
    spy = mocker.patch("movies.redis_services._cache_aside", return_value="sentinel")
    fetch = CountingFetch({})

    assert cache_data_movie("movie/popular", 4, fetch, max_page=3, b=2, a=1) == "sentinel"
    spy.assert_called_once_with("movies:list:v2:movie/popular:4:a=1&b=2", fetch, ttl=TTL_LIST)


def test_cache_data_movie_fallback_not_cached(isolated_cache):
    fallback = {"results": [], "page": 1, "total_pages": 1, "total_results": 0}

    assert cache_data_movie("movie/popular", 1, CountingFetch(TMDBFetchError(fallback))) is fallback
    assert isolated_cache.store == {}


# --------------------------------------------------------------------------- cache_tmdb (Django cache)


def test_cache_tmdb_miss_fetches_and_stores_in_django_cache(isolated_cache):
    from django.core.cache import cache

    fetch = CountingFetch({"id": 1})

    assert cache_tmdb("movies:details:v1:movie:1", fetch, TTL_DETAIL) == {"id": 1}
    assert fetch.calls == 1
    assert cache.get("movies:details:v1:movie:1") == {"id": 1}
    # The raw redis client is never touched by cache_tmdb.
    assert isolated_cache.store == {}


def test_cache_tmdb_hit_does_not_fetch():
    from django.core.cache import cache

    cache.set("key", {"cached": True}, 60)
    fetch = CountingFetch({"cached": False})

    assert cache_tmdb("key", fetch, 60) == {"cached": True}
    assert fetch.calls == 0


def test_cache_tmdb_passes_key_value_ttl_positionally(mocker):
    fake_cache = mocker.patch("movies.redis_services.cache")
    fake_cache.get.return_value = None

    cache_tmdb("key", CountingFetch({"v": 1}), 777)

    fake_cache.get.assert_called_once_with("key")
    fake_cache.set.assert_called_once_with("key", {"v": 1}, 777)


def test_cache_tmdb_keeps_python_types_on_hit():
    # Django's cache pickles, so unlike the raw JSON path tuples survive a hit.
    cache_tmdb("key", CountingFetch({"pair": (1, "movie"), 1: "int key"}), 60)

    assert cache_tmdb("key", CountingFetch("unused"), 60) == {"pair": (1, "movie"), 1: "int key"}


def test_cache_tmdb_none_result_is_refetched_every_time():
    # A stored None is indistinguishable from a miss (cache.get returns None),
    # so None results are effectively never cached - unlike _cache_aside.
    first = CountingFetch(None)
    cache_tmdb("key", first, 60)
    second = CountingFetch(None)
    cache_tmdb("key", second, 60)

    assert first.calls == 1
    assert second.calls == 1


@pytest.mark.parametrize("value", [[], {}, 0, ""])
def test_cache_tmdb_falsy_non_none_results_are_cached(value):
    cache_tmdb("key", CountingFetch(value), 60)
    fetch = CountingFetch("fresh")

    assert cache_tmdb("key", fetch, 60) == value
    assert fetch.calls == 0


def test_cache_tmdb_tmdb_fetch_error_returns_fallback_and_stores_nothing():
    from django.core.cache import cache

    fallback = {}

    assert cache_tmdb("key", CountingFetch(TMDBFetchError(fallback)), 60) is fallback
    assert cache.get("key", "absent") == "absent"


@pytest.mark.parametrize("error", [Exception("generic"), RedisError("down"), RuntimeError("x")])
def test_cache_tmdb_swallows_any_exception_on_get(mocker, error):
    fake_cache = mocker.patch("movies.redis_services.cache")
    fake_cache.get.side_effect = error
    fetch = CountingFetch({"fresh": 1})

    assert cache_tmdb("key", fetch, 60) == {"fresh": 1}
    assert fetch.calls == 1
    # The store is still attempted after a failed lookup.
    fake_cache.set.assert_called_once_with("key", {"fresh": 1}, 60)


@pytest.mark.parametrize("error", [Exception("generic"), RedisError("down"), RuntimeError("x")])
def test_cache_tmdb_swallows_any_exception_on_set(mocker, error):
    fake_cache = mocker.patch("movies.redis_services.cache")
    fake_cache.get.return_value = None
    fake_cache.set.side_effect = error

    assert cache_tmdb("key", CountingFetch({"fresh": 1}), 60) == {"fresh": 1}


def test_cache_tmdb_other_fetch_exceptions_propagate():
    with pytest.raises(ValueError, match="boom"):
        cache_tmdb("key", CountingFetch(ValueError("boom")), 60)


def test_cache_tmdb_errors_log_warnings(mocker, caplog):
    fake_cache = mocker.patch("movies.redis_services.cache")
    fake_cache.get.side_effect = Exception("get down")
    fake_cache.set.side_effect = Exception("set down")

    with caplog.at_level(logging.WARNING, logger="movies.redis_services"):
        cache_tmdb("key", CountingFetch("x"), 60)

    warnings = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING]
    assert warnings == [
        "Cache unavailable, skipping lookup for key: Exception('get down')",
        "Cache unavailable, skipping store for key: Exception('set down')",
    ]


# --------------------------------------------------------------------------- cache_item_detail


def test_cache_item_detail_key_and_ttl(isolated_cache):
    fetch = CountingFetch({"tmdb_id": 550})

    assert cache_item_detail("item", "movie", 550, fetch) == {"tmdb_id": 550}
    assert isolated_cache.ttls == {"movies:item:v1:movie:550": 21600}


def test_cache_item_detail_hit_and_fallback(isolated_cache):
    isolated_cache.store["movies:credits:v1:tv:1396"] = json.dumps({"cast": []})
    fetch = CountingFetch({"cast": ["x"]})

    assert cache_item_detail("credits", "tv", 1396, fetch) == {"cast": []}
    assert fetch.calls == 0

    fallback = {"genres": []}
    assert cache_item_detail("item", "tv", 7, CountingFetch(TMDBFetchError(fallback))) is fallback
    assert "movies:item:v1:tv:7" not in isolated_cache.store


# --------------------------------------------------------------------------- cache_items_detail


def test_cache_items_detail_empty_input_touches_nothing(isolated_cache, mocker):
    mget = mocker.spy(isolated_cache, "mget")
    pipeline = mocker.spy(isolated_cache, "pipeline")

    assert cache_items_detail("item", "movie", []) == {}
    mget.assert_not_called()
    pipeline.assert_not_called()


def test_cache_items_detail_all_hits_no_fetch_no_write(isolated_cache, mocker):
    isolated_cache.store["movies:item:v1:movie:1"] = json.dumps({"id": 1})
    isolated_cache.store["movies:item:v1:movie:2"] = json.dumps({"id": 2})
    pipeline = mocker.spy(isolated_cache, "pipeline")
    f1, f2 = CountingFetch("x"), CountingFetch("y")

    assert cache_items_detail("item", "movie", [(1, f1), (2, f2)]) == {1: {"id": 1}, 2: {"id": 2}}
    assert f1.calls == f2.calls == 0
    pipeline.assert_not_called()


def test_cache_items_detail_mixed_hits_misses_and_fallbacks(isolated_cache, mocker):
    isolated_cache.store["movies:item:v1:tv:1"] = json.dumps({"id": 1, "cached": True})
    mget = mocker.spy(isolated_cache, "mget")
    queued = []
    pipelines_created = []
    real_pipeline = isolated_cache.pipeline

    def recording_pipeline():
        pipe = real_pipeline()
        pipelines_created.append(pipe)
        real_set = pipe.set

        def set_(key, value, ex=None):
            queued.append((key, value, ex))
            return real_set(key, value, ex=ex)

        pipe.set = set_
        return pipe

    mocker.patch.object(isolated_cache, "pipeline", side_effect=recording_pipeline)
    hit_fetch = CountingFetch("unused")
    miss_fetch = CountingFetch({"id": 2})
    fallback = {"id": 3, "fallback": True}
    fail_fetch = CountingFetch(TMDBFetchError(fallback))
    miss2_fetch = CountingFetch({"id": 4})

    result = cache_items_detail("item", "tv", [(1, hit_fetch), (2, miss_fetch), (3, fail_fetch), (4, miss2_fetch)])

    assert result == {1: {"id": 1, "cached": True}, 2: {"id": 2}, 3: fallback, 4: {"id": 4}}
    assert result[3] is fallback
    assert list(result) == [1, 2, 3, 4]
    assert (hit_fetch.calls, miss_fetch.calls, fail_fetch.calls, miss2_fetch.calls) == (0, 1, 1, 1)
    # One MGET for every key, in input order.
    mget.assert_called_once_with(
        ["movies:item:v1:tv:1", "movies:item:v1:tv:2", "movies:item:v1:tv:3", "movies:item:v1:tv:4"]
    )
    # One pipeline, holding only the fresh misses (no hit, no fallback), JSON with ttl 21600.
    assert len(pipelines_created) == 1
    assert queued == [
        ("movies:item:v1:tv:2", json.dumps({"id": 2}), 21600),
        ("movies:item:v1:tv:4", json.dumps({"id": 4}), 21600),
    ]
    assert "movies:item:v1:tv:3" not in isolated_cache.store
    assert isolated_cache.ttls == {"movies:item:v1:tv:2": 21600, "movies:item:v1:tv:4": 21600}


def test_cache_items_detail_single_pipeline_and_no_plain_set(isolated_cache, mocker):
    pipeline = mocker.spy(isolated_cache, "pipeline")
    plain_get = mocker.spy(isolated_cache, "get")
    items = [(i, CountingFetch({"id": i})) for i in range(5)]
    original_set = isolated_cache.set
    set_calls = []

    def tracking_set(key, value, ex=None):
        set_calls.append(key)
        return original_set(key, value, ex=ex)

    # FakePipeline.execute() writes through client.set; count those writes.
    mocker.patch.object(isolated_cache, "set", side_effect=tracking_set)

    cache_items_detail("credits", "movie", items)

    assert pipeline.call_count == 1
    plain_get.assert_not_called()
    assert set_calls == [f"movies:credits:v1:movie:{i}" for i in range(5)]


def test_cache_items_detail_all_fallbacks_skip_pipeline(isolated_cache, mocker):
    pipeline = mocker.spy(isolated_cache, "pipeline")

    result = cache_items_detail("item", "movie", [(1, CountingFetch(TMDBFetchError({"f": 1})))])

    assert result == {1: {"f": 1}}
    pipeline.assert_not_called()
    assert isolated_cache.store == {}


def test_cache_items_detail_hit_values_are_json_decoded(isolated_cache):
    cache_items_detail("item", "movie", [(1, CountingFetch({"pair": (1, 2)}))])

    # First call returns the fetch object as-is; second call is a hit -> lists.
    assert cache_items_detail("item", "movie", [(1, CountingFetch("unused"))]) == {1: {"pair": [1, 2]}}


def test_cache_items_detail_shares_keys_with_cache_item_detail(isolated_cache):
    cache_item_detail("item", "movie", 9, CountingFetch({"id": 9}))
    fetch = CountingFetch("unused")

    assert cache_items_detail("item", "movie", [(9, fetch)]) == {9: {"id": 9}}
    assert fetch.calls == 0


def test_cache_items_detail_duplicate_ids_fetch_each_and_last_wins(isolated_cache):
    first, second = CountingFetch({"v": 1}), CountingFetch({"v": 2})

    result = cache_items_detail("item", "movie", [(1, first), (1, second)])

    assert (first.calls, second.calls) == (1, 1)
    assert result == {1: {"v": 2}}
    assert json.loads(isolated_cache.store["movies:item:v1:movie:1"]) == {"v": 2}


def test_cache_items_detail_mget_error_is_swallowed_and_everything_fetched(isolated_cache, mocker):
    mocker.patch.object(isolated_cache, "mget", side_effect=RedisError("down"))
    isolated_cache.store["movies:item:v1:movie:1"] = json.dumps({"stale": True})
    fetch = CountingFetch({"fresh": True})

    assert cache_items_detail("item", "movie", [(1, fetch)]) == {1: {"fresh": True}}
    assert fetch.calls == 1
    # Writes still go out after a failed MGET.
    assert json.loads(isolated_cache.store["movies:item:v1:movie:1"]) == {"fresh": True}


@pytest.mark.parametrize("error_on", ["set", "execute"])
def test_cache_items_detail_pipeline_error_is_swallowed(isolated_cache, mocker, error_on):
    mocker.patch.object(isolated_cache, "pipeline", side_effect=broken_pipeline(error_on))

    assert cache_items_detail("item", "movie", [(1, CountingFetch({"id": 1}))]) == {1: {"id": 1}}
    assert isolated_cache.store == {}


def test_cache_items_detail_pipeline_creation_error_is_swallowed(isolated_cache, mocker):
    mocker.patch.object(isolated_cache, "pipeline", side_effect=RedisError("down"))

    assert cache_items_detail("item", "movie", [(1, CountingFetch({"id": 1}))]) == {1: {"id": 1}}


def test_cache_items_detail_other_fetch_exceptions_propagate_and_nothing_written(isolated_cache):
    items = [(1, CountingFetch({"id": 1})), (2, CountingFetch(ValueError("boom")))]

    with pytest.raises(ValueError, match="boom"):
        cache_items_detail("item", "movie", items)
    # Item 1 was fetched but the batch write never happened.
    assert isolated_cache.store == {}


def test_cache_items_detail_mget_length_mismatch_raises(isolated_cache, mocker):
    # zip(..., strict=True): a short MGET reply is a ValueError, not silently truncated.
    mocker.patch.object(isolated_cache, "mget", return_value=[None])

    with pytest.raises(ValueError):
        cache_items_detail("item", "movie", [(1, CountingFetch({})), (2, CountingFetch({}))])


# --------------------------------------------------------------------------- cache_search_results


def test_cache_search_results_key_and_ttl(isolated_cache):
    cache_search_results("Batman", CountingFetch([[1, "movie"]]))

    assert isolated_cache.ttls == {"movies:search:v1:batman": 604800}


@pytest.mark.parametrize(
    ("query", "normalized"),
    [
        ("Batman", "batman"),
        ("  batman  ", "batman"),
        ("The   Dark\tKnight\n", "the dark knight"),
        ("BATMAN begins", "batman begins"),
        ("", ""),
        ("   ", ""),
        ("Amélie", "amélie"),
    ],
)
def test_cache_search_results_normalizes_query_for_key(isolated_cache, query, normalized):
    cache_search_results(query, CountingFetch([]))

    assert list(isolated_cache.store) == [f"movies:search:v1:{normalized}"]


def test_cache_search_results_lower_not_casefold(isolated_cache):
    cache_search_results("Straße", CountingFetch([]))

    assert list(isolated_cache.store) == ["movies:search:v1:straße"]


def test_cache_search_results_variants_share_one_entry(isolated_cache):
    cache_search_results("Batman", CountingFetch([(1, "movie")]))
    fetch = CountingFetch([(2, "tv")])

    # Hit, JSON round-tripped: tuples come back as lists.
    assert cache_search_results("  bATMAN ", fetch) == [[1, "movie"]]
    assert fetch.calls == 0


def test_cache_search_results_fetch_is_called_without_arguments(isolated_cache):
    # The original query is not passed on; the fetch closure carries it.
    calls = []

    def fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    cache_search_results(" Batman ", fetch)
    assert calls == [((), {})]


def test_cache_search_results_fallback_not_cached(isolated_cache):
    fallback = []

    assert cache_search_results("nothing", CountingFetch(TMDBFetchError(fallback))) is fallback
    assert isolated_cache.store == {}


# --------------------------------------------------------------------------- cache_genres


def test_cache_genres_key_and_ttl(isolated_cache):
    genres = [{"id": 28, "name": "Action"}]

    assert cache_genres("movie", CountingFetch(genres)) == genres
    assert isolated_cache.ttls == {"movies:genres:v1:movie": TTL_GENRES}
    assert json.loads(isolated_cache.store["movies:genres:v1:movie"]) == genres


def test_cache_genres_hit_and_fallback(isolated_cache):
    isolated_cache.store["movies:genres:v1:tv"] = json.dumps([{"id": 1, "name": "Drama"}])
    fetch = CountingFetch([])

    assert cache_genres("tv", fetch) == [{"id": 1, "name": "Drama"}]
    assert fetch.calls == 0

    assert cache_genres("movie", CountingFetch(TMDBFetchError([]))) == []
    assert "movies:genres:v1:movie" not in isolated_cache.store


# --------------------------------------------------------------------------- module wiring


def test_raw_paths_use_module_level_r(mocker):
    # Every raw-client path looks up `redis_services.r` at call time (that's what
    # lets conftest swap it). Swap it again here and check the calls land on it.
    other = mocker.MagicMock()
    other.get.return_value = None
    other.mget.return_value = [None]
    mocker.patch.object(redis_services, "r", other)

    cache_genres("movie", CountingFetch([]))
    cache_items_detail("item", "movie", [(1, CountingFetch({}))])

    other.get.assert_called_once_with("movies:genres:v1:movie")
    other.set.assert_called_once_with("movies:genres:v1:movie", "[]", ex=TTL_GENRES)
    other.mget.assert_called_once_with(["movies:item:v1:movie:1"])
    other.pipeline.return_value.set.assert_called_once_with("movies:item:v1:movie:1", "{}", ex=21600)
    other.pipeline.return_value.execute.assert_called_once_with()
