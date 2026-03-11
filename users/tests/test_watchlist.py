import pytest
from django.contrib.auth.models import User
from movies.models import Movies, Genre
from users.models import Watchlist
from users.views import AddToWatchlist
import datetime



@pytest.fixture
def movie():
    movie =  Movies.objects.create(title="Lord of the ring", media_type="movie", tmdb_id=1829,  release_date=datetime.date(2012, 1, 1), tmdb_rating=9.87, country="New Zenland")
    genre = Genre.objects.create(name="Action")
    movie.genres.add(genre)
    return movie

@pytest.fixture
def user():
    return User.objects.create_user(username="Kolya", password="Password_123")


@pytest.fixture
def login(client, user):
    return client.login(username="Kolya", password="Password_123")

@pytest.fixture
def watchlist(client, user, movie):
    return  Watchlist.objects.create(user=user, movie=movie, watched=False)




@pytest.mark.django_db
def test_add_watchlist(client, mocker, user, movie, login):

    mock_get = mocker.patch("users.views.get_or_create_media", return_value=movie)


    response = client.post("/users/watchlist/add/1829/movie")
    response = client.post("/users/watchlist/add/1829/movie")


    assert response.status_code == 302
    mock_get.assert_called_with(1829, "movie")

    assert Watchlist.objects.count() == 1


@pytest.mark.django_db
def test_add_watchlist_without_login(client, mocker,  movie):

    mocker.patch("users.views.get_or_create_media", return_value=movie)


    response = client.post("/users/watchlist/add/1829/movie")
    response = client.post("/users/watchlist/add/1829/movie")


    assert response.status_code == 302
    assert "/login/" in response.url



@pytest.mark.django_db
def test_toggle_watchlist(client, user, movie, login, watchlist):
    response = client.post("/users/watchlist/toggle/1")

    assert response.status_code == 200
    assert response.content == b"OK"
    
    item = Watchlist.objects.get(id=1)
    assert item.watched == True



@pytest.mark.django_db
def test_search_watchlist(client,  movie, user, login, watchlist):

    response = client.get("/users/watchlist/search/", {"genre_search": "Action"})

    # Rewrite the answer Drama is not in the genres, so we won't write anything in the database.
    response = client.get("/users/watchlist/search/", {"genre_search": "Drama"}) 


    assert response.status_code == 200
    assert "watchlist" in response.context
    assert response.context["watchlist"].count() == 0



@pytest.mark.django_db
def test_delete_watchlist(client, login, user, movie, watchlist):


    response = client.delete("/users/watchlist/delete/1")

    assert response.status_code == 302
    assert Watchlist.objects.count() == 0


@pytest.mark.django_db
def test_watchlist_view(client, login, user, movie, watchlist):
    response = client.get("/users/watchlist/")

    assert "years" in response.context
    assert "genres" in response.context
    assert response.status_code == 200