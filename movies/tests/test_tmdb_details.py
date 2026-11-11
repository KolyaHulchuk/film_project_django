"""Characterization tests for TMDBClient: they pin down the current behavior
(response shapes, limits, TMDB request params, cache keys and TTLs) so a
refactor of movies/tmdb_service.py can be checked against it.

`_request` is always mocked (no HTTP). The cache layers are real but isolated
by movies/tests/conftest.py (locmem Django cache + in-memory fake for
redis_services.r), so cache keys/TTLs and "failures are not cached" are
asserted through the actual cache-aside code.
"""

import copy

import pytest
import requests

from movies import tmdb_service
from movies.redis_services import TMDBFetchError
from movies.tmdb_service import TMDBClient, fetch_parallel

IMG = "https://image.tmdb.org/t/p"


@pytest.fixture
def client():
    return TMDBClient(api_key="test_key", languages=["en"])


@pytest.fixture
def cache_tmdb_spy(mocker):
    return mocker.spy(tmdb_service, "cache_tmdb")


# --------------------------------------------------------------------------- _request


def test_request_sends_api_key_and_timeout(mocker, client):
    get = mocker.patch("movies.tmdb_service.requests.get")
    get.return_value.status_code = 200
    get.return_value.json.return_value = {"id": 1}

    assert client._request("movie/1", {"language": "en"}) == {"id": 1}
    get.assert_called_once_with(
        "https://api.themoviedb.org/3/movie/1",
        params={"language": "en", "api_key": "test_key"},
        timeout=(3.05, 10),
    )


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_request_network_errors_return_empty_dict(mocker, client, error):
    mocker.patch("movies.tmdb_service.requests.get", side_effect=error)

    assert client._request("movie/1") == {}


def test_request_invalid_json_returns_empty_dict(mocker, client):
    get = mocker.patch("movies.tmdb_service.requests.get")
    get.return_value.status_code = 200
    get.return_value.json.side_effect = ValueError("bad json")

    assert client._request("movie/1") == {}


def test_lookup_by_id_endpoints(mocker, client):
    request = mocker.patch.object(client, "_request", return_value={"id": 5})

    assert client.get_movie_by_tmdb_id(5) == {"id": 5}
    assert client.get_tv_by_tmdb_id(6) == {"id": 5}
    assert request.call_args_list == [mocker.call("movie/5"), mocker.call("tv/6")]


# --------------------------------------------------------------------------- get_details


def _raw_movie():
    def recommendation(i):
        if i == 3:
            return {
                "id": 103,
                "media_type": "tv",
                "name": "Show 3",
                "first_air_date": "2002-02-02",
                "poster_path": "/r3.jpg",
                "vote_average": 7.0,
            }
        return {
            "id": 100 + i,
            "media_type": "movie",
            "title": f"Rec {i}",
            "release_date": "2001-01-01",
            "poster_path": None if i == 0 else f"/r{i}.jpg",
            "vote_average": 6.5,
        }

    return {
        "id": 603,
        "title": "The Matrix",
        "original_language": "en",
        "spoken_languages": [
            {"iso_639_1": "fr", "english_name": "French", "name": "Français"},
            {"iso_639_1": "en", "english_name": "English", "name": "English"},
        ],
        "credits": {
            "cast": [
                {"id": i, "name": f"Actor {i}", "character": f"Role {i}", "profile_path": f"/c{i}.jpg", "order": i}
                for i in range(22)
            ],
            "crew": [
                {"job": "Director", "name": "Lana"},
                {"job": "Director", "name": "Lilly"},
                {"job": "Director", "name": "Lana"},
                {"job": "Screenplay", "name": "Lana"},
                {"job": "Novel", "name": "Someone"},
                {"job": "Producer", "name": "Joel"},
                {"job": "Music", "name": "Don"},
                {"job": "Original Music Composer", "name": "Don"},
                {"job": "Editor", "name": "Zach"},
            ],
        },
        "videos": {
            "results": [
                {"key": "clip", "site": "YouTube", "type": "Clip", "official": True},
                {"key": "teaser", "site": "YouTube", "type": "Teaser", "official": True},
                {"key": "vimeo", "site": "Vimeo", "type": "Trailer", "official": True},
                {"key": "fan", "site": "YouTube", "type": "Trailer", "official": False},
            ]
        },
        "images": {
            "backdrops": [{"file_path": None if i == 1 else f"/b{i}.jpg"} for i in range(7)],
            "posters": [{"file_path": f"/p{i}.jpg"} for i in range(13)],
        },
        "keywords": {"keywords": [{"id": i, "name": f"kw{i}", "extra": True} for i in range(13)]},
        "recommendations": {
            "results": [{"id": 999, "media_type": "person", "name": "P"}] + [recommendation(i) for i in range(15)]
        },
        "release_dates": {
            "results": [
                {"iso_3166_1": "GB", "release_dates": [{"type": 3, "certification": "15"}]},
                {
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"type": 4, "certification": "R-digital"},
                        {"type": 3, "certification": "R"},
                        {"type": 1, "certification": ""},
                    ],
                },
            ]
        },
    }


