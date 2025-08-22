from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='movies-home' ),  # це створення шляху
    path('about/', views.about, name='movies-about')
]