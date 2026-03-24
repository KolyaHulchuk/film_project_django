from django.shortcuts import render, redirect, get_object_or_404 
# instance – the model object
# created – a boolean value:
# True if the object was created,
# False if it already existed in the database
from django.http import HttpResponse
from .models import Movies, Genre
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
from django.contrib.auth.decorators import login_required
from datetime import datetime
from .utils import *
from users.models import Watchlist
from movies.services import get_ai
from django.http import JsonResponse

class AllMoviesView(View):
    """
    Base view for all movie and TV category pages.
    Subclasses override title, template_name, base_filters and media_type.
    """


    title = "Default Title"
    template_name = "movies/category/default.html" # class attribute, can be overridden in subclasses
    parials_name = "movies/partials/movie_list.html" # class attribute, overriden in subclasses
    item_func = None
    media_type = "movie"
    
               
    def get(self, request):
        client = TMDBClient()
        try:
            page = int(request.GET.get("page", 1))
        except ValueError:
            page = 1
                                     
        data = self.item_func(page)  #  Call the function that returns raw data from TMDB

        total_pages = data.get("total_pages", 1)

        page = max(1, min(page, total_pages))
                                                                  
        items = client.enrich_items(data["results"], self.media_type) #  Add extra data for each item (rating, genres, etc.)

        genres = client.get_genres(self.media_type)


        if request.user.is_authenticated:
            watchlist = Watchlist.objects.filter(user=request.user)

            watched_map = {}

            for w in watchlist:
                watched_map[w.movie.tmdb_id] = w

            for item in items:
                if item["id"] in watched_map:
                    watchlist_obj = watched_map[item["id"]]
                    item["is_watched"] = watchlist_obj.watched # is_watched — flag from watchlist
                    item["watchlist_id"] = watchlist_obj.id
                    print(f"✅ Знайшов: {item.get('title')} watched={watchlist_obj.watched}")
                    
                print(f"❌ Не в watchlist: {item.get('title')} id={item['id']}")


        current_filters = request.GET.urlencode()

        without_filters_page = request.GET.copy() # Copy current filters without the page parameter
        without_filters_page.pop("page", None)    # Prevent duplicating the page parameter in the URL
        current_filters = without_filters_page.urlencode()

        context = {
            "title": self.title,
            "items": items,
            "current_page": page,
            "total_pages": total_pages,
            "is_paginated": total_pages > 1,
            "page_range": range(
                max(1, data["page"] - 3),
                min(data["total_pages"] + 1, data["page"] + 3)
            ),
            "countries": COUNTRY_CODES,
            "genres": genres,
            "current_filters": current_filters
        }

        # # If the request comes from HTMX, render only the partial template
        if request.headers.get("HX-Request"):
            template = self.parials_name
        else:
            template = self.template_name

        print(context)    
        return render(request, template, context)
    

    # Build extra filters from user input (query parameters)
    def search_filter_movie(self, request):

            extra_filters = {}

            years = request.GET.get("years_search")
            if years:
                if self.media_type == "tv":
                    extra_filters["first_air_date_year"] = years
                else:
                    extra_filters["primary_release_year"] = years


            ratings = request.GET.get("rating_search")
            if ratings:
                try:
                    rating = float(ratings)
                    extra_filters["vote_average.gte"] = rating
                except ValueError:
                    pass

            genres = request.GET.get("genre_search")
            if genres:
                extra_filters["with_genres"] = genres

            country = request.GET.get("country_search")
            if country:
                extra_filters["with_origin_country"] = country


            name = request.GET.get("name_search")
            if name:
                extra_filters["name"] = name

            return extra_filters



class PopularMoviesView(AllMoviesView):
    title = "Popular Movies"
    template_name = "movies/category/popular.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item_func = lambda page: TMDBClient().get_list("movie/popular", page)
        print(self.item_func)


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

        now_playings = client.get_list("movie/now_playing", page) # Fetch data from TMDB
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
        seen_ids = set() # Fetch data from TMDB

        watched_map = {}

        if request.user.is_authenticated:
            watchlist = Watchlist.objects.filter(user=request.user)

            

            for w in watchlist:
                watched_map[w.movie.tmdb_id] = w

       
        if query: # Search in the local database first
            local_movies = Movies.objects.filter(title__icontains=query)  # icontains performs a case-insensitive substring search
            for movie in local_movies:                                    # icontains is a built-in Django filter for case-insensitive substring search.

                if movie.tmdb_id and movie.tmdb_id not in seen_ids:

                    if movie.tmdb_id in watched_map:
                        watchlist_obj = watched_map[movie.tmdb_id] #  get the Watchlist object
                        movie.is_watched = watchlist_obj.watched  # True if watched, False if not
                        movie.watchlist_id = watchlist_obj.id  # attach watchlist data to movie object


                
                    results.append(movie)
                    seen_ids.add(movie.tmdb_id)
                    
            tmdb_results = TMDBClient().search_movies(query) # Returns a list of movies and TV shows from TMDB
       

            
            for item in tmdb_results: # Each item is a dictionary with TMDB data
                media_type = item.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue
                
                tmdb_id = item["id"]
                obj = get_or_create_media(tmdb_id, media_type)

                
                
                if obj.tmdb_id in watched_map:
                    watchlist_obj = watched_map[obj.tmdb_id]
                    obj.is_watched = watchlist_obj.watched # is_watched is the column name we create in the dictionary that comes from the API
                    obj.watchlist_id = watchlist_obj.id



                if obj.tmdb_id not in seen_ids:
                    results.append(obj)
                    seen_ids.add(obj.tmdb_id)
       
        return render(request, "movies/search.html", {"query": query, "results": results})