def _expected_movie_recommendation(i):
    if i == 3:
        return {
            "id": 103,
            "media_type": "tv",
            "name": "Show 3",
            "first_air_date": "2002-02-02",
            "poster_path": "/r3.jpg",
            "vote_average": 7.0,
            "poster_url": f"{IMG}/w500/r3.jpg",
            "title": "Show 3",
            "release_date": "2002-02-02",
            "rating": 7.0,
        }
    return {
        "id": 100 + i,
        "media_type": "movie",
        "title": f"Rec {i}",
        "release_date": "2001-01-01",
        "poster_path": None if i == 0 else f"/r{i}.jpg",
        "vote_average": 6.5,
        "poster_url": None if i == 0 else f"{IMG}/w500/r{i}.jpg",
        "rating": 6.5,
    }


def test_get_details_movie_snapshot(mocker, client, cache_tmdb_spy):
    raw = _raw_movie()
    request = mocker.patch.object(client, "_request", return_value=copy.deepcopy(raw))

    result = client.get_details(603, "movie")

    assert result == {
        "id": 603,
        "title": "The Matrix",
        "original_language": "en",
        "spoken_languages": raw["spoken_languages"],
        "cast": [
            {"id": i, "name": f"Actor {i}", "character": f"Role {i}", "profile_path": f"/c{i}.jpg"} for i in range(20)
        ],
        "crew": {
            "director": ["Lana", "Lilly"],
            "writer": ["Lana", "Someone"],
            "producer": ["Joel"],
            "music": ["Don"],
        },
        "trailer": {"key": "fan", "site": "YouTube", "type": "Trailer", "official": False},
        "backdrops": [f"{IMG}/w780/b{i}.jpg" for i in (0, 2, 3, 4, 5)],
        "posters": [{"thumb": f"{IMG}/w342/p{i}.jpg", "full": f"{IMG}/w780/p{i}.jpg"} for i in range(12)],
        "keywords": [{"id": i, "name": f"kw{i}"} for i in range(12)],
        "recommendations": [_expected_movie_recommendation(i) for i in range(14)],
        "certification": "R",
        "language": "English",
    }
    request.assert_called_once_with(
        "movie/603",
        {
            "language": "en",
            "append_to_response": "videos,credits,images,keywords,recommendations,release_dates",
            "include_image_language": "en,null",
        },
    )
    key, _fetch, ttl = cache_tmdb_spy.call_args.args
    assert (key, ttl) == ("movies:details:v1:movie:603", 86400)

    # Second call is served from the cache: same data, no new TMDB request.
    assert client.get_details(603, "movie") == result
    assert request.call_count == 1


