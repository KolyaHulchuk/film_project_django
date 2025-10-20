from django.shortcuts import render, redirect ,get_object_or_404 # instance - сам об’єкт моделі . created - булеве значення (True або False): True, якщо об’єкт щойно створили; False, якщо об’єкт уже існував у базі.
from django.http import HttpResponse
from .models import Movies, Watchlist, Genre
from .tmdb_service import (
    get_movie_by_tmdb_id, 
    get_tv_by_tmdb_id,
    search_movies, 
    popular_movies,
    tv_popular,
    movie_top_rated,
    movie_now_playings,
    movie_upcoming
    )
from django.views.generic import (
    ListView,
    DetailView,
    UpdateView
    )
from django.utils.timezone import make_aware
from datetime import datetime


def home(request):
    page = 1
    now_playings = movie_now_playings(page) # виклик функції
    upcoming = movie_upcoming(page)
    now_popular = popular_movies(page)
    filtered_upcoming = [ m for m in upcoming if m["id"] not in {x["id"] for x in now_playings}]
    filtered_now_plyaings =  [ m for m in now_playings if m["id"] not in { x["id"] for x in now_popular}]

    context  = {
        "now_popular": now_playings,
        "tv": tv_popular(page),
        "top_rated": movie_top_rated(page),
        "now_playings":  now_playings,
        "upcoming": upcoming,
        "filtered_upcoming": filtered_upcoming,
        "filtered_now_plyaings": filtered_now_plyaings,
    }
    print("Upcoming:", context["upcoming"]) 

    return render(request, 'movies/home.html', context)






class MoviesDetailView(DetailView):
    model = Movies
    


def added_watchlist(request, tmdb_id):
    user = request.user
    watchlist, _ = Watchlist.objects.get_or_create(user=user) # _ ігнорується

    movie, created = Watchlist.objects.get_or_create(tmdb_id=tmdb_id, defaults={})

    if created: # True якщо не інсує

        data = get_movie_by_tmdb_id(tmdb_id) # беру дані

        if data:
            movie.title = data.get("title")
            movie.description = data.get("overview", "")
            movie.poster_url = f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else ""
            raw_date = data.get("release_date")
            if raw_date:
                try:
                    movie.release_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                except ValueError:
                    movie.release_date = None
            movie.save()

    watchlist.movies.add(movie) # додаю фільм у watchlist користувача
    return redirect("movies-home")

def search(request):
    query = request.GET.get("q", '')
    results = []
    seen_ids = set()  # множина для унікальних tmdb_id


    if query: # шукаю в базі
        local_movies = Movies.objects.filter(title__icontains=query) # icontains - означає: пошук, який ігнорує регістр (case-insensitive) і перевіряє, чи міститься підрядок
        for movie in local_movies:
            if movie.tmdb_id not in seen_ids:
                results.append(movie)
                seen_ids.add(movie.tmdb_id)

        tmdb_result = search_movies(query) # повертає список фільмів
        for item in tmdb_result: # item — це словник з даними про один фільм.
            media_type = item.get("media_type")
            if media_type not in ["movie", "tv"]:
                continue

            title = item.get("title") if item.get("media_type") == "movie" else item.get("name")   
            release_date = item.get("release_date") if item.get("media_type") == "movie" else item.get("first_air_date")
                
            details = get_tv_by_tmdb_id(item["id"]) if media_type == "tv" else get_movie_by_tmdb_id(item["id"])
            print("RATING:", details.get("vote_average"))

            obj, _ = Movies.objects.get_or_create(  # obj — це конкретний фільм
                tmdb_id=item["id"], 
                defaults={ #defaults={...} Ті поля, які треба заповнити, якщо запис створюється вперше.
                    "title": title,
                    "description": item.get("overview", ""),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{item['poster_path']}" if item.get("poster_path") else None,
                    "release_date": release_date or None,
                    "media_type": media_type
                },
            )

            obj.tmdb_rating = details.get("vote_average")

            obj.genres.clear() # видаляє всі жарни 
            for genre_data in details.get("genres", []):
                genre_obj, _ = Genre.objects.get_or_create(  # genre_obj — це конкретний жанр
                    tmdb_id=genre_data["id"],
                    defaults={"name": genre_data["name"]}
                )
                if not obj.genres.filter(tmdb_id=genre_obj.tmdb_id).exists(): # якщо в цього фільму немає жанру в базі даних 
                    obj.genres.add(genre_obj)  

                
                    
            obj.save()
                
            if obj.tmdb_id not in seen_ids:
                results.append(obj)
                seen_ids.add(obj.tmdb_id)

    return render(request, "movies/search.html", {"query": query, "results": results})



def about(request):
    return render(request, 'movies/about.html')