def get_country(data, media_type):
    """
    pull code country from data TMDB    
    Args:
        data: data from  TMDB API
        media_type: "movie" or "tv"
    
    Returns:
        Lsit of country codes : ['US', 'UA']
    """


    if media_type == "tv":
        # For TV shows, use the origin_country field
        return data.get("origin_country", [])
    else:
        # For movies, extract data from production_countries
        production_countries = data.get("production_countries", [])
        return [country["iso_3166_1"] for country in production_countries]
        


def get_or_create_media(tmdb_id, media_type="movie"):
    client = TMDBClient()

    if media_type == "movie":
        data = client.get_movie_by_tmdb_id(tmdb_id)
        print("Data", data)
        title = data.get("title") if data else None
        raw_date = data.get("release_date") if data else None
    else:
        data = client.get_tv_by_tmdb_id(tmdb_id)
        title = data.get("name") if data else None
        raw_date = data.get("first_air_date") if data else None

    print("tmdb_id:", tmdb_id, "media_type:", media_type)
    print("data:", data)

    if not data:
        return None
    
    # Get country codes for both movies and TV shows
    country_code = get_country(data, media_type)

    # Convert country codes to full country names
    normalize = normalize_countries(country_code)

    movie, created = Movies.objects.get_or_create(
        tmdb_id=tmdb_id,
        defaults={
            "title": title,
            "description": data.get("overview", ""),
            "poster_url": f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get("poster_path") else "",
            "media_type": media_type,
            "tmdb_rating": data.get("vote_average"),
            "country": normalize,
            "author": data.get("production_companies")[0]["name"] if data.get("production_companies") else "",
        }
    )

    if created and raw_date:
        try:
            movie.release_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            movie.release_date = None
    movie.save()

    movie.genres.clear() # Remove all existing genres
    for genre_data in data.get("genres", []):
        genre_obj, _ = Genre.objects.get_or_create(  # genre_obj represents a single genre
            tmdb_id =genre_data["id"],
            defaults= {"name": genre_data["name"]}
        )
        if not  movie.genres.filter(tmdb_id=genre_obj.tmdb_id).exists(): # Add the genre if it is not already assigned to this movie
            movie.genres.add(genre_obj)


    return movie




class MoviesDetailView(View):
    def get(self, request, pk, media_type="movie"):
        data = Movies.objects.filter(tmdb_id=pk).first()
        if not data:
            data = get_or_create_media(pk, media_type)

        client = TMDBClient()
        credits = client.get_credit(pk, media_type)

        director = next(
            (p for p in credits.get("crew", []) if p["job"] == "Director"),
            None
        )

        cast = credits.get("cast", [])[:12]


        context = {
            "data": data,
            "director": director,
            "cast": cast,
        }



        return render(request, "movies/movies_detail.html", context)






    
class TVViews(AllMoviesView):
    title = "TV"
    template_name = "movies/type/tv.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_filters = {"without_genres": 16, "max_page": 100}
        self.media_type = "tv"



    def get(self, request):
        extra_filters = self.search_filter_movie(request)
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func =  lambda page: TMDBClient().get_list("discover/tv", page, **filters) 
        return super().get(request)

    

# Type tv/movie

class AnimeTVView(AllMoviesView):
    title = "Anime TV"
    template_name = "movies/type/anime.html"
      
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_filters = {   # # Base TMDB query parameters
                "with_genres": 16, # 16 = Animation in TMDB
                "with_original_language": "ja",  # Japan language
                "with_origin_country": "JP",  # Japanese production
                "max_page": 100  
                } 
        
        self.media_type = "tv"


    def get(self, request):
        extra_filters = self.search_filter_movie(request)
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func =  lambda page: TMDBClient().get_list("discover/tv", page, **filters) 
        return super().get(request)



class DoramTVView(AllMoviesView):
    title = "Dorams TV"
    template_name = "movies/type/dorams.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_filters = {"with_original_language": "ko", "without_genres": 16, "max_page": 100}
        self.media_type = "tv"


    def get(self, request):
        extra_filters = self.search_filter_movie(request)
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func =  lambda page: TMDBClient().get_list("discover/tv", page, **filters) 
        return super().get(request)

class CartoonTVView(AllMoviesView):
    title = "Cartoon TV"
    template_name = "movies/type/cartoons.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)       
        self.base_filters = {
            "with_genres": 16,
            "with_origin_country": "US|GB|FR|CA|AU",
            "max_page": 100
        }
        self.media_type = "tv"

    def get(self, request):
        extra_filters = self.search_filter_movie(request) # Additional filters from user input
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func =  lambda page: TMDBClient().get_list("discover/tv", page, **filters) 
        return super().get(request)


class MovieView(AllMoviesView):
    title = "Movie"
    template_name = "movies/type/movie.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_filters = {"max_page": 100}
        self.media_type = "movie"

    def get(self, request):
        extra_filters = self.search_filter_movie(request)
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func = lambda page: TMDBClient().get_list("discover/movie", page, **filters)
        return super().get(request)
    

@login_required
def ai_recomendations(request):
    message = request.GET.get("message", "")
    media_type = request.GET.get("type", "all")
    result = get_ai(request.user, message, media_type)
    return JsonResponse(result)





        