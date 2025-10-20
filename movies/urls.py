from django.urls import path
from . import views
from .views import  MoviesDetailView



urlpatterns = [
    path('', views.home, name='movies-home' ),  # це створення шляху
    path('movies/<int:pk>/', MoviesDetailView.as_view(), name='movies-detail'),
    path('about/', views.about, name='movies-about'),
    path("search/", views.search, name="movies-search")
]

