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
    path('movie/', MovieListView.as_view(), name='api-movie-list'),
    path('movie/<int:pk>/', MovieDetailView.as_view(), name='api-movie-datail'),
    path('genre/', GenreListView.as_view(), name='api-genre'),
    path('rating/', RatingView.as_view(), name='api-rating'),

    path('profile/', ProfileView.as_view(), name='api-profile'),
    path('watchlist/', WatchlistListView.as_view(), name='api-watchlist'),
    path('watchlist/<int:pk>/', WatchlistDetailView.as_view(), name='api-watchlist-detail')
]