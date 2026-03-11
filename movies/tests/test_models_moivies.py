import pytest
from movies.models import Movies, Genre
import datetime

@pytest.fixture
def genre():
    genre1 = Genre.objects.create(name="Adventure")
    genre2 = Genre.objects.create(name="Fantasy")
    return genre1, genre2

@pytest.fixture
def movie():
    return Movies.objects.create(title="Hobbit", release_date=datetime.date(2012, 1, 1), country="New Zenland",  tmdb_rating=9.67)


@pytest.mark.django_db
def test_create_movie(movie, genre):
    
    genre1, genre2 = genre

    movie.genres.add(genre1, genre2)

    assert movie.title == "Hobbit"
    assert movie.release_date == datetime.date(2012, 1, 1)
    assert movie.country == "New Zenland"
    assert movie.tmdb_rating== 9.67
    assert movie.genres.count() == 2
    assert genre1 in movie.genres.all()
    assert genre2 in movie.genres.all()
    assert movie.media_type == "movie"


def test_dublicat_genres():
    Genre.objects.create(name="Adventure")
    with pytest.raises(Exception):
        Genre.objects.create(name="Adventure")
