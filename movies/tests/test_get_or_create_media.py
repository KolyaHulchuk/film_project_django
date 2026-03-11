import pytest
from movies.views import get_or_create_media
from unittest.mock import MagicMock
from movies.models import Movies
import datetime


@pytest.fixture
def db():
    return Movies.objects.create(title="Berserk", release_date=datetime.date(1997, 1, 1), country="American", tmdb_id=12)


@pytest.fixture
def tmdb(mocker):
    fake_client = MagicMock()

    mocker.patch("movies.views.TMDBClient", return_value=fake_client)

    fake_client.get_movie_by_tmdb_id.return_value = { "id": 550,
            "original_language": "en",
            "original_title": "Fight Club",
            "overview": "A ticking-time-bomb insomniac and a slippery soap salesman channel primal male aggression into a shocking new form of therapy. Their concept catches on, with underground \"fight clubs\" forming in every town, until an eccentric gets in the way and ignites an out-of-control spiral toward oblivion.",
            "popularity": 73.433,
            "poster_path": "/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
            "release_date": "1999-10-15",
            "title": "Fight Club",
            "video": False,
            "vote_average": 8.433,
            "vote_count": 26279
            }
    
    fake_client.get_tv_by_tmdb_id.return_value = { "id": 1396,
                        "origin_country": ["US"],
                        "original_language": "en",
                        "original_name": "Breaking Bad",
                        "overview": "When Walter White, a New Mexico chemistry teacher, is diagnosed with Stage III cancer and given a prognosis of only two years left to live. He becomes filled with a sense of fearlessness and an unrelenting desire to secure his family's financial future at any cost as he enters the dangerous world of drugs and crime.",
                        "popularity": 298.884,
                        "poster_path": "/ggFHVNu6YYI5L9pCfOacjizRGt.jpg",
                        "first_air_date": "2008-01-20",
                        "name": "Breaking Bad",
                        "vote_average": 8.879,
                        "vote_count": 11536
                    }
                                

    return fake_client




@pytest.mark.django_db
def test_dublicate(tmdb, db):
    

    result = get_or_create_media(12, "movie")
    result2 = get_or_create_media(12, "movie")
    assert result.title == "Berserk"
    assert Movies.objects.count() == 1
    

@pytest.mark.django_db
def test_create(tmdb, db):


    result = get_or_create_media(39, "movie")
    result_tv = get_or_create_media(40, "tv")

    

    assert result.title == "Fight Club"
    assert result_tv.title == "Breaking Bad"

    assert Movies.objects.count() == 3

    tmdb.get_movie_by_tmdb_id.assert_called_once_with(39)
    tmdb.get_tv_by_tmdb_id.assert_called_once_with(40)



@pytest.mark.django_db
def test_return_none(tmdb, db):
    tmdb.get_movie_by_tmdb_id.return_value = None

    result = get_or_create_media(99, "movie")

    assert result is None


