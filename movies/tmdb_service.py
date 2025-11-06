import requests
import logging
from datetime import datetime
from django.conf import settings

class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

    def __init__(self, api_key=None, languages=("en", "uk")):
        self.api_key = api_key or settings.TMDB_API_KEY # Якщо api_key не передано, візьми settings.TMDB_API_KEY
        self.languages = languages

    def _request(self, endpoint, params=None):
        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {} # # якщо параметри не передані  створюю порожній словник
        params["api_key"] = self.api_key # додаю до параметрів ключ API, щоб авторизувати запит до TMDB
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json() # — це метод, який перетворює JSON-відповідь з сервера на Python-словник.
        else:
            logging.warning(f"TMDB API error {response.status_code} for endpoint '{endpoint}")
        return {} # тут пусто бо дані даля обробляюст і там вже будуть добавлений результ та сторінки


    def get_movie_by_tmdb_id(self, tmdb_id):
        return self._request(f"movie/{tmdb_id}")

    def get_tv_by_tmdb_id(self, tmdb_id):
        return self._request(f"tv/{tmdb_id}")
        

    def _type_items(self, items):
        for item in items:
            path = item.get("poster_path")
            item["poster_url"] = f"https://image.tmdb.org/t/p/w500{path}" if path else None

            media_type = item.get("media_type", "movie")
            item["title"] = item.get("title") if media_type == "movie" else item.get("name")
            item["release_date"] = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
            item["rating"] = item.get("vote_average")
        
        return items
    
    
    def get_list(self, endpoint, page=1):
        data = self._request(endpoint, {"language": "en", "page": page})
        if not data or "results" not in data:
            return {
                "results": [],
                "page": page,
                "total_pages": 1
            }

        uniq_results = []
        seen_id = set()

        for result in data["results"]:
            if result["id"] not in seen_id:
                seen_id.add(result["id"])
                uniq_results.append(result)

        uniq_results = self._type_items(uniq_results)

        return {
            "results": uniq_results,
            "page": data.get("page", page),
            "total_pages": min(data.get("total_pages", 1), 10)
        }


   
    def search_movies(self, query): # query — це рядок із того, що ввів користувач у форму пошуку 
        seen_ids = set()
        combined = []

        for lang in self.languages:
            data = self._request("search/multi", {"query": query, "language": lang})
            for item in data.get("results", []):
                media_type = item.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue # пропускаємо акторів та інше
                if item["id"] not in seen_ids:
                    combined.append(item)
                    seen_ids.add(item["id"])

        return self._type_items(combined)

    @staticmethod
    def get_release_date(details, media_type):
        raw_date = (
            details.get("release_date") if media_type == "movie" 
            else details.get("first_air_date")
        )

        try:
            date_obj = datetime.strptime(raw_date, "%Y-%m-%d")
            return date_obj.strftime("%d.%m.%Y")
        except (TypeError, ValueError):
            return "Uknown"
        

    def enrich_item(self, item, media_type):
            details = (
                self.get_movie_by_tmdb_id(item["id"])
                if media_type == "movie"
                else self.get_tv_by_tmdb_id(item["id"])
            )

            item["release_date"] = self.get_release_date(details, media_type)
            item["tmdb_rating"] = details.get("vote_average")
            item["genres"] = [ genre["name"] for genre in details.get("genres", [])]
            return item
    
    def enrich_items(self, items, media_type):
        return [self.enrich_item(item, media_type) for item in items]
# шукає в цьому словнику ключ "results". Якщо він є  повертає значення (тобто список фільмів). Якщо його немає  повертає порожній список [] 