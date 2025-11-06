from django.shortcuts import render, redirect ,get_object_or_404 # instance - сам об’єкт моделі . created - булеве значення (True або False): True, якщо об’єкт щойно створили; False, якщо об’єкт уже існував у базі.
from django.http import HttpResponse
from .models import Movies, Watchlist, Genre
from django.views import View
from .tmdb_service import (
    TMDBClient
    )
from django.views.generic import (
    ListView,
    DetailView,
    UpdateView
    )
from django.utils.timezone import make_aware
from datetime import datetime


class AllMoviesView(View):
    title = "Default Title"
    template_name = "movies/category/default.html" # це атрибути класу потім вони перевизначаються
    item_func = None
    media_type = "movie"
    
               
    def get(self, request):
        client = TMDBClient()
        try:
            page = int(request.GET.get("page", 1))
        except ValueError:
            page = 1

        data = self.item_func(page)  # це "сирі" дані з TMDB
        # перший запит — дізнатись total_pages для запитаного page
        total_pages = data.get("total_pages", 1)

        page = max(1, min(page, total_pages))

        items = client.enrich_items(data["results"], self.media_type) # додаю  до кожного фільма додаткові дані: рейтинг, жанри

        context = {
            "title": self.title,
            "items": items,
            "current_page": page,
            "total_pages": total_pages,
            "is_paginated": total_pages > 1,
            "page_range": range(
                max(1, data["page"] - 3),
                min(data["total_pages"] + 1, data["page"] + 3)
            )
        }

        return render(request, self.template_name, context)

class PopularMoviesView(AllMoviesView):
    title = "Popular Movies"
    template_name = "movies/category/popular.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item_func = lambda page: TMDBClient().get_list("movie/popular", page)


class TVPopularView(AllMoviesView):
    title = "Popular Tv"
    template_name = "movies/category/tv.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item_func = lambda page: TMDBClient().get_list("tv/popular", page)
        self.media_type = "tv"

class TopRatedView(AllMoviesView):
    title = "Top rated"
    template_name = "movies/category/top_rated.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item_func = lambda page: TMDBClient().get_list("movie/top_rated", page)

class NowPlayingsView(AllMoviesView):
    title = "Now Playings"
    template_name = "movies/category/now_playings.html"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item_func = lambda page: TMDBClient().get_list("movie/now_playing", page)

class UpcomingView(AllMoviesView):
    title = "Upcoming"
    template_name = "movies/category/upcoming.html"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item_func = lambda page: TMDBClient().get_list("movie/upcoming", page)


class HomeView(View):
    def get(self, request):
        page = 1
        client = TMDBClient()

        now_playings = client.get_list("movie/now_playing", page) # виклик функції
        upcoming = client.get_list("movie/upcoming", page)
        tv_serilas_popular = client.get_list("tv/popular", page)
        now_popular = client.get_list("movie/popular", page)
        top_rated = client.get_list("movie/top_rated", page)
        filtered_upcoming = [ m for m in upcoming["results"] if m["id"] not in {x["id"] for x in now_playings["results"]}]
        filtered_now_playings =  [ m for m in now_playings["results"] if m["id"] not in { x["id"] for x in now_popular["results"]}]

        
        context  = {
            "now_popular": now_popular["results"],
            "tv_serials_popular": tv_serilas_popular["results"],
            "top_rated": top_rated["results"],
            "now_playings":  now_playings["results"],
            "upcoming": upcoming["results"],
            "filtered_upcoming": filtered_upcoming,
            "filtered_now_playings": filtered_now_playings,
        }
    
        return render(request, 'movies/home.html', context)


class SerachView(View):
    def get(self, request):
        query = request.GET.get("q", '')
        results = [] 
        seen_ids = set() # множина для унікальних tmdb_id
        cleint = TMDBClient()
       
        if query: # шукаю в базі
            local_movies = Movies.objects.filter(title__icontains=query)  # icontains - означає: пошук, який ігнорує регістр (case-insensitive) і перевіряє, чи міститься підрядок
            for movie in local_movies:
                if movie.tmdb_id not in seen_ids:
                    results.append(movie)
                    seen_ids.add(movie.tmdb_id)

            tmdb_results = TMDBClient().search_movies(query) # повертає список фільмів
            print("TMDB RESULTS:", tmdb_results)

            for item in tmdb_results: # item — це словник з даними про один фільм.
                media_type = item.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue
                
                title = item.get("title") if item.get("media_type") == "movie" else item.get("name")
                release_date = item.get("release_date") if item.get("media_type") == "movie" else item.get("first_air_date")

                details = cleint.get_movie_by_tmdb_id(item["id"]) if media_type == "movie" else cleint.get_tv_by_tmdb_id(item["id"])
                print("RATING:", details.get("vote_average"))

                obj, _ = Movies.objects.get_or_create(   # obj — це конкретний фільм
                    tmdb_id=item["id"],
                    defaults={  #defaults={...} Ті поля, які треба заповнити, якщо запис створюється вперше.
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
                    genre_obj, _ = Genre.objects.get_or_create( # genre_obj — це конкретний жанр
                        tmdb_id =genre_data["id"],
                        defaults= {"name": genre_data["name"]}
                    )
                    if not  obj.genres.filter(tmdb_id=genre_obj.tmdb_id).exists():  # якщо в цього фільму немає жанру в базі даних 
                        obj.genres.add(genre_obj)

                    obj.save()

                    if obj.tmdb_id not in seen_ids:
                        results.append(obj)
                        seen_ids.add(obj.tmdb_id)

        return render(request, "movies/search.html", {"query": query, "results": results})



def added_watchlist(request, tmdb_id):
    user = request.user
    watchlist, _ = Watchlist.objects.get_or_create(user=user) # _ ігнорується
    client = TMDBClient()

    movie, created = Watchlist.objects.get_or_create(tmdb_id=tmdb_id, defaults={})

    if created: # True якщо не інсує

        data = client.get_movie_by_tmdb_id(tmdb_id) # беру дані

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


def about(request):
    return render(request, 'movies/about.html')


class MoviesDetailView(DetailView):
    model = Movies
    
