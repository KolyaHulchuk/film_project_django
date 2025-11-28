from django.urls import path
from . import views
from .views import  (
    MoviesDetailView,
    PopularMoviesView,
    NowPlayingsView,
    UpcomingView,
    TopRatedView,
    TVPopularView,
    HomeView,
    SerachView
    )



urlpatterns = [
    path('', HomeView.as_view(), name='movies-home' ),  # це створення шляху
    path('movies/<int:pk>/', MoviesDetailView.as_view(), name='movies-detail'),
    path('about/', views.about, name='movies-about'),
    path("search/", SerachView.as_view(), name="movies-search"),
    path("popular-movies/", PopularMoviesView.as_view(), name="popular-movies"),
    path("tv-popular/", TVPopularView.as_view(), name="popular-tv"),
    path("top-rated/", TopRatedView.as_view(), name="top-rated"),
    path("now-playings/", NowPlayingsView.as_view(), name="now-playings"),
    path("upcoming/", UpcomingView.as_view(), name="upcoming"),
]