def test_get_details_tv_snapshot(mocker, client, cache_tmdb_spy):
    raw = {
        "id": 1399,
        "name": "Thrones",
        "original_language": "ko",
        "spoken_languages": [{"iso_639_1": "ko", "english_name": "", "name": "한국어"}],
        "created_by": [{"name": "David"}, {"name": "Dan"}],
        "credits": {"cast": [], "crew": [{"job": "Producer", "name": "Bernie"}]},
        "videos": None,
        "images": {},
        "keywords": {"results": [{"id": 1, "name": "dragons"}]},
        # No media_type on TV recommendations: kept by the filter (defaults to
        # the page's media_type) but normalized by _type_items as a movie.
        "recommendations": {
            "results": [
                {"id": 5, "name": "HotD", "poster_path": "/h.jpg", "first_air_date": "2022-08-21", "vote_average": 8.4}
            ]
        },
        "content_ratings": {"results": [{"iso_3166_1": "DE", "rating": "16"}, {"iso_3166_1": "US", "rating": "TV-MA"}]},
    }
    request = mocker.patch.object(client, "_request", return_value=copy.deepcopy(raw))

    result = client.get_details(1399, "tv")

    assert result == {
        "id": 1399,
        "name": "Thrones",
        "original_language": "ko",
        "spoken_languages": raw["spoken_languages"],
        "created_by": raw["created_by"],
        "cast": [],
        "crew": {"producer": ["Bernie"], "creator": ["David", "Dan"]},
        "trailer": None,
        "backdrops": [],
        "posters": [],
        "keywords": [{"id": 1, "name": "dragons"}],
        "recommendations": [
            {
                "id": 5,
                "name": "HotD",
                "poster_path": "/h.jpg",
                "first_air_date": "2022-08-21",
                "vote_average": 8.4,
                "poster_url": f"{IMG}/w500/h.jpg",
                "title": None,
                "release_date": None,
                "rating": 8.4,
            }
        ],
        "certification": "TV-MA",
        "language": "한국어",
    }
    request.assert_called_once_with(
        "tv/1399",
        {
            "language": "en",
            "append_to_response": "videos,credits,images,keywords,recommendations,content_ratings",
            "include_image_language": "en,null",
        },
    )
    key, _fetch, ttl = cache_tmdb_spy.call_args.args
    assert (key, ttl) == ("movies:details:v1:tv:1399", 86400)


@pytest.mark.parametrize("response", [{}, {"status_code": 34, "status_message": "not found"}])
def test_get_details_failure_returns_empty_details_uncached(mocker, client, response):
    request = mocker.patch.object(client, "_request", return_value=response)

    assert client.get_details(1, "movie") == TMDBClient._empty_details()
    assert client.get_details(1, "movie") == TMDBClient._empty_details()
    assert request.call_count == 2


