from django.urls import path
from .views import (
    MovieListView, 
    MovieDetailView,
    ProfileView,
    WatchlistListView,
    WatchlistDetailView,
    RatingView,
    GenreListView)


urlpatterns = [
    path('movie/', MovieListView.as_view(), name='movie-list'),
    path('movie/<int:pk>/', MovieDetailView.as_view(), name='movie-datail'),
    path('genre/', GenreListView.as_view(), name='genre'),
    path('rating/', RatingView.as_view(), name='rating'),

    path('profile/', ProfileView.as_view(), name='profile'),
    path('watchlist/', WatchlistListView.as_view(), name='watchlist'),
    path('watchlist/<int:pk>/', WatchlistDetailView.as_view(), name='watchlist-detail')
]