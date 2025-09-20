from django.shortcuts import render
from django.http import HttpResponse
from .models import Movies
from django.views.generic import (
    ListView,
    DetailView
    )


def home(request):
    context = {
        'movies': Movies.objects.all()
    }
    return render(request, 'movies/home.html', context)


class MoviesListView(ListView):
    model = Movies
    template_name = 'movies/home.html'
    context_object_name = 'movies'


class MoviesDetailView(DetailView):
    model = Movies
    



def about(request):
    return render(request, 'movies/about.html')