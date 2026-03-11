import pytest
import requests
from unittest.mock import MagicMock
from movies.tmdb_service import TMDBClient


@pytest.fixture
def valeu():
    return {
        "page": 1,
        "results": [
                {
                "adult": False,
                "backdrop_path": "/bsNm9z2TJfe0WO3RedPGWQ8mG1X.jpg",
                "genre_ids": [
                    18,
                    80
                ],
                "id": 1396,
                "origin_country": [
                    "US"
                ],
                "original_language": "en",
                "original_name": "Breaking Bad",
                "overview": "When Walter White, a New Mexico chemistry teacher, is diagnosed with Stage III cancer and given a prognosis of only two years left to live. He becomes filled with a sense of fearlessness and an unrelenting desire to secure his family's financial future at any cost as he enters the dangerous world of drugs and crime.",
                "popularity": 298.884,
                "poster_path": "/ggFHVNu6YYI5L9pCfOacjizRGt.jpg",
                "first_air_date": "2008-01-20",
                "name": "Breaking Bad",
                "media_type": "tv",
                "vote_average": 8.879,
                "vote_count": 11536
                },

                {
                "id": 1396,
                "name": "Game of Throne",
                "media_type": "tv"
                }
            ],
            "total_pages": 110,
            "total_results": 1
        }


@pytest.fixture
def item_value():
    return [ {'adult': False, 
            'backdrop_path': '/uHZRTGMFb1RLmgWcqlIOZsGbDCT.jpg', 
            'id': 4247, 
            'title': 'Scary Movie', 
            'original_title': 'Scary Movie', 
            'overview': 'A familiar-looking group of teenagers find themselves being stalked by a more-than-vaguely recognizable masked killer! As the victims begin to pile up and the laughs pile on, none of your favorite scary movies escape the razor-sharp satire of this outrageously funny parody!', 
            'poster_path': '/fVQFPRuw3yWXojYDJvA5EoFjUOY.jpg', 
            'media_type': 'movie', 
            'original_language': 'en', 
            'genre_ids': [35], 
            'popularity': 41.8587, 
            'release_date': '2000-07-07',
            'video': False, 
            'vote_average': 6.384, 
            'vote_count': 7573, 
            'poster_url': 'https://image.tmdb.org/t/p/w500/fVQFPRuw3yWXojYDJvA5EoFjUOY.jpg', 
            'rating': 6.384
            } ]



@pytest.fixture
def mock(mocker):
    return mocker.patch("movies.tmdb_service.requests.get")

@pytest.fixture
def tmdb_client():
    return TMDBClient(api_key="test_key", languages=["en"])



def test_request(mock, valeu, tmdb_client):

    mock.return_value.status_code = 200
    mock.return_value.json.return_value = valeu

    

    result = tmdb_client._request("movie/15", {})

    assert result == valeu



def test_error_request(mock, tmdb_client):
    mock.return_value.status_code = 404

    result = tmdb_client._request("movie/16", {})

    assert result == {}





def test_genres(mocker, tmdb_client):
    # Use patch.object when you want to replace a method on a specific instance that you already have.
    # patch.object  - specify the object itself and the method name
    mock_request = mocker.patch.object(tmdb_client, "_request", return_value={"genres": [{"id": 1, "name": "Action"}]} )

    result = tmdb_client.get_genres("movie")

    assert result == [{"id": 1, "name": "Action"}]
    mock_request.assert_called_once_with("genre/movie/list")





def test_type_items(tmdb_client, item_value):

    result = tmdb_client._type_items(item_value)

    assert result[0]["title"] == "Scary Movie"


def test_get_list(mocker, tmdb_client, valeu):

    mocker.patch.object(tmdb_client, "_request", return_value=valeu)

    result = tmdb_client.get_list("movie/", max_page=10)

    assert len(result["results"]) == 1
    assert result["page"] == 1
    assert result["total_pages"] == 10



def test_get_list_without_data(mocker, tmdb_client):

    mocker.patch.object(tmdb_client, "_request", return_value={})

    result = tmdb_client.get_list("movie/", max_page=10)

    assert len(result["results"]) == 0
    assert result["page"] == 1
    assert result["total_pages"] == 1



def test_search_movies(mocker, tmdb_client, valeu):

    mocker.patch.object(tmdb_client, "_request", return_value=valeu)

    result = tmdb_client.search_movies("Breaking Bad")


    assert result[0]["title"] == "Breaking Bad"
    assert len(result) == 1 # duplicate check


@pytest.mark.parametrize("details, media_type", [({"release_date": "2008-01-20"}, "movie"), ({"first_air_date": "2008-01-20"}, "tv")])
def test_get_release_date(details, media_type, tmdb_client):

    assert tmdb_client.get_release_date(details, media_type) ==  "20.01.2008"





def test_get_release_date_invalid(tmdb_client):

    with pytest.raises(ValueError):
        tmdb_client.get_release_date({"release_date": "invalid_date"}, "movie")