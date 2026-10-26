import pytest
import requests
from django.urls import reverse

from movies.redis_services import TMDBFetchError
from movies.tmdb_service import TMDBClient

URL = "search-suggest"


def test_short_query_returns_empty_without_tmdb(client, mocker):
    suggest = mocker.patch.object(TMDBClient, "suggest")
    resp = client.get(reverse(URL), {"q": "a"})
    assert resp.json() == {"results": []}
    suggest.assert_not_called()


def test_returns_serialized_results(client, mocker):
    mocker.patch.object(
        TMDBClient,
        "suggest",
        return_value=[
            {
                "id": 603,
                "media_type": "movie",
                "title": "The Matrix",
                "release_date": "1999-03-31",
                "poster_url": "https://image.tmdb.org/t/p/w500/x.jpg",
                "vote_average": 8.24,
            }
        ],
    )
    data = client.get(reverse(URL), {"q": "matrix"}).json()
    assert data["results"] == [
        {
            "title": "The Matrix",
            "year": "1999",
            "media_type": "movie",
            "poster_url": "https://image.tmdb.org/t/p/w500/x.jpg",
            "rating": 8.2,
            "url": reverse("movie-detail", args=[603, "movie"]),
        }
    ]


def test_no_matches_is_empty_list(client, mocker):
    mocker.patch.object(TMDBClient, "suggest", return_value=[])
    resp = client.get(reverse(URL), {"q": "zzzzzz"})
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


@pytest.mark.parametrize("exc", [TMDBFetchError([]), requests.ConnectionError()])
def test_tmdb_failure_is_502(client, mocker, exc):
    mocker.patch.object(TMDBClient, "suggest", side_effect=exc)
    assert client.get(reverse(URL), {"q": "matrix"}).status_code == 502
