import pytest
from django.test import RequestFactory
from unittest.mock import MagicMock
from movies.views import AllMoviesView

@pytest.fixture
def tmdb(mocker):
    fake_client = MagicMock()
    mocker.patch("movies.views.TMDBClient", return_value=fake_client)

    fake_client.get_list.return_value = {
        "results": [{"id": 1, "title": "Hobbit", "media_type": "movie"}],
        "total_pages": 1,
        "page": 1
    }

    fake_client.enrich_items.return_value = [{"id": 1, "title": "Hobbit", "media_type": "movie"}]
    fake_client.get_genres.return_value = [
        {"id": 1, "name": "Adventure"},
        {"id": 2, "name": "Fantasy"}
    ]
    
    return fake_client



@pytest.mark.django_db
@pytest.mark.parametrize("url, title, template", [
    ("/movies/anime-tv/", "Anime TV", "movies/type/anime.html"),
    ("/movies/dorams-tv/", "Dorams TV", "movies/type/dorams.html"),
    ("/movies/cartoon-tv/", "Cartoon TV", "movies/type/cartoons.html"),
    ("/movies/tv/", "TV", "movies/type/tv.html"),
    ("/movies/movie/", "Movie", "movies/type/movie.html"),
    ("/movies/popular-movies/", "Popular Movies", "movies/category/popular.html"),
    ("/movies/tv-popular/", "Popular Tv", "movies/category/tv.html"),
    ("/movies/top-rated/", "Top rated", "movies/category/top_rated.html"),
    ("/movies/now-playings/", "Now Playings", "movies/category/now_playings.html"),
    ("/movies/upcoming/", "Upcoming", "movies/category/upcoming.html")
])
def test_allmoviews_view(client, tmdb, url, title, template):
    response = client.get(url)

    templates = [t.name for t in response.templates]

    assert response.status_code == 200

    assert template in templates # checks what templates are available 

    assert "items" in response.context #  checks the data that view passes to the template
    assert "title" in response.context 
    assert "countries" in response.context
    assert "genres" in response.context
    assert response.context["title"] == title
    assert response.context["items"] == [{"id": 1, "title": "Hobbit", "media_type": "movie"}]
    assert response.context["genres"] == [{'id': 1, 'name': 'Adventure'}, {'id': 2, 'name': 'Fantasy'}]

    assert title in response.content.decode() # content - checks that the data is actually displayed on the page
    assert "Hobbit" in response.content.decode() # decode - converts to bytes, otherwise it won't work








def test_search_filter_movie():
    view = AllMoviesView()

    request = RequestFactory().get("/", {"years_search": "2020"})

    filter = view.search_filter_movie(request)

    assert filter["primary_release_year"] == "2020"