def test_empty_details_shape():
    assert TMDBClient._empty_details() == {
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


def test_get_details_unknown_media_type_makes_no_request(mocker, client):
    request = mocker.patch.object(client, "_request")

    assert client.get_details(1, "person") == TMDBClient._empty_details()
    request.assert_not_called()


# --------------------------------------------------------------------------- details helpers


def _video(key, type_, official=True, site="YouTube"):
    return {"key": key, "type": type_, "official": official, "site": site}


@pytest.mark.parametrize(
    "videos, expected_key",
    [
        ([_video("t2", "Trailer", False), _video("t1", "Trailer")], "t1"),
        ([_video("tz1", "Teaser"), _video("t2", "Trailer", False)], "t2"),
        ([_video("c", "Clip"), _video("tz2", "Teaser", False), _video("tz1", "Teaser")], "tz1"),
        ([_video("c", "Clip"), _video("tz2", "Teaser", False)], "tz2"),
        ([_video("bts", "Behind the Scenes"), _video("c", "Clip", False)], "c"),
        ([_video("v", "Trailer", site="Vimeo"), _video("bts", "Featurette")], None),
        ([], None),
    ],
)
def test_select_trailer_priority(videos, expected_key):
    trailer = TMDBClient._select_trailer(videos)

    assert (trailer or {}).get("key") == expected_key


def test_select_images_limits_and_none():
    images = {
        "backdrops": [{"file_path": f"/b{i}.jpg"} for i in range(5)],
        "posters": [{"file_path": f"/p{i}.jpg"} for i in range(5)],
    }

    assert TMDBClient._select_backdrops(images, limit=2) == [f"{IMG}/w780/b0.jpg", f"{IMG}/w780/b1.jpg"]
    assert TMDBClient._select_posters(images, limit=1) == [
        {"thumb": f"{IMG}/w342/p0.jpg", "full": f"{IMG}/w780/p0.jpg"}
    ]
    assert TMDBClient._select_backdrops(None) == []
    assert TMDBClient._select_posters({}) == []


@pytest.mark.parametrize(
    "media_type, release_dates, content_ratings, expected",
    [
        ("movie", [{"iso_3166_1": "GB", "release_dates": [{"type": 3, "certification": "15"}]}], [], None),
        ("movie", [{"iso_3166_1": "US", "release_dates": [{"type": 3, "certification": ""}]}], [], None),
        (
            "movie",
            [
                {
                    "iso_3166_1": "US",
                    "release_dates": [{"type": 5, "certification": "NR"}, {"type": 3, "certification": ""}],
                }
            ],
            [],
            "NR",
        ),
        ("tv", [], [{"iso_3166_1": "US", "rating": ""}, {"iso_3166_1": "US", "rating": "TV-14"}], "TV-14"),
        ("tv", [], [{"iso_3166_1": "GB", "rating": "15"}], None),
    ],
)
def test_certification(media_type, release_dates, content_ratings, expected):
    assert TMDBClient._certification(media_type, release_dates, content_ratings) == expected


@pytest.mark.parametrize(
    "data, expected",
    [
        ({"original_language": "en", "spoken_languages": [{"iso_639_1": "en", "english_name": "English"}]}, "English"),
        ({"original_language": "xx", "spoken_languages": []}, "XX"),
        ({}, None),
    ],
)
def test_language_name(data, expected):
    assert TMDBClient._language_name(data) == expected


def test_type_items_movie_tv_and_missing_poster():
    items = [
        {
            "id": 1,
            "media_type": "movie",
            "title": "M",
            "release_date": "2000-01-01",
            "poster_path": "/m.jpg",
            "vote_average": 7,
        },
        {
            "id": 2,
            "media_type": "tv",
            "name": "S",
            "first_air_date": "2010-01-01",
            "poster_path": None,
            "vote_average": 8,
        },
    ]

    result = TMDBClient(api_key="k")._type_items(items)

    assert result is items
    assert [(i["poster_url"], i["title"], i["release_date"], i["rating"]) for i in result] == [
        (f"{IMG}/w500/m.jpg", "M", "2000-01-01", 7),
        (None, "S", "2010-01-01", 8),
    ]


# --------------------------------------------------------------------------- season / collection / keyword


def test_get_season_shape_and_cache(mocker, client, cache_tmdb_spy):
    raw = {
        "_id": "abc",
        "season_number": 1,
        "name": "Season 1",
        "air_date": "2011-04-17",
        "overview": "dropped",
        "episodes": [
            {
                "episode_number": 1,
                "name": "Winter Is Coming",
                "overview": "o",
                "air_date": "2011-04-17",
                "runtime": 62,
                "still_path": "/s.jpg",
                "vote_average": 8.1,
                "crew": [{"name": "x"}],
                "guest_stars": [{"name": "y"}],
            },
            {"episode_number": 2},
        ],
    }
    request = mocker.patch.object(client, "_request", return_value=raw)

    result = client.get_season(1399, 1)

    assert result == {
        "season_number": 1,
        "name": "Season 1",
        "air_date": "2011-04-17",
        "episodes": [
            {
                "episode_number": 1,
                "name": "Winter Is Coming",
                "overview": "o",
                "air_date": "2011-04-17",
                "runtime": 62,
                "still_path": "/s.jpg",
                "vote_average": 8.1,
            },
            {
                "episode_number": 2,
                "name": None,
                "overview": None,
                "air_date": None,
                "runtime": None,
                "still_path": None,
                "vote_average": None,
            },
        ],
    }
    request.assert_called_once_with("tv/1399/season/1", {"language": "en"})
    key, _fetch, ttl = cache_tmdb_spy.call_args.args
    assert (key, ttl) == ("movies:season:v1:1399:1", 86400)


@pytest.mark.parametrize("response", [{}, {"name": "no episodes"}])
def test_get_season_failure_returns_none_uncached(mocker, client, response):
    request = mocker.patch.object(client, "_request", return_value=response)

    assert client.get_season(1, 2) is None
    assert client.get_season(1, 2) is None
    assert request.call_count == 2


def test_get_collection_sorted_parts_and_cache(mocker, client, cache_tmdb_spy):
    raw = {
        "id": 10,
        "name": "Star Wars Collection",
        "overview": "o",
        "poster_path": "/c.jpg",
        "parts": [
            {
                "id": 3,
                "title": "C",
                "release_date": "",
                "poster_path": None,
                "vote_average": 0,
                "vote_count": 0,
                "x": 1,
            },
            {
                "id": 1,
                "title": "A",
                "release_date": "1977-05-25",
                "poster_path": "/a.jpg",
                "vote_average": 8.2,
                "vote_count": 100,
            },
            {
                "id": 2,
                "title": "B",
                "release_date": "1980-05-20",
                "poster_path": "/b.jpg",
                "vote_average": 8.4,
                "vote_count": 90,
            },
        ],
    }
    request = mocker.patch.object(client, "_request", return_value=raw)

    result = client.get_collection(10)

    assert result == {
        "id": 10,
        "name": "Star Wars Collection",
        "overview": "o",
        "parts": [
            {
                "id": 1,
                "title": "A",
                "release_date": "1977-05-25",
                "poster_url": f"{IMG}/w500/a.jpg",
                "vote_average": 8.2,
                "vote_count": 100,
            },
            {
                "id": 2,
                "title": "B",
                "release_date": "1980-05-20",
                "poster_url": f"{IMG}/w500/b.jpg",
                "vote_average": 8.4,
                "vote_count": 90,
            },
            {"id": 3, "title": "C", "release_date": "", "poster_url": None, "vote_average": 0, "vote_count": 0},
        ],
    }
    request.assert_called_once_with("collection/10", {"language": "en"})
    key, _fetch, ttl = cache_tmdb_spy.call_args.args
    assert (key, ttl) == ("movies:collection:v1:10", 86400)


def test_get_collection_failure_returns_none(mocker, client):
    mocker.patch.object(client, "_request", return_value={"id": 10})

    assert client.get_collection(10) is None


def test_get_keyword_shape_and_cache(mocker, client, cache_tmdb_spy):
    request = mocker.patch.object(client, "_request", return_value={"id": 180547, "name": "superhero", "x": 1})

    assert client.get_keyword(180547) == {"id": 180547, "name": "superhero"}
    request.assert_called_once_with("keyword/180547")
    key, _fetch, ttl = cache_tmdb_spy.call_args.args
    assert (key, ttl) == ("movies:keyword:v1:180547", 86400)


def test_get_keyword_failure_returns_none(mocker, client):
    mocker.patch.object(client, "_request", return_value={})

    assert client.get_keyword(1) is None


# --------------------------------------------------------------------------- get_list and friends


def test_get_list_params_dedupe_cap_and_cache_key(mocker, client, isolated_cache):
    response = {
        "page": 2,
        "total_pages": 500,
        "total_results": 9999,
        "results": [
            {"id": 1, "media_type": "movie", "title": "A", "release_date": "2000-01-01", "poster_path": "/a.jpg"},
            {"id": 1, "media_type": "movie", "title": "A duplicate"},
            {"id": 2, "media_type": "tv", "name": "S", "first_air_date": "2020-01-01", "vote_average": 7.5},
        ],
    }
    request = mocker.patch.object(client, "_request", return_value=response)

    result = client.get_list("discover/tv", 2, with_genres=16, max_page=100)

    # max_page is currently sent to TMDB too (but kept out of the cache key).
    request.assert_called_once_with("discover/tv", {"language": "en", "page": 2, "with_genres": 16, "max_page": 100})
    assert result["page"] == 2
    assert result["total_pages"] == 100
    assert result["total_results"] == 9999
    assert [(i["id"], i["title"], i["release_date"], i["poster_url"], i["rating"]) for i in result["results"]] == [
        (1, "A", "2000-01-01", f"{IMG}/w500/a.jpg", None),
        (2, "S", "2020-01-01", None, 7.5),
    ]
    assert isolated_cache.ttls == {"movies:list:v2:discover/tv:2:with_genres=16": 43200}  # TTL_LIST, 12h


def test_get_list_defaults(mocker, client, isolated_cache):
    request = mocker.patch.object(
        client, "_request", return_value={"results": [], "total_pages": 500, "total_results": 0}
    )

    result = client.get_list("movie/popular")

    request.assert_called_once_with("movie/popular", {"language": "en", "page": 1})
    assert result == {"results": [], "page": 1, "total_pages": 10, "total_results": 0}
    assert isolated_cache.ttls == {"movies:list:v2:movie/popular:1:": 43200}


def test_get_list_keeps_smaller_total_pages_and_explicit_ttl(mocker, client, isolated_cache):
    mocker.patch.object(client, "_request", return_value={"results": [], "page": 1, "total_pages": 3})

    result = client.get_list("discover/movie", 1, ttl=60, sort_by="vote_average.desc")

    assert result["total_pages"] == 3
    assert result["total_results"] == 0
    assert isolated_cache.ttls == {"movies:list:v2:discover/movie:1:sort_by=vote_average.desc": 60}


def test_get_list_failure_fallback_is_not_cached(mocker, client, isolated_cache):
    mocker.patch.object(client, "_request", return_value={})

    assert client.get_list("movie/popular", 4) == {"results": [], "page": 4, "total_pages": 1, "total_results": 0}
    assert isolated_cache.store == {}


def test_get_genres_tv_endpoint_and_cache(mocker, client, isolated_cache):
    request = mocker.patch.object(client, "_request", return_value={"genres": [{"id": 10759, "name": "Action"}]})

    assert client.get_genres("tv") == [{"id": 10759, "name": "Action"}]
    request.assert_called_once_with("genre/tv/list")
    assert isolated_cache.ttls == {"movies:genres:v1:tv": 129600}


def test_get_genres_failure_not_cached(mocker, client, isolated_cache):
    mocker.patch.object(client, "_request", return_value={"status_code": 7})

    assert client.get_genres("movie") == []
    assert isolated_cache.store == {}


def test_get_keyword_movies_delegates_to_get_list(mocker, client):
    get_list = mocker.patch.object(client, "get_list", return_value="list")

    assert client.get_keyword_movies(5, 3) == "list"
    get_list.assert_called_once_with("keyword/5/movies", 3)


def test_get_trending_endpoints(mocker, client):
    get_list = mocker.patch.object(client, "get_list", return_value="list")

    client.get_trending()
    client.get_trending("tv", "week", 2)

    assert get_list.call_args_list == [mocker.call("trending/all/day", 1), mocker.call("trending/tv/week", 2)]


@pytest.mark.parametrize("media_type, window", [("anime", "day"), ("tv", "month")])
def test_get_trending_rejects_unknown_lists(mocker, client, media_type, window):
    get_list = mocker.patch.object(client, "get_list")

    with pytest.raises(ValueError, match=f"Unsupported trending list: {media_type}/{window}"):
        client.get_trending(media_type, window)
    get_list.assert_not_called()


def test_get_list_with_trailers_takes_first_items(mocker, client):
    get_list = mocker.patch.object(client, "get_list", return_value={"results": [{"id": i} for i in range(8)]})
    mocker.patch.object(client, "get_details", side_effect=lambda tmdb_id, media_type: {"trailer": f"t{tmdb_id}"})

    result = client.get_list_with_trailers("trending/all/day", 1, "movie")

    get_list.assert_called_once_with("trending/all/day", 1)
    assert result == [{"id": i, "trailer": f"t{i}"} for i in range(5)]


def test_attach_trailers(mocker, client):
    def fake_details(tmdb_id, media_type):
        if tmdb_id == 2:
            raise RuntimeError("boom")
        if tmdb_id == 3:
            return None
        return {"trailer": {"key": f"k{tmdb_id}"}}

    get_details = mocker.patch.object(client, "get_details", side_effect=fake_details)
    items = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]

    result = client.attach_trailers(items, "tv")

    assert result is items
    assert [i["trailer"] for i in result] == [{"key": "k1"}, None, None, {"key": "k4"}]
    assert sorted(c.args for c in get_details.call_args_list) == [(1, "tv"), (2, "tv"), (3, "tv"), (4, "tv")]


