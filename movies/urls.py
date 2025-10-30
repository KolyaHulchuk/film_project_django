from django.urls import path
from . import views
from .views import  MoviesDetailView



urlpatterns = [
    path('', views.home, name='movies-home' ),  # це створення шляху
    path('movies/<int:pk>/', MoviesDetailView.as_view(), name='movies-detail'),
    path('about/', views.about, name='movies-about'),
    path("search/", views.search, name="movies-search"),
    path("popular-movies/", views.popular_movies_view, name="popular-movies"),
    path("tv-popular/", views.tv, name="popular-tv"),
    path("top-rated/", views.top_rated_view, name="top-rated"),
    path("now-playings/", views.now_playings_view, name="now-playings"),
    path("upcoming/", views.upcoming_view, name="upcoming")
]

