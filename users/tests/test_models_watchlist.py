import pytest
from users.models import Watchlist
from movies.models import Movies
from django.contrib.auth.models import User



@pytest.fixture
def user():
    return User.objects.create_user(username="Kolya", password="test123")

@pytest.fixture
def movie():
    return Movies.objects.create(title="The Lord of the Rings")


@pytest.mark.django_db
def test_watchlist_created(user, movie):

    watchlist = Watchlist.objects.create(user=user, movie=movie)

    assert watchlist.user.username == "Kolya"
    assert watchlist.movie.title ==  "The Lord of the Rings"
    assert watchlist.watched == False


@pytest.mark.django_db
def test_watchlist_dublicat(user, movie):

    # Create a record in the database
    Watchlist.objects.create(user=user, movie=movie)

    # we are trying to create the same record
    with pytest.raises(Exception):
        Watchlist.objects.create(user=user, movie=movie) #  should fall with an error