# --------------------------------------------------------------------------- search


def test_search_movies_across_languages(mocker, client):
    client.languages = ["en", "uk"]
    request = mocker.patch.object(
        client,
        "_request",
        side_effect=[
            {"results": [{"id": 1, "media_type": "movie", "title": "A"}, {"id": 9, "media_type": "person"}]},
            {
                "results": [
                    {"id": 1, "media_type": "movie", "title": "A (uk)"},
                    {"id": 2, "media_type": "tv", "name": "S"},
                ]
            },
        ],
    )

    result = client.search_movies("bat")

    assert request.call_args_list == [
        mocker.call("search/multi", {"query": "bat", "language": "en"}),
        mocker.call("search/multi", {"query": "bat", "language": "uk"}),
    ]
    assert [(i["id"], i["title"]) for i in result] == [(1, "A"), (2, "S")]


def test_suggest_filters_limits_and_uses_first_language(mocker, client):
    client.languages = ["uk", "en"]
    results = [{"id": 0, "media_type": "person"}] + [
        {"id": i, "media_type": "movie" if i % 2 else "tv", "title": f"M{i}", "name": f"S{i}"} for i in range(1, 9)
    ]
    request = mocker.patch.object(client, "_request", return_value={"results": results})

    result = client.suggest("bat")

    request.assert_called_once_with("search/multi", {"query": "bat", "language": "uk"})
    assert [(i["id"], i["title"]) for i in result] == [(1, "M1"), (2, "S2"), (3, "M3"), (4, "S4"), (5, "M5"), (6, "S6")]
    assert len(client.suggest("bat", limit=2)) == 2


