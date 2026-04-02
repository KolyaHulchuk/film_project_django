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
    SerachView,
    AnimeTVView,
    DoramTVView,
    CartoonTVView,
    TVViews,
    MovieView,
    PopularActorView,
    ai_recomendations,
    )



urlpatterns = [
    path('', HomeView.as_view(), name='movies-home' ), 
    path('movie/<int:pk>/<str:media_type>/', MoviesDetailView.as_view(), name='movie-detail'),
    path("search/", SerachView.as_view(), name="movies-search"),

    path("popular-movies/", PopularMoviesView.as_view(), name="popular-movies"),
    path("tv-popular/", TVPopularView.as_view(), name="popular-tv"),
    path("top-rated/", TopRatedView.as_view(), name="top-rated"),
    path("now-playings/", NowPlayingsView.as_view(), name="now-playings"),
    path("upcoming/", UpcomingView.as_view(), name="upcoming"),

    path("anime-tv/", AnimeTVView.as_view(), name="anime-tv"),
    path("dorams-tv/", DoramTVView.as_view(), name="dorams-tv"),
    path("cartoon-tv/", CartoonTVView.as_view(), name="cartoon-tv"),
    path("tv/", TVViews.as_view(), name="tv"),
    path("movie/", MovieView.as_view(), name="movie"),

    path("ai/", ai_recomendations, name='ai-recomendations'),

    path('popular-actors/', PopularActorView.as_view(), name="popular-actors")
    
]

