"""Characterization tests for the watchlist views in users/views.py.

They pin the *current* behavior of search_watchlist, WatchlistView,
AddToWatchlist, DeleteWatchlist and toggle_watched before the users views
refactor: which rows each filter returns, what goes into the context, which
messages and redirects the plain-form path produces, and the JSON / HTMX
responses. Known bugs are pinned as they are and marked "Known bug, pinned as is";
fixing one is a behavior change, so its test is expected to change with it.
"""

import datetime

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from movies.models import Genre, Movies
from users.models import Watchlist

LOGIN_URL = reverse("login")
NOT_FOUND_MESSAGE = "Could not find data for this movie"


# == Fixtures and helpers ==


@pytest.fixture
def user(db):
    return User.objects.create_user(username="viewer", password="pass12345")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="other", password="pass12345")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


def make_movie(tmdb_id, title="Title", year=2012, country="", rating=None, genres=()):
    movie = Movies.objects.create(
        tmdb_id=tmdb_id,
        title=title,
        release_date=datetime.date(year, 1, 1) if year else None,
        country=country,
        tmdb_rating=rating,
    )
    for name in genres:
        genre, _ = Genre.objects.get_or_create(name=name)
        movie.genres.add(genre)
    return movie


def add(user, movie, watched=False):
    return Watchlist.objects.create(user=user, movie=movie, watched=watched)


def messages_of(response):
    return [(m.level_tag, m.message) for m in get_messages(response.wsgi_request)]


def ids(items):
    return sorted(item.id for item in items)


# == search_watchlist ==


@pytest.fixture
def search_rows(user, other_user):
    """Three entries of `user` plus one of `other_user` that matches every filter below."""
    alpha = add(
        user,
        make_movie(1, "Alpha", 2012, "United States of America, Canada", 7.0, ["Action"]),
    )
    beta = add(user, make_movie(2, "Beta Story", 2020, "Japan", 7.99, ["Comedy"]))
    gamma = add(user, make_movie(3, "Gamma", 2020, "France", 8.0, ["Horror"]))
    foreign = add(other_user, make_movie(4, "Alpha Beta", 2020, "Japan, Canada", 7.5, ["Action", "Comedy"]))
    return {"alpha": alpha, "beta": beta, "gamma": gamma, "foreign": foreign}


def search(client, **params):
    response = client.get(reverse("search_watchlist"), params)
    assert response.status_code == 200
    return response


@pytest.mark.django_db
def test_search_watchlist_requires_login(client):
    response = client.get(reverse("search_watchlist"))

    assert response.status_code == 302
    assert response.url.startswith(LOGIN_URL)


@pytest.mark.django_db
def test_search_watchlist_renders_partial_with_all_own_entries_when_no_filters(auth_client, search_rows):
    response = search(auth_client)

    assert [t.name for t in response.templates][0] == "users/partials/watchlist_result.html"
    rows = search_rows
    assert ids(response.context["watchlist"]) == ids([rows["alpha"], rows["beta"], rows["gamma"]])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params, expected",
    [
        ({"years_search": "2020"}, ["beta", "gamma"]),
        ({"years_search": "2012"}, ["alpha"]),
        ({"country_search": "canada"}, ["alpha"]),  # case-insensitive substring of a comma-joined value
        ({"country_search": "Japan"}, ["beta"]),
        ({"genre_search": "comedy"}, ["beta"]),
        ({"genre_search": "Horr"}, ["gamma"]),
        ({"name_search": "story"}, ["beta"]),
        ({"name_search": "a"}, ["alpha", "beta", "gamma"]),
        ({"years_search": "1999"}, []),
    ],
)
def test_search_watchlist_single_filter(auth_client, search_rows, params, expected):
    response = search(auth_client, **params)

    assert ids(response.context["watchlist"]) == ids(search_rows[name] for name in expected)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "rating, expected",
    [
        ("7", ["alpha", "beta"]),  # [7.0, 8.0): 7.0 and 7.99 are in, 8.0 is out
        ("7.0", ["alpha", "beta"]),
        ("8", ["gamma"]),
        ("7.5", ["beta", "gamma"]),  # [7.5, 8.5)
        ("6", []),
    ],
)
def test_search_watchlist_rating_is_a_half_open_range(auth_client, search_rows, rating, expected):
    response = search(auth_client, rating_search=rating)

    assert ids(response.context["watchlist"]) == ids(search_rows[name] for name in expected)