def test_suggest_failure_raises_with_empty_fallback(mocker, client):
    mocker.patch.object(client, "_request", return_value={})

    with pytest.raises(TMDBFetchError) as exc_info:
        client.suggest("bat")
    assert exc_info.value.fallback == []


# --------------------------------------------------------------------------- popular actors


def test_get_popular_actors(mocker, client):
    request = mocker.patch.object(
        client,
        "_request",
        return_value={
            "total_pages": 500,
            "results": [
                {"id": 1, "known_for_department": "Acting"},
                {"id": 2, "known_for_department": "Directing"},
                {"id": 3, "known_for_department": "Acting"},
            ],
        },
    )

    result = client.get_popular_actors(7)

    request.assert_called_once_with("person/popular", {"page": 7})
    assert result == {
        "actors": [{"id": 1, "known_for_department": "Acting"}, {"id": 3, "known_for_department": "Acting"}],
        "current_page": 7,
        "total_pages": 50,
        "page_range": range(4, 10),
    }


@pytest.mark.parametrize(
    "page, response, expected",
    [
        (60, {"total_pages": 500, "results": []}, (50, 50, range(47, 51))),
        (1, {}, (1, 1, range(1, 2))),
        (2, {"total_pages": 3, "results": []}, (2, 3, range(1, 4))),
    ],
)
def test_get_popular_actors_page_clamping(mocker, client, page, response, expected):
    mocker.patch.object(client, "_request", return_value=response)

    result = client.get_popular_actors(page)

    assert (result["current_page"], result["total_pages"], result["page_range"]) == expected


# --------------------------------------------------------------------------- fetch_parallel / release date


def test_fetch_parallel():
    def boom():
        raise RuntimeError("down")

    assert fetch_parallel({}) == {}
    assert fetch_parallel({"a": lambda: 1, "b": boom, "c": lambda: [3]}, max_workers=2) == {
        "a": 1,
        "b": None,
        "c": [3],
    }


def test_get_release_date_missing_returns_none():
    assert TMDBClient.get_release_date({}, "movie") is None
    assert TMDBClient.get_release_date({"release_date": "2000-01-01"}, "tv") is None
