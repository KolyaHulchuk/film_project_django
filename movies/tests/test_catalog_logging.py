"""Catalog timings go to the "movies.views" logger at DEBUG (shown with LOG_LEVEL=DEBUG), not to stdout."""

import logging
from unittest.mock import MagicMock

import pytest
from django.http import HttpResponse
from django.urls import reverse


@pytest.fixture
def catalog_tmdb(mocker):
    client = MagicMock()
    client.get_list.return_value = {"page": 1, "total_pages": 1, "total_results": 1, "results": [{"id": 1}]}
    client.get_genres.return_value = []
    client.annotate_items.side_effect = lambda items, media_type, genres: [dict(item) for item in items]
    mocker.patch("movies.views.TMDBClient", return_value=client)
    mocker.patch("movies.views.render", return_value=HttpResponse("rendered"))
    return client


@pytest.mark.django_db
def test_catalog_timings_are_debug_logs_not_prints(client, catalog_tmdb, caplog, capsys):
    caplog.set_level(logging.DEBUG, logger="movies.views")

    client.get(reverse("popular-movies"))

    timings = [r.getMessage() for r in caplog.records if r.name == "movies.views" and r.levelno == logging.DEBUG]
    assert [t.split(":")[0] for t in timings] == [
        "[timing] item_func/get_list",
        "[timing] get_genres",
        "[timing] annotate_items",
        "[timing] render",
        "[timing] AllMoviesView.get total",
    ]
    assert "[timing]" not in capsys.readouterr().out


@pytest.mark.django_db
def test_catalog_timings_are_hidden_at_the_default_info_level(client, catalog_tmdb, caplog):
    caplog.set_level(logging.INFO, logger="movies.views")

    client.get(reverse("popular-movies"))

    assert not [r for r in caplog.records if r.name == "movies.views"]