@pytest.mark.django_db
@pytest.mark.parametrize("rating", ["abc", "7,5", "seven"])
def test_search_watchlist_ignores_invalid_rating(auth_client, search_rows, rating):
    response = search(auth_client, rating_search=rating)

    assert ids(response.context["watchlist"]) == ids([search_rows["alpha"], search_rows["beta"], search_rows["gamma"]])


@pytest.mark.django_db
def test_search_watchlist_strips_whitespace(auth_client, search_rows):
    response = search(auth_client, name_search="  gamma  ", years_search=" 2020 ", rating_search=" 8 ")

    assert ids(response.context["watchlist"]) == [search_rows["gamma"].id]


@pytest.mark.django_db
def test_search_watchlist_blank_params_are_ignored(auth_client, search_rows):
    response = search(
        auth_client, years_search="   ", country_search="", genre_search=" ", rating_search="", name_search=""
    )

    assert response.context["watchlist"].count() == 3


@pytest.mark.django_db
def test_search_watchlist_combines_filters(auth_client, search_rows):
    response = search(auth_client, years_search="2020", genre_search="Comedy", rating_search="7", name_search="beta")

    assert ids(response.context["watchlist"]) == [search_rows["beta"].id]

    response = search(auth_client, years_search="2020", country_search="Canada")

    assert ids(response.context["watchlist"]) == []


@pytest.mark.django_db
def test_search_watchlist_excludes_other_users_entries(auth_client, search_rows):
    # The foreign entry matches all of these filters, but belongs to other_user.
    response = search(auth_client, name_search="Alpha Beta")

    assert ids(response.context["watchlist"]) == []


@pytest.mark.django_db
def test_search_watchlist_genre_substring_can_duplicate_rows(auth_client, user):
    # Known bug, pinned as is: genre_search joins the M2M with icontains, so a movie with
    # two matching genres comes back twice.
    entry = add(user, make_movie(10, "Two genres", genres=["Action", "Action & Adventure"]))

    response = search(auth_client, genre_search="Act")

    assert [item.id for item in response.context["watchlist"]] == [entry.id, entry.id]


# == WatchlistView ==


@pytest.mark.django_db
def test_watchlist_view_requires_login(client):
    response = client.get(reverse("watchlist"))

    assert response.status_code == 302
    assert response.url.startswith(LOGIN_URL)


@pytest.mark.django_db
def test_watchlist_view_lists_own_entries_newest_first(auth_client, user, other_user):
    first = add(user, make_movie(1, "First"))
    add(other_user, make_movie(2, "Foreign"))
    second = add(user, make_movie(3, "Second"))

    response = auth_client.get(reverse("watchlist"))

    assert response.status_code == 200
    assert "users/watchlist.html" in [t.name for t in response.templates]
    assert [item.id for item in response.context["watchlist"]] == [second.id, first.id]


@pytest.mark.django_db
def test_watchlist_view_paginates_by_20(auth_client, user):
    entries = [add(user, make_movie(i, f"Movie {i}")) for i in range(1, 26)]
    newest_first = [entry.id for entry in reversed(entries)]

    page_1 = auth_client.get(reverse("watchlist"))
    page_2 = auth_client.get(reverse("watchlist"), {"page": 2})

    assert page_1.context["is_paginated"] is True
    assert [item.id for item in page_1.context["watchlist"]] == newest_first[:20]
    assert [item.id for item in page_2.context["watchlist"]] == newest_first[20:]
    assert auth_client.get(reverse("watchlist"), {"page": 3}).status_code == 404


@pytest.mark.django_db
def test_watchlist_view_filter_options(auth_client, user):
    response = auth_client.get(reverse("watchlist"))

    assert response.context["years"] == range(2026, 2020, -1)
    assert list(response.context["years"]) == [2026, 2025, 2024, 2023, 2022, 2021]
    assert response.context["genres"] == ["Comedy", "Horror", "Adventure", "Action"]
    assert type(response.context["genres"]) is list
    assert response.context["countries"] == []


@pytest.mark.django_db
def test_watchlist_view_countries_are_split_stripped_deduplicated_and_sorted(auth_client, user, other_user):
    add(user, make_movie(1, country="United States of America, Canada"))
    add(user, make_movie(2, country="Canada"))
    add(user, make_movie(3, country=""))  # a blank value is skipped
    add(user, make_movie(4, country=" Japan ,France"))
    add(other_user, make_movie(5, country="Ukraine"))  # other users' countries are not offered

    response = auth_client.get(reverse("watchlist"))

    assert response.context["countries"] == ["Canada", "France", "Japan", "United States of America"]


