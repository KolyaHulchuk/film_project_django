"""Characterization tests for movies/views.py.

They pin the *current* behavior of the catalog, home, detail, AI and
get_or_create_media code paths before the views refactor: which TMDB calls are
made (and with which arguments), which template is rendered, what goes into the
context, and how many SQL queries run. Most tests replace `movies.views.render`
with `rendered` (below) so the context can be inspected without depending on
the templates; a couple of smoke tests render the real templates.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from movies import views
from movies.models import Genre, Movies, Rating
from movies.redis_services import TTL_LIST
from movies.utils import COUNTRY_CODES
from movies.views import AllMoviesView, get_or_create_media, topic_of_the_day
from users.models import Watchlist

TODAY = datetime.date(2026, 5, 1)


# == Fixtures ==


@pytest.fixture
def tmdb(mocker):
    """The TMDBClient every view in movies.views instantiates."""
    client = MagicMock()
    mocker.patch("movies.views.TMDBClient", return_value=client)
    return client


@pytest.fixture
def rendered(mocker):
    """Replace movies.views.render; each call is recorded as (template, context, status)."""
    calls = []

    def fake_render(request, template_name, context=None, *args, **kwargs):
        calls.append(SimpleNamespace(template=template_name, context=context, status=kwargs.get("status", 200)))
        return HttpResponse("rendered", status=kwargs.get("status", 200))

    mocker.patch("movies.views.render", side_effect=fake_render)
    return calls


@pytest.fixture
def fixed_today(mocker):
    """Freeze date.today() as seen by movies.views."""
    fake_date = mocker.patch("movies.views.date")
    fake_date.today.return_value = TODAY
    return fake_date


@pytest.fixture
def user(db):
    return User.objects.create_user(username="viewer", password="pass12345")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="other", password="pass12345")


def list_page(ids, page=1, total_pages=1, total_results=None):
    return {
        "page": page,
        "total_pages": total_pages,
        "total_results": total_results,
        "results": [{"id": i, "title": f"Title {i}", "media_type": "movie"} for i in ids],
    }


# == Catalog ==

GENRES = [{"id": 18, "name": "Drama"}, {"id": 35, "name": "Comedy"}]


@pytest.fixture
def catalog_tmdb(tmdb):
    tmdb.get_list.return_value = list_page([1, 2, 3])
    tmdb.get_genres.return_value = GENRES
    tmdb.annotate_items.side_effect = lambda items, media_type, genres: [dict(item) for item in items]
    return tmdb


CATALOG_PAGES = [
    # url name, endpoint, base filters sent to get_list, media_type, sortable, template
    ("popular-movies", "movie/popular", {}, "movie", False, "movies/category/popular.html"),
    ("popular-tv", "tv/popular", {}, "tv", False, "movies/category/tv.html"),
    ("top-rated", "movie/top_rated", {}, "movie", False, "movies/category/top_rated.html"),
    ("now-playings", "movie/now_playing", {}, "movie", False, "movies/category/now_playings.html"),
    ("upcoming", "movie/upcoming", {}, "movie", False, "movies/category/upcoming.html"),
    ("tv", "discover/tv", {"without_genres": 16, "max_page": 100}, "tv", True, "movies/type/tv.html"),
    (
        "anime-tv",
        "discover/tv",
        {"with_genres": 16, "with_original_language": "ja", "with_origin_country": "JP", "max_page": 100},
        "tv",
        True,
        "movies/type/anime.html",
    ),
    (
        "dorams-tv",
        "discover/tv",
        {"with_original_language": "ko", "without_genres": 16, "max_page": 100},
        "tv",
        True,
        "movies/type/dorams.html",
    ),
    (
        "cartoon-tv",
        "discover/tv",
        {"with_genres": 16, "with_origin_country": "US|GB|FR|CA|AU", "max_page": 100},
        "tv",
        True,
        "movies/type/cartoons.html",
    ),
    ("movie", "discover/movie", {"max_page": 100}, "movie", True, "movies/type/movie.html"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name, endpoint, filters, media_type, sortable, template", CATALOG_PAGES)
def test_catalog_tmdb_calls_and_template(
    client, catalog_tmdb, rendered, url_name, endpoint, filters, media_type, sortable, template
):
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert catalog_tmdb.get_list.call_args_list == [call(endpoint, 1, **filters)]
    assert catalog_tmdb.get_genres.call_args_list == [call(media_type)]
    assert catalog_tmdb.annotate_items.call_args_list == [call(list_page([1, 2, 3])["results"], media_type, GENRES)]
    assert len(rendered) == 1
    assert rendered[0].template == template
    assert rendered[0].context["sortable"] is sortable


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", [page[0] for page in CATALOG_PAGES])
def test_catalog_htmx_renders_partial(client, catalog_tmdb, rendered, url_name):
    client.get(reverse(url_name), headers={"HX-Request": "true"})

    assert rendered[0].template == "movies/partials/movie_list.html"


@pytest.mark.django_db
def test_catalog_context(client, catalog_tmdb, rendered):
    catalog_tmdb.get_list.return_value = list_page([1, 2], page=4, total_pages=9, total_results=170)

    client.get(reverse("movie"), {"page": "4", "genre_search": "18", "sort": "rating"})

    context = rendered[0].context
    assert catalog_tmdb.get_list.call_args_list == [
        call(
            "discover/movie",
            4,
            max_page=100,
            with_genres="18",
            sort_by="vote_average.desc",
            **{"vote_count.gte": 100},
        )
    ]
    assert list(context) == [
        "title",
        "items",
        "current_page",
        "total_pages",
        "is_paginated",
        "page_range",
        "countries",
        "genres",
        "current_filters",
        "total_results",
        "sortable",
        "sort_options",
        "current_sort",
    ]
    assert context["title"] == "Movie"
    assert context["items"] == list_page([1, 2])["results"]
    assert context["current_page"] == 4
    assert context["total_pages"] == 9
    assert context["is_paginated"] is True
    assert context["page_range"] == range(1, 7)
    assert context["countries"] is COUNTRY_CODES
    assert context["genres"] == GENRES
    assert context["current_filters"] == "genre_search=18&sort=rating"
    assert context["total_results"] == 170
    assert context["sort_options"] == [
        ("popularity", "Popularity"),
        ("rating", "Rating"),
        ("newest", "Release date"),
        ("title", "A–Z"),
    ]
    assert context["current_sort"] == "rating"


@pytest.mark.django_db
def test_catalog_single_page_is_not_paginated(client, catalog_tmdb, rendered):
    client.get(reverse("popular-movies"))

    context = rendered[0].context
    assert context["is_paginated"] is False
    assert context["page_range"] == range(1, 2)
    assert context["current_filters"] == ""
    assert context["current_sort"] == "popularity"


@pytest.mark.django_db
def test_catalog_without_total_results(client, catalog_tmdb, rendered):
    catalog_tmdb.get_list.return_value = {"page": 1, "total_pages": 1, "results": []}

    client.get(reverse("popular-movies"), {"page": "7"})

    assert rendered[0].context["current_page"] == 1
    assert rendered[0].context["total_results"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("raw_page, requested", [("abc", 1), ("", 1), ("3", 3), ("-2", -2), ("0", 0)])
def test_catalog_page_param_is_sent_to_tmdb_as_parsed(client, catalog_tmdb, rendered, raw_page, requested):
    catalog_tmdb.get_list.return_value = list_page([1], page=1, total_pages=5)

    client.get(reverse("popular-movies"), {"page": raw_page})

    assert catalog_tmdb.get_list.call_args_list == [call("movie/popular", requested)]
    assert rendered[0].context["current_page"] == max(1, min(requested, 5))


@pytest.mark.django_db
def test_catalog_page_beyond_total_is_clamped_but_page_range_uses_tmdb_page(client, catalog_tmdb, rendered):
    catalog_tmdb.get_list.return_value = list_page([1], page=2, total_pages=5)

    client.get(reverse("popular-movies"), {"page": "50"})

    context = rendered[0].context
    assert catalog_tmdb.get_list.call_args_list == [call("movie/popular", 50)]
    assert context["current_page"] == 5
    assert context["page_range"] == range(1, 5)  # from data["page"] = 2, not from the clamped 5


@pytest.mark.django_db
def test_catalog_anonymous_items_have_no_watchlist_fields(client, catalog_tmdb, rendered):
    client.get(reverse("popular-movies"))

    for item in rendered[0].context["items"]:
        assert "is_watched" not in item
        assert "watchlist_id" not in item


@pytest.mark.django_db
def test_catalog_marks_watchlist_items_for_logged_in_user(client, catalog_tmdb, rendered, user, other_user):
    watched = Watchlist.objects.create(user=user, movie=Movies.objects.create(title="One", tmdb_id=1), watched=True)
    unwatched = Watchlist.objects.create(user=user, movie=Movies.objects.create(title="Three", tmdb_id=3))
    Watchlist.objects.create(user=other_user, movie=Movies.objects.create(title="Two", tmdb_id=2), watched=True)
    client.force_login(user)

    client.get(reverse("popular-movies"))

    items = {item["id"]: item for item in rendered[0].context["items"]}
    assert items[1]["is_watched"] is True
    assert items[1]["watchlist_id"] == watched.id
    assert items[3]["is_watched"] is False
    assert items[3]["watchlist_id"] == unwatched.id
    assert "is_watched" not in items[2]
    assert "watchlist_id" not in items[2]


@pytest.mark.django_db
def test_catalog_logged_in_query_count(client, catalog_tmdb, rendered, user, django_assert_num_queries):
    for tmdb_id in (1, 2, 3):
        Watchlist.objects.create(user=user, movie=Movies.objects.create(title=str(tmdb_id), tmdb_id=tmdb_id))
    client.force_login(user)

    # user + one watchlist query with select_related("movie") (sessions live in the cache)
    with django_assert_num_queries(2):
        client.get(reverse("popular-movies"))


@pytest.mark.django_db
def test_catalog_real_template_renders(client, catalog_tmdb):
    response = client.get(reverse("movie"), {"sort": "newest"})

    assert response.status_code == 200
    assert "Title 1" in response.content.decode()


# == Catalog filters from the query string ==


@pytest.mark.django_db
def test_discover_query_filters_are_merged_over_base_filters(client, catalog_tmdb, rendered, fixed_today):
    client.get(reverse("anime-tv"), {"genre_search": "35", "country_search": "KR", "years_search": "2020"})

    assert catalog_tmdb.get_list.call_args_list == [
        call(
            "discover/tv",
            1,
            with_genres="35",  # overrides ANIME_TV_FILTERS' 16
            with_original_language="ja",
            with_origin_country="KR",  # overrides "JP"
            max_page=100,
            first_air_date_year="2020",
        )
    ]


@pytest.mark.django_db
def test_discover_newest_sort_for_tv_page(client, catalog_tmdb, rendered, fixed_today):
    client.get(reverse("tv"), {"sort": "newest", "rating_search": "7"})

    assert catalog_tmdb.get_list.call_args_list == [
        call(
            "discover/tv",
            1,
            without_genres=16,
            max_page=100,
            sort_by="first_air_date.desc",
            **{"vote_average.gte": 7.0, "first_air_date.lte": "2026-05-01", "vote_count.gte": 100},
        )
    ]


@pytest.mark.django_db
def test_non_discover_pages_ignore_query_filters(client, catalog_tmdb, rendered):
    client.get(reverse("top-rated"), {"genre_search": "18", "sort": "rating", "years_search": "2001"})

    assert catalog_tmdb.get_list.call_args_list == [call("movie/top_rated", 1)]
    assert rendered[0].context["sortable"] is False
    assert rendered[0].context["current_sort"] == "rating"


def make_view(media_type):
    view = AllMoviesView()
    view.media_type = media_type
    return view


def filters_for(media_type, **params):
    return make_view(media_type).search_filter_movie(RequestFactory().get("/", params))


def test_search_filter_movie_no_params():
    assert filters_for("movie") == {}
    assert filters_for("tv") == {}


def test_search_filter_movie_years():
    assert filters_for("movie", years_search="1999") == {"primary_release_year": "1999"}
    assert filters_for("tv", years_search="1999") == {"first_air_date_year": "1999"}


def test_search_filter_movie_valid_rating_adds_min_votes():
    assert filters_for("movie", rating_search="7.5") == {"vote_average.gte": 7.5, "vote_count.gte": 100}


def test_search_filter_movie_invalid_rating_is_ignored():
    assert filters_for("movie", rating_search="good") == {}


def test_search_filter_movie_genre_and_country():
    assert filters_for("tv", genre_search="18", country_search="KR") == {
        "with_genres": "18",
        "with_origin_country": "KR",
    }


def test_search_filter_movie_empty_values_are_ignored():
    assert filters_for("movie", years_search="", rating_search="", genre_search="", country_search="", sort="") == {}


@pytest.mark.parametrize(
    "media_type, sort, expected",
    [
        ("movie", "popularity", {}),
        ("tv", "popularity", {}),
        ("movie", "rating", {"sort_by": "vote_average.desc", "vote_count.gte": 100}),
        ("tv", "rating", {"sort_by": "vote_average.desc", "vote_count.gte": 100}),
        ("movie", "newest", {"sort_by": "primary_release_date.desc", "primary_release_date.lte": "2026-05-01"}),
        ("tv", "newest", {"sort_by": "first_air_date.desc", "first_air_date.lte": "2026-05-01"}),
        ("movie", "title", {"sort_by": "title.asc", "vote_count.gte": 100}),
        ("tv", "title", {"sort_by": "name.asc", "vote_count.gte": 100}),
        ("movie", "unknown", {}),
    ],
)
def test_search_filter_movie_sorts(fixed_today, media_type, sort, expected):
    assert filters_for(media_type, sort=sort) == expected


def test_search_filter_movie_all_params_key_order(fixed_today):
    result = filters_for(
        "movie", years_search="2020", rating_search="6", genre_search="28", country_search="US", sort="newest"
    )

    assert list(result.items()) == [
        ("primary_release_year", "2020"),
        ("vote_average.gte", 6.0),
        ("with_genres", "28"),
        ("with_origin_country", "US"),
        ("sort_by", "primary_release_date.desc"),
        ("primary_release_date.lte", "2026-05-01"),
        ("vote_count.gte", 100),
    ]


@pytest.mark.parametrize("raw, expected", [(None, "popularity"), ("title", "title"), ("bogus", "popularity")])
def test_current_sort(raw, expected):
    params = {} if raw is None else {"sort": raw}
    assert AllMoviesView.current_sort(RequestFactory().get("/", params)) == expected


# == Search ==


@pytest.mark.django_db
def test_search_watchlist_query_count(client, tmdb, rendered, user, django_assert_num_queries):
    for tmdb_id in (1, 2):
        Watchlist.objects.create(user=user, movie=Movies.objects.create(title=str(tmdb_id), tmdb_id=tmdb_id))
    client.force_login(user)

    # user, watchlist, then one movie query per entry: no select_related here (known N+1, out of scope)
    with django_assert_num_queries(4):
        client.get(reverse("movies-search"), {"q": ""})

    assert rendered[0].context == {"query": "", "results": []}


# == Topic of the Day ==


def test_topic_of_the_day_rotates_by_date():
    assert topic_of_the_day(datetime.date(2026, 1, 1)) == 3358
    assert topic_of_the_day(datetime.date(2026, 1, 2)) == 12570


def test_topic_of_the_day_defaults_to_today(fixed_today):
    assert topic_of_the_day() == 3358


# == Popular actors ==


@pytest.mark.parametrize("raw_page, requested", [(None, 1), ("abc", 1), ("3", 3)])
def test_popular_actors_page_param(client, tmdb, rendered, raw_page, requested):
    tmdb.get_popular_actors.return_value = {"actors": [], "current_page": requested}
    params = {} if raw_page is None else {"page": raw_page}

    client.get(reverse("popular-actors"), params)

    assert tmdb.get_popular_actors.call_args_list == [call(requested)]
    assert rendered[0].template == "movies/popular_actors.html"
    assert rendered[0].context == {"actors": [], "current_page": requested}


# == Home ==

HOME_LISTS = {
    "movie/now_playing": [1, 2, 3],
    "movie/upcoming": [3, 4, 5],
    "movie/popular": [2, 10],
    "movie/top_rated": [20],
    "tv/popular": [100],
}
HOME_TV_IDS = {"ko": 201, "ja": 202}  # dorama / anime by with_original_language; cartoon has none


def home_get_list(endpoint, page=1, ttl=None, **filters):
    if endpoint == "discover/movie":
        return {"results": [{"id": 1000 + filters["with_genres"]}]}
    if endpoint == "discover/tv":
        return {"results": [{"id": HOME_TV_IDS.get(filters.get("with_original_language"), 203)}]}
    return list_page(HOME_LISTS[endpoint])


def home_trending(media_type, time_window):
    if media_type == "person":
        return {
            "results": [
                {"id": 301, "known_for_department": "Acting"},
                {"id": 302, "known_for_department": "Directing"},
                {"id": 303},
            ]
        }
    if media_type == "movie":
        return {"results": [{"id": 77}, {"id": 78}]}
    first_id = 401 if time_window == "week" else 402  # trending/all/{week,day}
    return {"results": [{"id": first_id, "media_type": "movie", "title": f"Trending {time_window}"}]}


@pytest.fixture
def home_tmdb(tmdb, fixed_today):
    tmdb.get_list.side_effect = home_get_list
    tmdb.get_trending.side_effect = home_trending
    tmdb.get_list_with_trailers.return_value = [{"id": 1, "trailer": "hero"}]
    tmdb.get_genres.return_value = [{"id": 18, "name": "Drama"}, {"id": 35, "name": "Comedy"}, {"id": 1, "name": "X"}]
    tmdb.get_keyword.return_value = {"id": 3358, "name": "heist"}
    tmdb.get_keyword_movies.return_value = {"results": [{"id": 9}], "total_results": 42}
    tmdb.attach_trailers.side_effect = lambda items, media_type: [{**item, "trailer": "t"} for item in items]
    tmdb.get_details.return_value = {"id": 77, "title": "Movie of the Week"}
    return tmdb


@pytest.fixture
def home_rounds(mocker):
    """Record the task names of each fetch_parallel round (the real fetch_parallel still runs)."""
    rounds = []
    real = views.fetch_parallel

    def recording(tasks):
        rounds.append(list(tasks))
        return real(tasks)

    mocker.patch("movies.views.fetch_parallel", side_effect=recording)
    return rounds


FIRST_ROUND = [
    "hero_movies",
    "trending_all_week",
    "trending_all_day",
    "trending_movie_week",
    "trending_people",
    "now_playings",
    "upcoming",
    "tv_serials_popular",
    "now_popular",
    "top_rated",
    "movie_genres",
    "topic",
    "topic_movies",
    "mood:comedy",
    "mood:drama",
    "mood:thriller",
    "mood:horror",
    "mood:romance",
    "mood:scifi",
    "mood:action",
    "mood:fantasy",
    "mood:documentary",
    "mood:mystery",
    "tv:dorama",
    "tv:anime",
    "tv:cartoon",
]


def assert_same_calls(actual, expected):
    """Same calls, any order (fetch_parallel runs them in threads)."""
    assert len(actual) == len(expected)
    for expected_call in expected:
        assert expected_call in actual


@pytest.mark.django_db
def test_home_fetch_rounds(client, home_tmdb, home_rounds, rendered):
    client.get(reverse("movies-home"))

    assert home_rounds == [FIRST_ROUND, ["coming_soon", "motw"]]


@pytest.mark.django_db
def test_home_tmdb_calls(client, home_tmdb, home_rounds, rendered):
    client.get(reverse("movies-home"))

    mood_filters = {"sort_by": "popularity.desc", "vote_count.gte": 300}
    assert_same_calls(
        home_tmdb.get_list.call_args_list,
        [
            call("movie/now_playing", 1),
            call("movie/upcoming", 1),
            call("tv/popular", 1),
            call("movie/popular", 1),
            call("movie/top_rated", 1),
            *[
                call("discover/movie", 1, ttl=TTL_LIST, with_genres=genre_id, **mood_filters)
                for genre_id in (35, 18, 53, 27, 10749, 878, 28, 14, 99, 9648)
            ],
            call("discover/tv", 1, ttl=TTL_LIST, with_original_language="ko", without_genres=16, max_page=100),
            call(
                "discover/tv",
                1,
                ttl=TTL_LIST,
                with_genres=16,
                with_original_language="ja",
                with_origin_country="JP",
                max_page=100,
            ),
            call("discover/tv", 1, ttl=TTL_LIST, with_genres=16, with_origin_country="US|GB|FR|CA|AU", max_page=100),
        ],
    )
    assert_same_calls(
        home_tmdb.get_trending.call_args_list,
        [call("all", "week"), call("all", "day"), call("movie", "week"), call("person", "week")],
    )
    assert home_tmdb.get_list_with_trailers.call_args_list == [call("movie/popular", 1, "movie")]
    assert home_tmdb.get_genres.call_args_list == [call("movie")]
    assert home_tmdb.get_keyword.call_args_list == [call(3358)]
    assert home_tmdb.get_keyword_movies.call_args_list == [call(3358)]
    assert home_tmdb.attach_trailers.call_args_list == [call(list_page([4, 5])["results"], "movie")]
    assert home_tmdb.get_details.call_args_list == [call(77, "movie")]


@pytest.mark.django_db
def test_home_context(client, home_tmdb, home_rounds, rendered):
    client.get(reverse("movies-home"))

    assert rendered[0].template == "movies/home.html"
    context = rendered[0].context
    assert list(context) == [
        "hero_movies",
        "trending_all_week",
        "trending_all_day",
        "now_popular",
        "tv_serials_popular",
        "top_rated",
        "now_playings",
        "upcoming",
        "filtered_upcoming",
        "filtered_now_playings",
        "actors",
        "motw",
        "moods",
        "topic",
        "tv_showcase",
    ]
    row_keys = context.keys() - {"hero_movies", "motw", "moods", "topic", "tv_showcase"}
    ids = {key: [item["id"] for item in context[key]] for key in row_keys}
    assert context["hero_movies"] == [{"id": 1, "trailer": "hero"}]
    assert ids["trending_all_week"] == [401]
    assert ids["trending_all_day"] == [402]
    assert ids["now_popular"] == [2, 10]
    assert ids["tv_serials_popular"] == [100]
    assert ids["top_rated"] == [20]
    assert ids["now_playings"] == [1, 2, 3]
    assert ids["upcoming"] == [3, 4, 5]  # unfiltered
    assert ids["filtered_upcoming"] == [4, 5]  # minus now playing
    assert all(item["trailer"] == "t" for item in context["filtered_upcoming"])  # attach_trailers' result
    assert ids["filtered_now_playings"] == [1, 3]  # minus popular
    assert ids["actors"] == [301]  # Acting only
    assert context["motw"] == {"id": 77, "title": "Movie of the Week"}
    assert context["moods"] == [
        {"slug": "comedy", "genre_id": 35, "icon": "i-smile", "name": "Comedy", "items": [{"id": 1035}]},
        {"slug": "drama", "genre_id": 18, "icon": "i-masks", "name": "Drama", "items": [{"id": 1018}]},
    ]
    assert context["topic"] == {"id": 3358, "name": "heist", "movies": [{"id": 9}], "total": 42}
    assert context["tv_showcase"] == [
        {"slug": "tv", "label": "TV Shows", "url": "/movies/tv-popular/", "items": list_page([100])["results"]},
        {"slug": "dorama", "label": "Doramas", "url": "/movies/dorams-tv/", "items": [{"id": 201}]},
        {"slug": "anime", "label": "Anime", "url": "/movies/anime-tv/", "items": [{"id": 202}]},
        {"slug": "cartoon", "label": "Cartoons", "url": "/movies/cartoon-tv/", "items": [{"id": 203}]},
    ]


@pytest.mark.django_db
def test_home_coming_soon_takes_first_eight_upcoming(client, home_tmdb, home_rounds, rendered):
    long_upcoming = list_page(range(500, 512))
    home_tmdb.get_list.side_effect = lambda endpoint, page=1, ttl=None, **filters: (
        long_upcoming if endpoint == "movie/upcoming" else home_get_list(endpoint, page, ttl, **filters)
    )

    client.get(reverse("movies-home"))

    (sent, media_type), _ = home_tmdb.attach_trailers.call_args
    assert [item["id"] for item in sent] == list(range(500, 508))
    assert media_type == "movie"
    assert [item["id"] for item in rendered[0].context["filtered_upcoming"]] == list(range(500, 508))


@pytest.mark.django_db
def test_home_coming_soon_falls_back_when_attach_trailers_returns_nothing(client, home_tmdb, home_rounds, rendered):
    home_tmdb.attach_trailers.side_effect = None
    home_tmdb.attach_trailers.return_value = []

    client.get(reverse("movies-home"))

    assert rendered[0].context["filtered_upcoming"] == list_page([4, 5])["results"]


@pytest.mark.django_db
def test_home_motw_is_none_when_details_have_no_id(client, home_tmdb, home_rounds, rendered):
    home_tmdb.get_details.return_value = {}

    client.get(reverse("movies-home"))

    assert rendered[0].context["motw"] is None


@pytest.mark.django_db
def test_home_no_trending_movie_skips_motw_request(client, home_tmdb, home_rounds, rendered):
    home_tmdb.get_trending.side_effect = lambda media_type, window: (
        {"results": []} if media_type == "movie" else home_trending(media_type, window)
    )

    client.get(reverse("movies-home"))

    assert home_rounds[1] == ["coming_soon"]
    home_tmdb.get_details.assert_not_called()
    assert rendered[0].context["motw"] is None


@pytest.mark.django_db
def test_home_topic_requires_keyword_and_movies(client, home_tmdb, home_rounds, rendered):
    home_tmdb.get_keyword_movies.return_value = {"results": [], "total_results": 0}
    client.get(reverse("movies-home"))
    assert rendered[-1].context["topic"] is None

    home_tmdb.get_keyword_movies.return_value = {"results": [{"id": 9}]}
    home_tmdb.get_keyword.return_value = None
    client.get(reverse("movies-home"))
    assert rendered[-1].context["topic"] is None


@pytest.mark.django_db
def test_home_topic_total_missing(client, home_tmdb, home_rounds, rendered):
    home_tmdb.get_keyword_movies.return_value = {"results": [{"id": 9}]}

    client.get(reverse("movies-home"))

    assert rendered[0].context["topic"]["total"] is None


@pytest.mark.django_db
def test_home_failed_calls_give_empty_rows(client, home_tmdb, home_rounds, rendered):
    # fetch_parallel turns an exception into None; every row must survive that
    for method in ("get_list", "get_trending", "get_list_with_trailers", "get_genres", "get_keyword"):
        getattr(home_tmdb, method).side_effect = RuntimeError("TMDB down")
    home_tmdb.get_keyword_movies.side_effect = RuntimeError("TMDB down")

    client.get(reverse("movies-home"))

    context = rendered[0].context
    assert context["hero_movies"] == []
    assert context["now_playings"] == []
    assert context["filtered_upcoming"] == []
    assert context["actors"] == []
    assert context["motw"] is None
    assert context["moods"] == []
    assert context["topic"] is None
    assert [tab["items"] for tab in context["tv_showcase"]] == [[], [], [], []]
    assert home_rounds[1] == ["coming_soon"]
    assert home_tmdb.attach_trailers.call_args_list == [call([], "movie")]


@pytest.mark.django_db
def test_home_real_template_renders(client, home_tmdb):
    response = client.get(reverse("movies-home"))

    assert response.status_code == 200
    assert "Movie of the Week" in response.content.decode()


# == Detail ==

MOVIE_DETAILS = {
    "id": 5,
    "title": "Inception",
    "crew": {"director": ["Christopher Nolan", "Someone Else"], "writer": ["Nolan"]},
    "cast": [{"name": f"Actor {i}"} for i in range(15)],
    "trailer": {"key": "abc"},
    "backdrops": ["b1", "b2"],
    "posters": ["p1"],
    "recommendations": [{"id": 6}],
}


@pytest.fixture
def local_movie(db):
    return Movies.objects.create(title="Inception", tmdb_id=5, media_type="movie", country="US")


@pytest.fixture
def local_show(db):
    return Movies.objects.create(title="Show", tmdb_id=7, media_type="tv", country="US")


def detail(client, pk, media_type, **params):
    return client.get(reverse("movie-detail", args=[pk, media_type]), params)


@pytest.mark.django_db
def test_detail_movie_context(client, tmdb, rendered, local_movie, mocker):
    tmdb.get_details.return_value = dict(MOVIE_DETAILS)
    create = mocker.patch("movies.views.get_or_create_media")

    detail(client, 5, "movie")

    create.assert_not_called()  # the local row already exists
    assert tmdb.get_details.call_args_list == [call(5, "movie")]
    assert rendered[0].template == "movies/movies_detail.html"
    context = rendered[0].context
    assert list(context) == [
        "data",
        "details",
        "director",
        "crew",
        "cast",
        "trailer",
        "gallery",
        "posters",
        "recommendations",
        "no_collection",
        "movie",
        "movie_url",
        "form",
        "comment_max_length",
        "sort",
        "sort_options",
        "comments",
        "has_more",
        "total",
        "ratings_count",
    ]
    assert context["data"] == local_movie
    assert context["details"] == MOVIE_DETAILS
    assert context["director"] == {"name": "Christopher Nolan"}
    assert context["crew"] == MOVIE_DETAILS["crew"]
    assert context["cast"] == MOVIE_DETAILS["cast"][:12]
    assert context["trailer"] == {"key": "abc"}
    assert context["gallery"] == ["b1", "b2"]
    assert context["posters"] == ["p1"]
    assert context["recommendations"] == [{"id": 6}]
    assert context["no_collection"] is True
    assert context["movie"] == local_movie
    assert context["movie_url"] == "/movies/movie/5/movie/"
    assert context["sort"] == "new"
    assert context["sort_options"] == [("new", "Newest"), ("old", "Oldest")]
    assert context["comments"] == []
    assert context["has_more"] is False
    assert context["total"] == 0
    assert context["ratings_count"] == 0
    tmdb.get_collection.assert_not_called()
    tmdb.get_season.assert_not_called()


@pytest.mark.django_db
def test_detail_without_local_row_creates_it_from_details(client, tmdb, rendered, mocker, local_movie):
    tmdb.get_details.return_value = {**MOVIE_DETAILS, "id": 50}
    create = mocker.patch("movies.views.get_or_create_media", return_value=local_movie)

    detail(client, 50, "movie")

    assert create.call_args_list == [call(50, "movie", {**MOVIE_DETAILS, "id": 50})]
    assert rendered[0].context["data"] == local_movie


@pytest.mark.django_db
def test_detail_without_tmdb_details(client, tmdb, rendered, mocker):
    tmdb.get_details.return_value = {}
    create = mocker.patch("movies.views.get_or_create_media", return_value=None)

    detail(client, 50, "movie")

    assert create.call_args_list == [call(50, "movie", None)]
    context = rendered[0].context
    assert context == {
        "data": None,
        "details": None,
        "director": None,
        "crew": {},
        "cast": [],
        "trailer": None,
        "gallery": [],
        "posters": [],
        "recommendations": [],
    }
    tmdb.get_collection.assert_not_called()


@pytest.mark.django_db
def test_detail_no_director(client, tmdb, rendered, local_movie):
    tmdb.get_details.return_value = {**MOVIE_DETAILS, "crew": {"director": []}}

    detail(client, 5, "movie")

    assert rendered[0].context["director"] is None


@pytest.mark.django_db
def test_detail_collection(client, tmdb, rendered, local_movie):
    tmdb.get_details.return_value = {**MOVIE_DETAILS, "belongs_to_collection": {"id": 9, "name": "Saga"}}
    parts = [
        {"id": 1, "vote_average": 7.0, "vote_count": 10, "release_date": "2001-01-01"},
        {"id": 2, "vote_average": 9.0, "vote_count": 5, "release_date": ""},
        {"id": 3, "vote_average": 2.0, "vote_count": 0, "release_date": "2003-01-01"},
    ]
    tmdb.get_collection.return_value = {"id": 9, "parts": parts}

    detail(client, 5, "movie")

    assert tmdb.get_collection.call_args_list == [call(9)]
    context = rendered[0].context
    assert "no_collection" not in context
    assert context["collection"] == {
        "id": 9,
        "parts": parts,
        "rating_range": (7.0, 9.0),
        "released": [parts[0], parts[2]],
    }


@pytest.mark.django_db
def test_detail_collection_without_votes(client, tmdb, rendered, local_movie):
    tmdb.get_details.return_value = {**MOVIE_DETAILS, "belongs_to_collection": {"id": 9}}
    tmdb.get_collection.return_value = {"parts": [{"vote_average": 0, "vote_count": 0}]}

    detail(client, 5, "movie")

    assert rendered[0].context["collection"]["rating_range"] is None
    assert rendered[0].context["collection"]["released"] == []


@pytest.mark.django_db
def test_detail_collection_fetch_failed(client, tmdb, rendered, local_movie):
    tmdb.get_details.return_value = {**MOVIE_DETAILS, "belongs_to_collection": {"id": 9}}
    tmdb.get_collection.return_value = None

    detail(client, 5, "movie")

    assert rendered[0].context["collection"] is None
    assert "no_collection" not in rendered[0].context


SEASONS = [
    {"season_number": 0, "episode_count": 5, "air_date": "2000-01-01"},  # specials: skipped
    {"season_number": 1, "episode_count": 10, "air_date": "2020-01-01"},
    {"season_number": 2, "episode_count": 8, "air_date": "2024-01-01"},
    {"season_number": 3, "episode_count": 0, "air_date": None},  # announced, no episodes: skipped
    {"season_number": 4, "episode_count": 6, "air_date": "2030-01-01"},  # not aired yet
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "param, selected",
    [(None, 2), ("4", 4), ("1", 1), ("3", 2), ("0", 2), ("abc", 2), ("", 2)],
)
def test_detail_tv_seasons(client, tmdb, rendered, fixed_today, local_show, param, selected):
    tmdb.get_details.return_value = {"id": 7, "seasons": SEASONS, "belongs_to_collection": {"id": 1}}
    tmdb.get_season.return_value = {"season_number": selected, "episodes": []}
    params = {} if param is None else {"season": param}

    detail(client, 7, "tv", **params)

    context = rendered[0].context
    assert context["seasons"] == [SEASONS[1], SEASONS[2], SEASONS[4]]
    assert context["selected_season"] == selected
    assert context["season"] == {"season_number": selected, "episodes": []}
    assert tmdb.get_season.call_args_list == [call(7, selected)]
    tmdb.get_collection.assert_not_called()
    assert "no_collection" not in context


@pytest.mark.django_db
def test_detail_tv_no_aired_season_defaults_to_first(client, tmdb, rendered, fixed_today, local_show):
    tmdb.get_details.return_value = {
        "id": 7,
        "seasons": [
            {"season_number": 2, "episode_count": 3, "air_date": "2031-01-01"},
            {"season_number": 3, "episode_count": 3},
        ],
    }

    detail(client, 7, "tv")

    assert rendered[0].context["selected_season"] == 2
    assert tmdb.get_season.call_args_list == [call(7, 2)]


@pytest.mark.django_db
def test_detail_tv_without_seasons(client, tmdb, rendered, local_show):
    tmdb.get_details.return_value = {"id": 7, "seasons": [{"season_number": 0, "episode_count": 3}]}

    detail(client, 7, "tv")

    context = rendered[0].context
    assert context["seasons"] == []
    assert context["season"] is None
    assert "selected_season" not in context
    tmdb.get_season.assert_not_called()


@pytest.mark.django_db
def test_detail_tv_without_details_still_builds_seasons_context(client, tmdb, rendered, local_show):
    tmdb.get_details.return_value = {}

    detail(client, 7, "tv")

    assert rendered[0].context["seasons"] == []
    assert rendered[0].context["season"] is None


@pytest.mark.django_db
def test_detail_watchlist_state_for_logged_in_user(client, tmdb, rendered, local_movie, user, other_user):
    tmdb.get_details.return_value = dict(MOVIE_DETAILS)
    Rating.objects.create(movie=local_movie, user=other_user, score=4)
    Rating.objects.create(movie=local_movie, user=user, score=5)
    Watchlist.objects.create(user=other_user, movie=local_movie, watched=False)
    client.force_login(user)

    detail(client, 5, "movie")
    assert rendered[-1].context["watchlist_id"] is None
    assert rendered[-1].context["is_watched"] is False
    assert rendered[-1].context["ratings_count"] == 2

    entry = Watchlist.objects.create(user=user, movie=local_movie, watched=True)
    detail(client, 5, "movie")
    assert rendered[-1].context["watchlist_id"] == entry.id
    assert rendered[-1].context["is_watched"] is True


@pytest.mark.django_db
def test_detail_anonymous_has_no_watchlist_keys(client, tmdb, rendered, local_movie):
    tmdb.get_details.return_value = dict(MOVIE_DETAILS)

    detail(client, 5, "movie")

    assert "watchlist_id" not in rendered[0].context
    assert "is_watched" not in rendered[0].context


@pytest.mark.django_db
def test_detail_logged_in_query_count(client, tmdb, rendered, local_movie, user, django_assert_num_queries):
    tmdb.get_details.return_value = dict(MOVIE_DETAILS)
    client.force_login(user)

    # local row, user, comments window, comments total, ratings count, watchlist entry
    with django_assert_num_queries(6):
        detail(client, 5, "movie")


@pytest.mark.django_db
def test_detail_real_template_renders(client, tmdb, local_movie, user):
    tmdb.get_details.return_value = {**MOVIE_DETAILS, "belongs_to_collection": None}
    client.force_login(user)

    response = detail(client, 5, "movie")

    assert response.status_code == 200
    assert "Christopher Nolan" in response.content.decode()


# == AI ==


@pytest.fixture
def ai_task(mocker):
    task = mocker.patch("movies.views.get_ai_recommendation_task")
    task.delay.return_value.id = "task-123"
    return task


@pytest.mark.django_db
def test_ai_recomendations_requires_login(client, ai_task):
    response = client.get(reverse("ai-recomendations"), {"message": "hi"})

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))
    ai_task.delay.assert_not_called()


@pytest.mark.django_db
def test_ai_recomendations_enqueues_task(client, ai_task, user):
    client.force_login(user)

    response = client.get(reverse("ai-recomendations"), {"message": "something dark", "type": "tv"})

    assert response.status_code == 200
    assert response.json() == {"task_id": "task-123"}
    assert ai_task.delay.call_args_list == [call(user.id, "something dark", "tv")]


@pytest.mark.django_db
def test_ai_recomendations_defaults(client, ai_task, user):
    client.force_login(user)

    client.get(reverse("ai-recomendations"))

    assert ai_task.delay.call_args_list == [call(user.id, "", "all")]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "wait, minutes, retry_after", [(125, 2, 125), (10, 1, 10), (None, 60, 3600), (0, 60, 3600), (89.6, 1, 90)]
)
def test_ai_recomendations_throttled(client, ai_task, user, mocker, wait, minutes, retry_after):
    throttle = mocker.patch("movies.views.AIRecommendationThrottle").return_value
    throttle.allow_request.return_value = False
    throttle.wait.return_value = wait
    client.force_login(user)

    response = client.get(reverse("ai-recomendations"), {"message": "hi"})

    assert response.status_code == 429
    assert response.json() == {
        "error": f"AI request limit exceeded. Please try again in {minutes} minutes.",
        "retry_after": retry_after,
    }
    assert throttle.allow_request.call_args.kwargs == {"view": None}
    ai_task.delay.assert_not_called()


@pytest.mark.django_db
def test_ai_recomendations_real_throttle_limit(client, ai_task, user):
    client.force_login(user)

    statuses = [client.get(reverse("ai-recomendations"), {"message": "hi"}).status_code for _ in range(11)]

    assert statuses == [200] * 10 + [429]
    assert ai_task.delay.call_count == 10


@pytest.fixture
def async_result(mocker):
    return mocker.patch("movies.views.AsyncResult")


def status_url(task_id="task-123"):
    return reverse("ai-recommendation-status", args=[task_id])


@pytest.mark.django_db
def test_ai_status_requires_login(client, async_result):
    response = client.get(status_url())

    assert response.status_code == 302
    async_result.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["PENDING", "STARTED", "RETRY"])
def test_ai_status_pending(client, async_result, user, state):
    async_result.return_value.ready.return_value = False
    async_result.return_value.state = state
    client.force_login(user)

    response = client.get(status_url())

    assert async_result.call_args_list == [call("task-123")]
    assert response.json() == {"status": state.lower()}


@pytest.mark.django_db
def test_ai_status_done(client, async_result, user):
    async_result.return_value.ready.return_value = True
    async_result.return_value.successful.return_value = True
    async_result.return_value.result = {"recommendations": ["Heat"]}
    client.force_login(user)

    response = client.get(status_url())

    assert response.status_code == 200
    assert response.json() == {"status": "done", "result": {"recommendations": ["Heat"]}}


@pytest.mark.django_db
def test_ai_status_failed(client, async_result, user):
    async_result.return_value.ready.return_value = True
    async_result.return_value.successful.return_value = False
    async_result.return_value.result = RuntimeError("Groq is down")
    client.force_login(user)

    response = client.get(status_url())

    assert response.status_code == 200
    assert response.json() == {"status": "failed", "error": "Groq is down"}


# == get_or_create_media ==

TV_DATA = {
    "id": 1396,
    "name": "Breaking Bad",
    "overview": "Chemistry teacher.",
    "poster_path": "/bb.jpg",
    "first_air_date": "2008-01-20",
    "vote_average": 8.9,
    "origin_country": ["US", "GB", "US"],
    "production_companies": [{"name": "Sony"}, {"name": "AMC"}],
    "genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}],
}


@pytest.mark.django_db
def test_get_or_create_media_tv_branch(tmdb):
    tmdb.get_tv_by_tmdb_id.return_value = dict(TV_DATA)

    show = get_or_create_media(1396, "tv")

    tmdb.get_tv_by_tmdb_id.assert_called_once_with(1396)
    tmdb.get_movie_by_tmdb_id.assert_not_called()
    show.refresh_from_db()
    assert show.title == "Breaking Bad"
    assert show.description == "Chemistry teacher."
    assert show.poster_url == "https://image.tmdb.org/t/p/w500/bb.jpg"
    assert show.media_type == "tv"
    assert show.tmdb_rating == 8.9
    assert show.country == "United States, United Kingdom"
    assert show.author == "Sony"
    assert show.release_date == datetime.date(2008, 1, 20)
    assert sorted(show.genres.values_list("tmdb_id", flat=True)) == [18, 80]


@pytest.mark.django_db
def test_get_or_create_media_movie_countries_and_empty_fields(tmdb):
    data = {
        "title": "Amélie",
        "production_countries": [{"iso_3166_1": "FR"}, {"iso_3166_1": "DE"}],
        "poster_path": None,
        "production_companies": [],
    }

    movie = get_or_create_media(194, "movie", data)

    tmdb.get_movie_by_tmdb_id.assert_not_called()  # `data` was passed in
    movie.refresh_from_db()
    assert movie.title == "Amélie"
    assert movie.description == ""
    assert movie.poster_url == ""
    assert movie.media_type == "movie"
    assert movie.tmdb_rating is None
    assert movie.country == "France, Germany"
    assert movie.author == ""
    assert movie.release_date is None
    assert movie.genres.count() == 0


@pytest.mark.django_db
def test_get_or_create_media_missing_production_companies(tmdb):
    movie = get_or_create_media(195, "movie", {"title": "X"})

    assert movie.author == ""
    assert movie.country == ""


@pytest.mark.django_db
@pytest.mark.parametrize("raw_date", ["2020-13-45", "2020", "soon"])
def test_get_or_create_media_invalid_date(tmdb, raw_date):
    movie = get_or_create_media(196, "movie", {"title": "X", "release_date": raw_date})

    movie.refresh_from_db()
    assert movie.release_date is None


@pytest.mark.django_db
def test_get_or_create_media_empty_data_returns_none_without_fetch(tmdb):
    assert get_or_create_media(197, "movie", {}) is None
    tmdb.get_movie_by_tmdb_id.assert_not_called()
    assert not Movies.objects.exists()


@pytest.mark.django_db
def test_get_or_create_media_tv_fetch_returns_nothing(tmdb):
    tmdb.get_tv_by_tmdb_id.return_value = {}

    assert get_or_create_media(198, "tv") is None
    assert not Movies.objects.exists()


@pytest.mark.django_db
def test_get_or_create_media_existing_row_keeps_fields_but_resyncs_genres(tmdb):
    Genre.objects.create(tmdb_id=80, name="Old crime name")
    first = get_or_create_media(1396, "tv", dict(TV_DATA))

    second = get_or_create_media(
        1396,
        "tv",
        {
            **TV_DATA,
            "name": "Renamed",
            "first_air_date": "1990-01-01",
            "genres": [{"id": 80, "name": "Crime"}, {"id": 9648, "name": "Mystery"}],
        },
    )

    assert second.id == first.id
    second.refresh_from_db()
    assert second.title == "Breaking Bad"  # defaults only apply on create
    assert second.release_date == datetime.date(2008, 1, 20)  # only set when created
    assert sorted(second.genres.values_list("tmdb_id", flat=True)) == [80, 9648]
    assert Genre.objects.get(tmdb_id=80).name == "Old crime name"  # existing genre reused, not renamed
    assert Genre.objects.filter(tmdb_id=18).exists()  # dropped from the movie, not deleted
    assert Movies.objects.count() == 1


@pytest.mark.django_db
def test_get_or_create_media_query_counts(tmdb, django_assert_num_queries):
    data = {"title": "X", "release_date": "2001-02-03", "genres": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}

    # create: select + savepoint/insert/release for the row, save(), genres.clear(),
    # then per genre: select + savepoint/insert/release, exists(), add()
    with django_assert_num_queries(18):
        get_or_create_media(300, "movie", data)

    # repeat: select row, save(), genres.clear(), then per genre: select, exists(), add()
    with django_assert_num_queries(9):
        get_or_create_media(300, "movie", data)
