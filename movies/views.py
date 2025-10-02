from django.shortcuts import render, redirect ,get_object_or_404 # instance - сам об’єкт моделі . created - булеве значення (True або False): True, якщо об’єкт щойно створили; False, якщо об’єкт уже існував у базі.
from django.http import HttpResponse
from .models import Movies, UserMovies
from .tmdb_service import get_movie_by_tmdb_id, search_movies
from django.views.generic import (
    ListView,
    DetailView,
    UpdateView
    )
from django.utils.timezone import make_aware
from datetime import datetime


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
    


def added_watchlist(request, tmdb_id):
    user = request.user
    watchlist, _ = UserMovies.objects.get_or_create(user=user) # _ ігнорується

    movie, created = UserMovies.objects.get_or_create(tmdb_id=tmdb_id, defaults={})

    if created: # True якщо не інсує

        data = get_movie_by_tmdb_id(tmdb_id) # беру дані

        if data:
            movie.title = data.get("title")
            movie.description = data.get("overview", "")
            movie.poster_url = f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else ""
            raw_date = data.get("release_date")
            if raw_date:
                try:
                    movie.release_date = datetime.strftime(raw_date, "%Y-%m-%d").date()
                except ValueError:
                    movie.release_date = None
            movie.save()

    watchlist.movies.add(movie) # додаю фільм у watchlist користувача
    return redirect("movies-home")

def search(request):
    query = request.GET.get("q", '')
    results = []

    if query: # шукаю в базі
        local_movies = Movies.objects.filter(title__icontains=query) # icontains - означає: пошук, який ігнорує регістр (case-insensitive) і перевіряє, чи міститься підрядок
        results.extend(local_movies)  # extend() — це спосіб додати всі елементи одного списку до іншого

        if not local_movies.exists(): # це метод QuerySet, який перевіряє, чи є хоч один запис, що задовольняє умові.
            tmdb_result = search_movies(query) # повертає список фільмів
            for movie in tmdb_result: # movie — це словник з даними про один фільм.
                obj, _ = Movies.objects.get_or_create(tmdb_id=movie["id"], defaults={ #defaults={...} Ті поля, які треба заповнити, якщо запис створюється вперше.
                    "title": movie["title"],
                        "description": movie.get("overview", ""),
                        "poster_url": f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get("poster_path") else None,
                        "release_date": movie.get("release_date") or None,
                },
                )
                results.append(obj)

    return render(request, "movies/search.html", {"query": query, "results": results})



def about(request):
    return render(request, 'movies/about.html')