@pytest.mark.django_db
def test_watchlist_view_countries_keep_empty_parts(auth_client, user):
    # Only a fully blank value is skipped; an empty part after a stray comma is kept as "".
    add(user, make_movie(1, country="Japan,"))

    response = auth_client.get(reverse("watchlist"))

    assert response.context["countries"] == ["", "Japan"]


@pytest.mark.django_db
def test_watchlist_view_countries_come_from_all_pages(auth_client, user):
    add(user, make_movie(1, country="Iceland"))  # oldest entry, so it lands on page 2
    for i in range(2, 22):
        add(user, make_movie(i, country="France"))

    response = auth_client.get(reverse("watchlist"))

    assert "Iceland" not in [item.movie.country for item in response.context["watchlist"]]
    assert response.context["countries"] == ["France", "Iceland"]


@pytest.mark.django_db
def test_watchlist_view_countries_query_is_distinct_and_unordered(auth_client, user):
    add(user, make_movie(1, country="France"))

    with CaptureQueriesContext(connection) as queries:
        auth_client.get(reverse("watchlist"))

    distinct = [q["sql"] for q in queries.captured_queries if "DISTINCT" in q["sql"]]
    assert len(distinct) == 1
    assert '"movies_movies"."country"' in distinct[0]
    assert "ORDER BY" not in distinct[0]


# == AddToWatchlist ==


@pytest.fixture
def media(mocker):
    """Patch users.views.get_or_create_media; set .return_value to the Movies row (or None)."""
    return mocker.patch("users.views.get_or_create_media")


def add_url(tmdb_id=1829, media_type="movie"):
    return reverse("add_watchlist", args=[tmdb_id, media_type])


@pytest.mark.django_db
def test_add_form_creates_entry_with_success_message_and_redirects_home(auth_client, user, media):
    media.return_value = movie = make_movie(1829, "Lord")

    response = auth_client.post(add_url(1829, "tv"))

    media.assert_called_once_with(1829, "tv")
    assert response.status_code == 302
    assert response.url == reverse("movies-home")
    assert Watchlist.objects.filter(user=user, movie=movie).count() == 1
    assert messages_of(response) == [("success", "Lord added to your watchlist")]


@pytest.mark.django_db
def test_add_form_existing_entry_gives_info_message(auth_client, user, media):
    media.return_value = movie = make_movie(1829, "Lord")
    add(user, movie)

    response = auth_client.post(add_url())

    assert response.status_code == 302
    assert Watchlist.objects.filter(user=user, movie=movie).count() == 1
    assert messages_of(response) == [("info", "Lord is already in your watchlist")]


@pytest.mark.django_db
def test_add_form_missing_movie_gives_error_message(auth_client, media):
    media.return_value = None

    response = auth_client.post(add_url(), {"next": "/somewhere/"})

    assert response.status_code == 302
    assert response.url == "/somewhere/"
    assert not Watchlist.objects.exists()
    assert messages_of(response) == [("error", NOT_FOUND_MESSAGE)]


@pytest.mark.django_db
def test_add_form_redirects_to_next(auth_client, media):
    media.return_value = make_movie(1829, "Lord")

    response = auth_client.post(add_url(), {"next": "/users/watchlist/"})

    assert response.url == "/users/watchlist/"


@pytest.mark.django_db
def test_add_form_blank_next_falls_back_to_home(auth_client, media):
    media.return_value = make_movie(1829, "Lord")

    response = auth_client.post(add_url(), {"next": ""})

    assert response.url == reverse("movies-home")


@pytest.mark.django_db
def test_add_form_ignores_referer_header(auth_client, media):
    # Known bug, pinned as is: the view reads META["HTTP-REFERER"] (dash), which is never set,
    # so without `next` it always goes home, even when the browser sent a Referer.
    media.return_value = make_movie(1829, "Lord")

    response = auth_client.post(add_url(), HTTP_REFERER="/search/?q=lord")

    assert response.url == reverse("movies-home")


@pytest.mark.django_db
def test_add_form_movie_without_title_raises(auth_client, media):
    # Known bug, pinned as is: `movie.title or movie.name`, and Movies has no `name` field.
    media.return_value = make_movie(1829, "")

    with pytest.raises(AttributeError):
        auth_client.post(add_url())


