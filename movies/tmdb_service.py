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


def popular_movies(page):
    def fetch(language):
        url = f"{BASE_URL}/movie/popular"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": language,
            "page": page
        }
        response =  requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("results", []) # витягує список фільмів і серіалів
        else:
            logging.warning(f"TMDB API error {response.status_code}")
        return []
    
    results_uk = fetch("uk")
    results_en = fetch("en")
    

    seens_id = set()
    combinate = []
    for movie in results_en + results_uk:
        if movie["id"] not in seens_id:
            combinate.append(movie)
            seens_id.add(movie["id"])

    return combinate

def tv_popular(page):
    def fetch(language):
        url = f"{BASE_URL}/tv/popular"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": language, 
            "page": page
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            logging.warning(f"TMDB API error {response.status_code}")
        return []
    
    results_uk = fetch("uk")
    results_en = fetch("en")

    seens_id = set()
    combinate = []
    for item in results_en + results_uk:
        if item["id"] not in seens_id:
            combinate.append(item)
            seens_id.add(item["id"])
    
    return combinate


def movie_top_rated(page):
    def fetch(language):
        url = f"{BASE_URL}/movie/top_rated"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": language,
            "page": page
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("results", [])
        return []
    
    results_uk = fetch("uk")
    results_en = fetch("en")

    seens_id = set()
    combinate = []

    for movie in results_en + results_uk:
        if movie["id"] not in seens_id:
            combinate.append(movie)
            seens_id.add(movie["id"])

    return combinate


def movie_now_playings(page):
    def fetch(language):
        url = f"{BASE_URL}/movie/now_playing"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": language,
            "page": page
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("results", [])
        return []
    
    results_uk = fetch("uk")
    results_en = fetch("en")

    seens_id = set()
    combinate = []

    for movie in results_en + results_uk:
        if movie["id"] not in seens_id:
            combinate.append(movie)
            seens_id.add(movie["id"])
            
    return combinate

def unique_upcoming(*lists):
    seens_id = set()
    result = []
    for movie_list in lists:
        for movie in movie_list:
            if movie["id"] not in seens_id:
                seens_id.add(movie["id"])
                result.append(movie)

    return result


def movie_upcoming(page):
    def fetch(language):
        url = f"{BASE_URL}/movie/upcoming"
        params = {
            "api_key": settings.TMDB_API_KEY,
            "language": language,
            "page": page
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            logging.warning(f"TMDB API erro {response.status_code}")
        return []

    result_uk = fetch("uk")
    result_en = fetch("en")

    return unique_upcoming(result_uk, result_en)

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