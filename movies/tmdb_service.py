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
    for movie in results_uk + results_en:
        if movie["id"] not in seen_ids:
            combined.append(movie)
            seen_ids.add(movie["id"])

    return combined




# шукає в цьому словнику ключ "results". Якщо він є  повертає значення (тобто список фільмів). Якщо його немає  повертає порожній список [] 