@pytest.mark.django_db
def test_add_json_repeat_returns_same_entry_not_created(auth_client, user, media):
    media.return_value = movie = make_movie(1829, "Lord")
    entry = add(user, movie)

    response = auth_client.post(add_url(), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "in_watchlist": True,
        "created": False,
        "watchlist_id": entry.id,
        "remove_url": reverse("delete_watchlist", args=[entry.id]),
    }
    assert Watchlist.objects.count() == 1
    assert messages_of(response) == []


@pytest.mark.django_db
def test_add_json_missing_movie_is_404(auth_client, media):
    media.return_value = None

    response = auth_client.post(add_url(), {"next": "/somewhere/"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": NOT_FOUND_MESSAGE}
    assert not Watchlist.objects.exists()
    assert messages_of(response) == []


@pytest.mark.django_db
def test_add_get_is_not_allowed(auth_client, media):
    response = auth_client.get(add_url())

    assert response.status_code == 405
    media.assert_not_called()


# == DeleteWatchlist ==


def delete_url(entry):
    return reverse("delete_watchlist", args=[entry.id])


@pytest.mark.django_db
def test_delete_htmx_returns_empty_200(auth_client, user):
    entry = add(user, make_movie(1))

    response = auth_client.delete(delete_url(entry), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert response.content == b""
    assert not Watchlist.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
def test_delete_json_wins_over_htmx(auth_client, user):
    entry = add(user, make_movie(1))

    response = auth_client.delete(delete_url(entry), HTTP_HX_REQUEST="true", HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    assert response.json() == {"ok": True, "in_watchlist": False}


@pytest.mark.django_db
def test_delete_plain_redirects_to_watchlist(auth_client, user):
    entry = add(user, make_movie(1))

    response = auth_client.delete(delete_url(entry))

    assert response.status_code == 302
    assert response.url == reverse("watchlist")
    assert not Watchlist.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
def test_delete_other_users_entry_is_404(auth_client, other_user):
    entry = add(other_user, make_movie(1))

    response = auth_client.delete(delete_url(entry))

    assert response.status_code == 404
    assert Watchlist.objects.filter(id=entry.id).exists()


@pytest.mark.django_db
def test_delete_requires_login(client, user):
    entry = add(user, make_movie(1))

    response = client.delete(delete_url(entry))

    assert response.status_code == 302
    assert response.url.startswith(LOGIN_URL)
    assert Watchlist.objects.filter(id=entry.id).exists()


# == toggle_watched ==


def toggle_url(entry_id):
    return reverse("toggle-watchlist", args=[entry_id])


@pytest.mark.django_db
def test_toggle_post_flips_watched_back_and_forth(auth_client, user):
    entry = add(user, make_movie(1), watched=False)

    first = auth_client.post(toggle_url(entry.id))
    entry.refresh_from_db()
    assert (first.status_code, first.content, entry.watched) == (200, b"OK", True)

    second = auth_client.post(toggle_url(entry.id))
    entry.refresh_from_db()
    assert (second.status_code, second.content, entry.watched) == (200, b"OK", False)


@pytest.mark.django_db
def test_toggle_get_returns_no_response(auth_client, user):
    # Known bug, pinned as is: GET falls through and returns None -> 500, not 405.
    entry = add(user, make_movie(1), watched=False)

    with pytest.raises(ValueError, match="didn't return an HttpResponse"):
        auth_client.get(toggle_url(entry.id))

    entry.refresh_from_db()
    assert entry.watched is False


@pytest.mark.django_db
def test_toggle_other_users_or_missing_entry_raises(auth_client, other_user):
    # Known bug, pinned as is: Watchlist.objects.get(...) instead of get_object_or_404 -> 500, not 404.
    entry = add(other_user, make_movie(1), watched=False)

    with pytest.raises(Watchlist.DoesNotExist):
        auth_client.post(toggle_url(entry.id))
    with pytest.raises(Watchlist.DoesNotExist):
        auth_client.post(toggle_url(entry.id + 1000))

    entry.refresh_from_db()
    assert entry.watched is False


@pytest.mark.django_db
def test_toggle_requires_login(client, user):
    entry = add(user, make_movie(1))

    response = client.post(toggle_url(entry.id))

    assert response.status_code == 302
    assert response.url.startswith(LOGIN_URL)
