import pytest
from unittest.mock import MagicMock
from movies.models import Movies
from users.models import Watchlist
from django.contrib.auth.models import User
import datetime


@pytest.fixture
def db_movie():
    return Movies.objects.create(title="Pirates of the Caribbean",  release_date=datetime.date(2001, 1, 1), country="American", tmdb_id=22)


@pytest.fixture
def user():
    return User.objects.create_user(username="Kolya", password="test123")


@pytest.fixture
def tmdb(mocker):
    fake_client = MagicMock()

    mocker.patch("movies.views.TMDBClient", return_value=fake_client)

    fake_client.search_movies.return_value = [{'adult': False,
                                               'backdrop_path': '/uRNgkJSkNBFbbn9fPsEjDIy8Sh3.jpg',
                                               'id': 22, 
                                               'title': 'Pirates of the Caribbean: The Curse of the Black Pearl', 
                                               'original_title': 'Pirates of the Caribbean: The Curse of the Black Pearl', 
                                               'media_type': "movies"
                                               }]
    return fake_client



@pytest.mark.django_db
def test_search_view(client, tmdb, db_movie):

    


    response = client.get("/movies/search/", {"q": "Pirates of the Caribbean"})

    templates = [t.name for t in response.templates]

    assert response.status_code == 200
    assert "movies/search.html" in templates   
    assert "movies/base.html" in templates
    assert "results" in response.context



    response = client.get("/movies/search/", {"q": "Pirates of the Caribbean"})

    templates = [t.name for t in response.templates]

    assert response.status_code == 200
    assert "movies/search.html" in templates   
    assert "movies/base.html" in templates
    assert "results" in response.context

   

@pytest.mark.django_db
def test_empty_quert(client, db_movie):
    response = client.get("/movies/search/", {"q": ""})

    assert response.context["results"] == []



@pytest.mark.django_db
def test_not_auth_user(client, db_movie):
    response = client.get("/movies/search/", {"q": "Pirates of the Caribbean"})

    assert response.status_code == 200
    

@pytest.mark.django_db
def test_search_with_watchlist(client, tmdb, db_movie, user):
    Watchlist.objects.create(user=user, movie=db_movie, watched=True)

    client.login(username="Kolya", password="test123")  

    response = client.get("/movies/search/", {"q": "Pirates"})

    movie = response.context["results"][0]

    assert movie.is_watched == True
    
    # if a film is in both the local database and TMDB, it should only appear once:
    assert len(response.context["results"]) == 1  


