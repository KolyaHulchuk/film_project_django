import requests
import logging
from django.conf import settings

BASE_URL = "https://api.themoviedb.org/3"

def get_movie_by_tmdb_id(tmdb_id):
    url = f"{BASE_URL}/movie/{tmdb_id}"
    params = {
        "api_key": settings.TMDB_API_KEY
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json() # завантажує інформацію з json в python словник
    return None

def get_tv_by_tmdb_id(tmdb_id):
    url = f"{BASE_URL}/tv/{tmdb_id}"
    params = {
        "api_key": settings.TMDB_API_KEY
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json()
    return None

def add_poster_url(items):
    for item in items:
        path = item.get("poster_path")
        item["poster_url"] = f"https://image.tmdb.org/t/p/w500{path}" if path else None

    return items


def add_extra_fields(items):
    for item in items:
        media_type = item.get("media_type", "movie")
        item["title"] = item.get("title") if media_type == "movie" else item.get("name")
        item["release_date"] = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
        item["rating"] = item.get("vote_average")
    
    return items

def all_func_movie(endpoint: str, page: int, languages=("en", "uk")):
    def fetch(language):
        url = f"{BASE_URL}/{endpoint}"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": language,
            "page": page
        }

        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json() # — це метод, який перетворює JSON-відповідь з сервера на Python-словник.
        else:
            logging.warning(f"Error API {response.status_code}")
        return {"results": [], "page": 1, "total_pages": 1}
    
    all_results = []
    base_data = None

    for lang in languages:
        data = fetch(lang)
        if lang == 'en':
            base_data = data
        all_results.extend(data.get("results"))

    uniq_results = []
    seen_id = set()
    for movie in all_results:
        if movie["id"] not in seen_id:
            seen_id.add(movie["id"])
            uniq_results.append(movie)
        
    uniq_results = add_poster_url(uniq_results)
    uniq_results = add_extra_fields(uniq_results)

    return {
        "results": uniq_results,
        "page": base_data.get("page", 1),
        "total_pages": base_data.get("total_pages", 1)
    }
    


def popular_movies(page):
    return all_func_movie("movie/popular", page)
        

def tv_popular(page):
    return all_func_movie("tv/popular", page)


def movie_top_rated(page):
    return all_func_movie("movie/top_rated", page)
  

def movie_now_playings(page):
    return all_func_movie("movie/now_playing", page)
      

def movie_upcoming(page):
    return all_func_movie("movie/upcoming", page)
        

def search_movies(query): # query — це рядок із того, що ввів користувач у форму пошуку 
    def fetch(language):
        url = f"{BASE_URL}/search/multi"
        params = {
            "api_key": settings.TMDB_API_KEY, 
            "query": query,
            "language": language
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            logging.warning(f"TMDB API error {response.status_code} for query '{query}' in '{language}'")
        return []

    results_uk = fetch("uk")
    results_en = fetch("en")

    seen_ids = set()
    combined = []

    for item in results_uk + results_en:
        media_type = item.get("media_type")
        if media_type not in ["movie", "tv"]:
            continue # пропускаємо акторів та інше
        if item["id"] not in seen_ids:
            combined.append(item)
            seen_ids.add(item["id"])

    return combined




# шукає в цьому словнику ключ "results". Якщо він є  повертає значення (тобто список фільмів). Якщо його немає  повертає порожній список [] 