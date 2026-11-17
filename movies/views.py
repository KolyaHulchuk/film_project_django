import logging
import math
import time
from collections.abc import Callable
from datetime import date, datetime
from functools import partial, wraps
from typing import Any

import requests
from celery.result import AsyncResult
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.decorators.http import require_GET, require_POST

from movies.tasks import get_ai_recommendation_task
from users.models import Watchlist
from users.security_log import security_event

from .comments import COMMENTS_PER_PAGE, get_annotated_comment, movie_comments, normalize_sort, toggle_vote
from .forms import CommentForm
from .models import COMMENT_MAX_LENGTH, Comment, CommentVote, Genre, Movies
from .redis_services import TTL_LIST, TMDBFetchError, cache_search_results
from .throttling import AIRecommendationThrottle, CommentCreateThrottle, CommentVoteThrottle
from .tmdb_service import (
    TMDBClient,
    TMDBData,
    fetch_parallel,
)
from .utils import COUNTRY_CODES, normalize_countries

logger = logging.getLogger(__name__)

# Home "Pick by Mood": mood -> (TMDB movie genre id, icon). Chip labels come from
# genre/movie/list, the picks row from discover/movie?with_genres={id}.
MOODS = {
    "comedy": (35, "i-smile"),
    "drama": (18, "i-masks"),
    "thriller": (53, "i-eye"),
    "horror": (27, "i-ghost"),
    "romance": (10749, "i-heart"),
    "scifi": (878, "i-planet"),
    "action": (28, "i-bolt"),
    "fantasy": (14, "i-spark"),
    "documentary": (99, "i-camera"),
    "mystery": (9648, "i-moon"),
}
# Popular titles only, so a mood row isn't filled with obscure, unrated films.
MOOD_DISCOVER_FILTERS = {"sort_by": "popularity.desc", "vote_count.gte": 300}

# Home "Topic of the Day": TMDB keyword ids, one per day in rotation (see
# topic_of_the_day). Checked against search/keyword on 2026-10-29: time travel,
# heist, dystopia, cyberpunk, road trip, survival, artificial intelligence (a.i.),
# haunted house, whodunit, space travel.
TOPIC_KEYWORDS = (4379, 10051, 4565, 12190, 7312, 10349, 310, 3358, 12570, 3801)

# Every Home row shows the first page of its TMDB list.
HOME_PAGE = 1
# Home "Coming Soon": how many upcoming movies get a trailer lookup.
COMING_SOON_LIMIT = 8

# discover/* base filters of the catalog pages; the first three are shared with the home TV showcase.
DORAMA_TV_FILTERS = {"with_original_language": "ko", "without_genres": 16, "max_page": 100}
ANIME_TV_FILTERS = {
    "with_genres": 16,  # 16 = Animation in TMDB
    "with_original_language": "ja",  # Japan language
    "with_origin_country": "JP",  # Japanese production
    "max_page": 100,
}
CARTOON_TV_FILTERS = {"with_genres": 16, "with_origin_country": "US|GB|FR|CA|AU", "max_page": 100}
TV_DISCOVER_FILTERS = {"without_genres": 16, "max_page": 100}  # all TV except animation
MOVIE_DISCOVER_FILTERS = {"max_page": 100}

# Home "TV & Categories" tabs: (slug, label, catalog url name). "tv" uses tv/popular.
TV_SHOWCASE_TABS = (
    ("tv", "TV Shows", "popular-tv"),
    ("dorama", "Doramas", "dorams-tv"),
    ("anime", "Anime", "anime-tv"),
    ("cartoon", "Cartoons", "cartoon-tv"),
)
TV_SHOWCASE = {
    "dorama": ("discover/tv", DORAMA_TV_FILTERS),
    "anime": ("discover/tv", ANIME_TV_FILTERS),
    "cartoon": ("discover/tv", CARTOON_TV_FILTERS),
}


# Catalog "Sort" chip (discover pages only): ?sort=<key> -> (label, movie sort_by, tv sort_by).
CATALOG_SORTS = {
    "popularity": ("Popularity", "popularity.desc", "popularity.desc"),
    "rating": ("Rating", "vote_average.desc", "vote_average.desc"),
    "newest": ("Release date", "primary_release_date.desc", "first_air_date.desc"),
    "title": ("A–Z", "title.asc", "name.asc"),
}
# (key, label) pairs for the Sort chip; templates only iterate over it.
CATALOG_SORT_OPTIONS = [(key, label) for key, (label, _, _) in CATALOG_SORTS.items()]
# Rating / A-Z sorts and the min-rating filter would otherwise surface titles with a handful of votes.
MIN_VOTES = 100

# Detail page: how many cast members are shown.
DETAIL_CAST_LIMIT = 12

# Comment feed sort switch: (normalize_sort() key, label).
COMMENT_SORT_OPTIONS = [("new", "Newest"), ("old", "Oldest")]


def topic_of_the_day(today: date | None = None) -> int:
    """Rotate TOPIC_KEYWORDS by calendar day: same topic for everyone all day."""
    today = today or date.today()
    return TOPIC_KEYWORDS[today.toordinal() % len(TOPIC_KEYWORDS)]


def _parse_page(request: HttpRequest) -> int:
    """`?page` as an int; 1 when it is missing or not a number (not clamped here)."""
    try:
        return int(request.GET.get("page", 1))
    except ValueError:
        return 1


# == Catalog ==


class AllMoviesView(View):
    """Base view for all movie and TV category pages.

    Subclasses set title, template_name, media_type and item_func(page), which
    returns one page of a TMDB list. The page is annotated with genre names and,
    for a logged-in user, with their watchlist state (is_watched, watchlist_id).
    """

    title = "Default Title"
    template_name = "movies/category/default.html"  # class attribute, can be overridden in subclasses
    parials_name = "movies/partials/movie_list.html"  # rendered instead of template_name for HTMX requests
    item_func: Callable[[int], TMDBData] | None = None
    media_type = "movie"
    sortable = False  # True on the discover-based pages, where search_filter_movie() sends sort_by

    def get(self, request: HttpRequest) -> HttpResponse:
        """Render one catalog page (`?page=N`, clamped to TMDB's total_pages)."""
        view_start = time.perf_counter()
        client = TMDBClient()
        page = _parse_page(request)

        step_start = time.perf_counter()
        data = self.item_func(page)  #  Call the function that returns raw data from TMDB
        logger.debug("[timing] item_func/get_list: %.1fms", (time.perf_counter() - step_start) * 1000)

        total_pages = data.get("total_pages", 1)

        page = max(1, min(page, total_pages))

        step_start = time.perf_counter()
        genres = client.get_genres(self.media_type)
        logger.debug("[timing] get_genres: %.1fms", (time.perf_counter() - step_start) * 1000)

        step_start = time.perf_counter()
        items = client.annotate_items(
            data["results"], self.media_type, genres
        )  #  Add extra data for each item (rating, genres, etc.) from data already in the list response - no TMDB calls
        logger.debug("[timing] annotate_items: %.1fms", (time.perf_counter() - step_start) * 1000)

        if request.user.is_authenticated:
            step_start = time.perf_counter()
            watchlist = Watchlist.objects.filter(user=request.user).select_related("movie")
            watched_map = {w.movie.tmdb_id: w for w in watchlist}

            for item in items:
                if item["id"] in watched_map:
                    watchlist_obj = watched_map[item["id"]]
                    item["is_watched"] = watchlist_obj.watched  # is_watched — flag from watchlist
                    item["watchlist_id"] = watchlist_obj.id
            logger.debug("[timing] watchlist_annotation: %.1fms", (time.perf_counter() - step_start) * 1000)

        without_filters_page = request.GET.copy()  # Copy current filters without the page parameter
        without_filters_page.pop("page", None)  # Prevent duplicating the page parameter in the URL
        current_filters = without_filters_page.urlencode()

        context = {
            "title": self.title,
            "items": items,
            "current_page": page,
            "total_pages": total_pages,
            "is_paginated": total_pages > 1,
            "page_range": range(max(1, data["page"] - 3), min(data["total_pages"] + 1, data["page"] + 3)),
            "countries": COUNTRY_CODES,
            "genres": genres,
            "current_filters": current_filters,
            "total_results": data.get("total_results"),
            "sortable": self.sortable,
            "sort_options": CATALOG_SORT_OPTIONS,
            "current_sort": self.current_sort(request),
        }

        # If the request comes from HTMX, render only the partial template
        template = self.parials_name if request.headers.get("HX-Request") else self.template_name

        step_start = time.perf_counter()
        response = render(request, template, context)
        logger.debug("[timing] render: %.1fms", (time.perf_counter() - step_start) * 1000)
        logger.debug("[timing] AllMoviesView.get total: %.1fms", (time.perf_counter() - view_start) * 1000)
        return response

    def search_filter_movie(self, request: HttpRequest) -> dict[str, Any]:
        """TMDB discover filters from the query string (years, rating, genre, country, sort)."""
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

        sort = self.current_sort(request)
        _label, movie_sort, tv_sort = CATALOG_SORTS[sort]
        if sort != "popularity":
            extra_filters["sort_by"] = tv_sort if self.media_type == "tv" else movie_sort
        if sort == "newest":
            # without an upper bound "newest" is all announced, unreleased titles
            today = date.today().isoformat()
            extra_filters["first_air_date.lte" if self.media_type == "tv" else "primary_release_date.lte"] = today
        if sort in ("rating", "title") or "vote_average.gte" in extra_filters:
            extra_filters["vote_count.gte"] = MIN_VOTES

        return extra_filters

    @staticmethod
    def current_sort(request: HttpRequest) -> str:
        """The `?sort` key if it is in CATALOG_SORTS, otherwise "popularity"."""
        sort = request.GET.get("sort", "popularity")
        return sort if sort in CATALOG_SORTS else "popularity"


class ListCatalogView(AllMoviesView):
    """Catalog page of one fixed TMDB list (list_endpoint); the query-string filters are not used."""

    list_endpoint = ""

    def item_func(self, page: int) -> TMDBData:
        """One page of list_endpoint."""
        return TMDBClient().get_list(self.list_endpoint, page)


class PopularMoviesView(ListCatalogView):
    title = "Popular Movies"
    template_name = "movies/category/popular.html"
    list_endpoint = "movie/popular"


class TVPopularView(ListCatalogView):
    title = "Popular Tv"
    template_name = "movies/category/tv.html"
    list_endpoint = "tv/popular"
    media_type = "tv"


class TopRatedView(ListCatalogView):
    title = "Top rated"
    template_name = "movies/category/top_rated.html"
    list_endpoint = "movie/top_rated"


class NowPlayingsView(ListCatalogView):
    title = "Now Playings"
    template_name = "movies/category/now_playings.html"
    list_endpoint = "movie/now_playing"


class UpcomingView(ListCatalogView):
    title = "Upcoming"
    template_name = "movies/category/upcoming.html"
    list_endpoint = "movie/upcoming"


class DiscoverCatalogView(AllMoviesView):
    """Catalog page on TMDB discover/*: base_filters plus the user's filters and sort from the query string."""

    sortable = True
    discover_endpoint = ""
    base_filters: dict[str, Any] = {}  # never mutated, only merged into a new dict

    def get(self, request: HttpRequest) -> HttpResponse:
        """Build this request's filters (query string wins over base_filters), then render the page."""
        extra_filters = self.search_filter_movie(request)
        self.filters = {**self.base_filters, **extra_filters}
        return super().get(request)

    def item_func(self, page: int) -> TMDBData:
        """One page of discover_endpoint with this request's filters."""
        return TMDBClient().get_list(self.discover_endpoint, page, **self.filters)


class TVViews(DiscoverCatalogView):
    title = "TV"
    template_name = "movies/type/tv.html"
    discover_endpoint = "discover/tv"
    base_filters = TV_DISCOVER_FILTERS
    media_type = "tv"


class AnimeTVView(DiscoverCatalogView):
    title = "Anime TV"
    template_name = "movies/type/anime.html"
    discover_endpoint = "discover/tv"
    base_filters = ANIME_TV_FILTERS
    media_type = "tv"


class DoramTVView(DiscoverCatalogView):
    title = "Dorams TV"
    template_name = "movies/type/dorams.html"
    discover_endpoint = "discover/tv"
    base_filters = DORAMA_TV_FILTERS
    media_type = "tv"


class CartoonTVView(DiscoverCatalogView):
    title = "Cartoon TV"
    template_name = "movies/type/cartoons.html"
    discover_endpoint = "discover/tv"
    base_filters = CARTOON_TV_FILTERS
    media_type = "tv"


class MovieView(DiscoverCatalogView):
    title = "Movie"
    template_name = "movies/type/movie.html"
    discover_endpoint = "discover/movie"
    base_filters = MOVIE_DISCOVER_FILTERS
    media_type = "movie"


# == Popular actors ==


class PopularActorView(View):
    """Paginated popular actors page.

    TMDB's "popular people" endpoint returns actors, directors, producers, etc.
    mixed together; get_popular_actors() filters that down to actors only,
    since the template just needs poster/name/one known-for title.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        client = TMDBClient()
        page = _parse_page(request)

        context = client.get_popular_actors(page)

        return render(request, "movies/popular_actors.html", context)


# == Home ==


class HomeView(View):
    """Home page. Every row comes from TMDB in two fetch_parallel rounds:

    1. all list rows, genres and the Topic of the Day;
    2. what depends on round 1: Coming Soon trailers and the Movie of the Week details.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        client = TMDBClient()
        data = fetch_parallel(self._first_round_tasks(client, topic_of_the_day()))

        now_playings = self._results(data, "now_playings")
        now_popular = self._results(data, "now_popular")
        now_playing_ids = {m["id"] for m in now_playings}
        popular_ids = {m["id"] for m in now_popular}
        filtered_upcoming = [m for m in self._results(data, "upcoming") if m["id"] not in now_playing_ids]
        filtered_now_playings = [m for m in now_playings if m["id"] not in popular_ids]

        # Movie of the Week rule: the #1 movie of TMDB trending/movie/week.
        coming_soon = filtered_upcoming[:COMING_SOON_LIMIT]
        motw_item = next(iter(self._results(data, "trending_movie_week")), None)
        data.update(fetch_parallel(self._second_round_tasks(client, coming_soon, motw_item)))

        motw = None
        if motw_item and (data.get("motw") or {}).get("id"):
            motw = data["motw"]

        context = {
            "hero_movies": data.get("hero_movies") or [],
            "trending_all_week": self._results(data, "trending_all_week"),
            "trending_all_day": self._results(data, "trending_all_day"),
            "now_popular": now_popular,
            "tv_serials_popular": self._results(data, "tv_serials_popular"),
            "top_rated": self._results(data, "top_rated"),
            "now_playings": now_playings,
            "upcoming": self._results(data, "upcoming"),
            "filtered_upcoming": data.get("coming_soon") or coming_soon,
            "filtered_now_playings": filtered_now_playings,
            "actors": [a for a in self._results(data, "trending_people") if a.get("known_for_department") == "Acting"],
            "motw": motw,
            "moods": self._moods(data),
            "topic": self._topic(data),
            "tv_showcase": self._tv_showcase(data),
        }

        return render(request, "movies/home.html", context)

    @staticmethod
    def _results(data: dict[str, Any], name: str) -> list[TMDBData]:
        """The "results" list of one fetched block; [] when the block failed or is empty."""
        return (data.get(name) or {}).get("results", [])

    @staticmethod
    def _first_round_tasks(client: TMDBClient, topic_id: int) -> dict[str, Callable[[], Any]]:
        """Round 1: every independent TMDB call of the page, keyed by block name."""
        tasks = {
            "hero_movies": partial(client.get_list_with_trailers, "movie/popular", HOME_PAGE, "movie"),
            "trending_all_week": partial(client.get_trending, "all", "week"),
            "trending_all_day": partial(client.get_trending, "all", "day"),
            "trending_movie_week": partial(client.get_trending, "movie", "week"),
            "trending_people": partial(client.get_trending, "person", "week"),
            "now_playings": partial(client.get_list, "movie/now_playing", HOME_PAGE),
            "upcoming": partial(client.get_list, "movie/upcoming", HOME_PAGE),
            "tv_serials_popular": partial(client.get_list, "tv/popular", HOME_PAGE),
            "now_popular": partial(client.get_list, "movie/popular", HOME_PAGE),
            "top_rated": partial(client.get_list, "movie/top_rated", HOME_PAGE),
            "movie_genres": partial(client.get_genres, "movie"),
            "topic": partial(client.get_keyword, topic_id),
            "topic_movies": partial(client.get_keyword_movies, topic_id),
        }
        for slug, (genre_id, _icon) in MOODS.items():
            tasks[f"mood:{slug}"] = partial(
                client.get_list,
                "discover/movie",
                HOME_PAGE,
                ttl=TTL_LIST,
                with_genres=genre_id,
                **MOOD_DISCOVER_FILTERS,
            )
        for slug, (endpoint, filters) in TV_SHOWCASE.items():
            tasks[f"tv:{slug}"] = partial(client.get_list, endpoint, HOME_PAGE, ttl=TTL_LIST, **filters)
        return tasks

    @staticmethod
    def _second_round_tasks(
        client: TMDBClient, coming_soon: list[TMDBData], motw_item: TMDBData | None
    ) -> dict[str, Callable[[], Any]]:
        """Round 2: trailers for the Coming Soon cards and the Movie of the Week details (credits).

        Both come from the same cached get_details() request the detail page uses.
        These stay lambdas on purpose: motw_item["id"] is read inside the worker
        thread, so a malformed item only empties its own block (see fetch_parallel).
        """
        tasks = {"coming_soon": lambda: client.attach_trailers(coming_soon, "movie")}
        if motw_item:
            tasks["motw"] = lambda: client.get_details(motw_item["id"], "movie")
        return tasks

    @classmethod
    def _moods(cls, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Pick by Mood chips with their rows; only moods whose genre is in genre/movie/list."""
        genre_names = {genre["id"]: genre["name"] for genre in data.get("movie_genres") or []}
        return [
            {
                "slug": slug,
                "genre_id": genre_id,
                "icon": icon,
                "name": genre_names.get(genre_id),
                "items": cls._results(data, f"mood:{slug}"),
            }
            for slug, (genre_id, icon) in MOODS.items()
            if genre_id in genre_names
        ]

    @staticmethod
    def _topic(data: dict[str, Any]) -> dict[str, Any] | None:
        """Topic of the Day: the keyword plus its movies; None without either."""
        topic_movies = data.get("topic_movies") or {}
        if data.get("topic") and topic_movies.get("results"):
            return {**data["topic"], "movies": topic_movies["results"], "total": topic_movies.get("total_results")}
        return None

    @classmethod
    def _tv_showcase(cls, data: dict[str, Any]) -> list[dict[str, Any]]:
        """TV & Categories tabs: label, catalog link and items for each of TV_SHOWCASE_TABS."""
        return [
            {
                "slug": slug,
                "label": label,
                "url": reverse(url_name),
                "items": cls._results(data, "tv_serials_popular") if slug == "tv" else cls._results(data, f"tv:{slug}"),
            }
            for slug, label, url_name in TV_SHOWCASE_TABS
        ]


# == Search ==


class SerachView(View):
    """Search page (`?q=`): local title matches plus TMDB search/multi, as local Movies rows."""

    def get(self, request: HttpRequest) -> HttpResponse:
        query = request.GET.get("q", "").strip()
        results = []

        watched_map = {}
        if request.user.is_authenticated:
            watched_map = {w.movie.tmdb_id: w for w in Watchlist.objects.filter(user=request.user)}

        if query:
            # matched: ordered, deduped list of (tmdb_id, media_type) pairs -
            # cached per normalized query for 7 days (see cache_search_results).
            # It never carries per-user state (watched/watchlist_id), same rule
            # AllMoviesView follows for its own caching.
            matched = cache_search_results(query, self._search_fetcher(query))

            # genres is a ManyToManyField, so movie.genres.all() in the template
            # is a separate DB query per movie (20 movies = 20 extra queries).
            # prefetch_related("genres") loads all of them in one extra query
            # up front instead, so Django reuses that instead of hitting the DB
            # again per movie. Same results, fewer round trips - with TMDB
            # calls now skipped on a cache hit, this was the next biggest cost.
            movies_by_id = {
                m.tmdb_id: m
                for m in Movies.objects.filter(tmdb_id__in=[tmdb_id for tmdb_id, _ in matched]).prefetch_related(
                    "genres"
                )
            }

            for tmdb_id, media_type in matched:
                # Normally a cache hit already has the row (fetch() below only
                # ever caches ids it just created/found locally). Falls back to
                # a fresh TMDB fetch only if the local row was since removed.
                movie = movies_by_id.get(tmdb_id) or get_or_create_media(tmdb_id, media_type)
                if movie is None:
                    continue

                if movie.tmdb_id in watched_map:
                    watchlist_obj = watched_map[movie.tmdb_id]
                    movie.is_watched = watchlist_obj.watched
                    movie.watchlist_id = watchlist_obj.id

                results.append(movie)

        return render(request, "movies/search.html", {"query": query, "results": results})

    @staticmethod
    def _search_fetcher(query: str) -> Callable[[], list[tuple[int, str]]]:
        # Reproduces the original (pre-cache) search exactly: local title
        # match first, then TMDB search/multi, deduped by tmdb_id. The only
        # difference is it returns (tmdb_id, media_type) pairs instead of the
        # Movies objects themselves, so the result is JSON-cacheable.
        def fetch():
            seen_ids = set()
            matched = []

            local_movies = Movies.objects.filter(title__icontains=query)
            for movie in local_movies:
                if movie.tmdb_id and movie.tmdb_id not in seen_ids:
                    matched.append((movie.tmdb_id, movie.media_type))
                    seen_ids.add(movie.tmdb_id)

            tmdb_results = TMDBClient().search_movies(query)  # Returns a list of movies and TV shows from TMDB

            for item in tmdb_results:  # Each item is a dictionary with TMDB data
                media_type = item.get("media_type")
                if media_type not in ["movie", "tv"]:
                    continue

                tmdb_id = item["id"]
                if tmdb_id in seen_ids:
                    continue

                obj = get_or_create_media(tmdb_id, media_type)  # still does the real TMDB detail fetch, once
                # None if TMDB had no data for this id (added check - original
                # code would crash here with AttributeError). continue = skip
                # this item, go to the next one in tmdb_results.
                if obj is None:
                    continue

                matched.append((tmdb_id, media_type))
                seen_ids.add(tmdb_id)

            if not matched:
                # Don't cache an empty result: it's indistinguishable here from
                # a transient TMDB failure (search/multi silently returns no
                # results on error rather than raising), so a real outage
                # would otherwise get cached as "no results" for 7 days.
                raise TMDBFetchError([])

            return matched

        return fetch


@require_GET
def search_suggest(request: HttpRequest) -> JsonResponse:
    """JSON for the header search dropdown: up to 6 movie/TV matches. 502 if TMDB fails."""
    query = " ".join(request.GET.get("q", "").split())[:100]
    if len(query) < 2:
        return JsonResponse({"results": []})
    try:
        items = TMDBClient().suggest(query)
    except (TMDBFetchError, requests.RequestException):
        return JsonResponse({"error": "TMDB unavailable"}, status=502)
    results = [
        {
            "title": item.get("title") or "",
            "year": (item.get("release_date") or "")[:4],
            "media_type": item["media_type"],
            "poster_url": item.get("poster_url"),
            "rating": round(item["vote_average"], 1) if item.get("vote_average") else None,
            "url": reverse("movie-detail", args=[item["id"], item["media_type"]]),
        }
        for item in items
    ]
    return JsonResponse({"results": results})


# == Local Movies rows ==


def get_country(data: TMDBData, media_type: str) -> list[str]:
    """Country codes of a TMDB movie/{id} or tv/{id} response.

    Args:
        data: the TMDB response.
        media_type: "movie" or "tv".

    Returns:
        A list of ISO 3166-1 codes, e.g. ['US', 'UA'].
    """

    if media_type == "tv":
        # For TV shows, use the origin_country field
        return data.get("origin_country", [])
    else:
        # For movies, extract data from production_countries
        production_countries = data.get("production_countries", [])
        return [country["iso_3166_1"] for country in production_countries]


def get_or_create_media(tmdb_id: int, media_type: str = "movie", data: TMDBData | None = None) -> Movies | None:
    """The local Movies row for a TMDB movie/TV show, created from TMDB data if missing.

    `data`: an already fetched movie/{id} or tv/{id} response (the detail page
    passes get_details()), so creating the local row costs no extra TMDB call.
    Without it the details are fetched here. Returns None if TMDB has no data.
    An existing row keeps its fields; only its genres are re-synced.
    """
    client = TMDBClient()
    is_movie = media_type == "movie"

    if data is None:
        data = client.get_movie_by_tmdb_id(tmdb_id) if is_movie else client.get_tv_by_tmdb_id(tmdb_id)
    if not data:
        return None

    title = data.get("title" if is_movie else "name")
    raw_date = data.get("release_date" if is_movie else "first_air_date")

    # Get country codes for both movies and TV shows
    country_code = get_country(data, media_type)

    # Convert country codes to full country names
    normalize = normalize_countries(country_code)

    poster_path = data.get("poster_path")
    companies = data.get("production_companies")
    movie, created = Movies.objects.get_or_create(
        tmdb_id=tmdb_id,
        defaults={
            "title": title,
            "description": data.get("overview", ""),
            "poster_url": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "",
            "media_type": media_type,
            "tmdb_rating": data.get("vote_average"),
            "country": normalize,
            "author": companies[0]["name"] if companies else "",
        },
    )

    if created and raw_date:
        try:
            movie.release_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            movie.release_date = None
    movie.save()

    movie.genres.clear()  # Remove all existing genres
    for genre_data in data.get("genres", []):
        genre_obj, _ = Genre.objects.get_or_create(  # genre_obj represents a single genre
            tmdb_id=genre_data["id"], defaults={"name": genre_data["name"]}
        )
        if not movie.genres.filter(
            tmdb_id=genre_obj.tmdb_id
        ).exists():  # Add the genre if it is not already assigned to this movie
            movie.genres.add(genre_obj)

    return movie


# == Detail ==


class MoviesDetailView(View):
    """Movie / TV detail page: TMDB details, the local row's comments and ratings, watchlist state.

    TV pages add the seasons block, movie pages the collection block.
    """

    def get(self, request: HttpRequest, pk: int, media_type: str = "movie") -> HttpResponse:
        client = TMDBClient()
        # One cached TMDB request: details + videos, credits, images, keywords,
        # recommendations and release dates / content ratings (get_details).
        details = client.get_details(pk, media_type)
        has_details = bool(details.get("id"))

        data = Movies.objects.filter(tmdb_id=pk).first()
        if not data:
            data = get_or_create_media(pk, media_type, details if has_details else None)

        crew = details.get("crew", {})
        director = {"name": crew["director"][0]} if crew.get("director") else None
        gallery = details.get("backdrops", [])

        context = {
            "data": data,
            "details": details if has_details else None,
            "director": director,
            "crew": crew,
            "cast": details.get("cast", [])[:DETAIL_CAST_LIMIT],
            "trailer": details.get("trailer"),
            "gallery": gallery,
            "posters": details.get("posters", []),
            "recommendations": details.get("recommendations", []),
        }
        if media_type == "tv":
            context.update(self._seasons_context(request, client, pk, details))
        elif has_details:
            context.update(self._collection_context(client, details))

        if data:
            context.update(_comments_context(request, data))
            context["ratings_count"] = data.ratings.count()
            if request.user.is_authenticated:
                # initial state of the watchlist toggle and the watched (eye) button, rendered server-side (no flicker)
                entry = Watchlist.objects.filter(user=request.user, movie=data).values("id", "watched").first()
                context["watchlist_id"] = entry["id"] if entry else None
                context["is_watched"] = bool(entry and entry["watched"])

        return render(request, "movies/movies_detail.html", context)

    @staticmethod
    def _seasons_context(request: HttpRequest, client: TMDBClient, pk: int, details: TMDBData) -> dict[str, Any]:
        """Season chips from the details response; episodes only for the selected season (?season=N).

        Default season: the latest one that has already started airing (skips
        specials = season 0 and announced seasons with no episodes yet).
        """
        seasons = [s for s in details.get("seasons", []) if s.get("season_number") and s.get("episode_count")]
        if not seasons:
            return {"seasons": [], "season": None}
        numbers = [s["season_number"] for s in seasons]
        try:
            selected = int(request.GET.get("season", ""))
        except ValueError:
            selected = None
        if selected not in numbers:
            today = date.today().isoformat()
            aired = [s["season_number"] for s in seasons if s.get("air_date") and s["air_date"] <= today]
            selected = aired[-1] if aired else numbers[0]
        return {
            "seasons": seasons,
            "selected_season": selected,
            "season": client.get_season(pk, selected),
        }

    @staticmethod
    def _collection_context(client: TMDBClient, details: TMDBData) -> dict[str, Any]:
        """The movie's collection with its rating range and released parts; no_collection if it has none."""
        info = details.get("belongs_to_collection")
        if not info:
            return {"no_collection": True}  # nothing to show, not a failure
        collection = client.get_collection(info["id"])
        if collection:
            rated = [p["vote_average"] for p in collection["parts"] if p.get("vote_count")]
            collection["rating_range"] = (min(rated), max(rated)) if rated else None
            collection["released"] = [p for p in collection["parts"] if p.get("release_date")]
        return {"collection": collection}


# == AI ==


@login_required
def ai_recomendations(request: HttpRequest) -> JsonResponse:
    """Queue an AI recommendation task; returns {"task_id": ...}, or 429 over the per-user limit."""
    message = request.GET.get("message", "")
    media_type = request.GET.get("type", "all")

    throttle = AIRecommendationThrottle()
    if not throttle.allow_request(request, view=None):
        wait_seconds = throttle.wait() or 3600
        minutes = max(1, round(wait_seconds / 60))
        return JsonResponse(
            {
                "error": f"AI request limit exceeded. Please try again in {minutes} minutes.",
                "retry_after": round(wait_seconds),
            },
            status=429,
        )

    task = get_ai_recommendation_task.delay(request.user.id, message, media_type)
    return JsonResponse({"task_id": task.id})


@login_required
def ai_recommendation_status(request: HttpRequest, task_id: str) -> JsonResponse:
    """Poll an AI task: {"status": "pending"/"started"/...}, "done" with the result, or "failed" with the error."""
    task = AsyncResult(task_id)

    if not task.ready():
        # PENDING/STARTED/RETRY -> lowercase to keep the response shape uniform
        return JsonResponse({"status": task.state.lower()})

    if task.successful():
        return JsonResponse({"status": "done", "result": task.result})

    # Celery marks the task FAILURE only when get_ai() itself raised — it
    # normally catches its own errors and returns {"error": ...} instead,
    # which is covered by the "done" branch above.
    return JsonResponse({"status": "failed", "error": str(task.result)})


# == Comments ==
# Server-rendered HTMX fragments (templates under movies/partials/comments/).
# Error responses are retargeted into the section's #cm-flash box, see _comment_error().


def _comment_error(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(request, "movies/partials/comments/flash.html", {"message": message}, status=status)
    response["HX-Retarget"] = "#cm-flash"
    response["HX-Reswap"] = "innerHTML"
    return response


def _throttled_error(request: HttpRequest, throttle: CommentCreateThrottle | CommentVoteThrottle) -> HttpResponse:
    minutes = max(1, math.ceil((throttle.wait() or 60) / 60))
    return _comment_error(request, f"Too many requests. Try again in {minutes} min.", 429)


def comment_login_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Like @login_required, but answers anonymous users with a 401 flash message instead of a redirect.

    @login_required would answer with a 302 to the login page, which HTMX
    follows and then swaps the whole login page into the comment list.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _comment_error(request, "Log in to do that.", 401)
        return view(request, *args, **kwargs)

    return wrapper


def _compose_context(request: HttpRequest, movie: Movies, form: CommentForm | None = None) -> dict[str, Any]:
    # `form` is passed back in on a validation error so the textarea keeps what the user typed
    return {
        "movie": movie,
        "movie_url": reverse("movie-detail", args=[movie.tmdb_id, movie.media_type]),
        "form": form or CommentForm(),
        "comment_max_length": COMMENT_MAX_LENGTH,
    }


def _feed_context(request: HttpRequest, movie: Movies, sort: str | None = None, offset: int = 0) -> dict[str, Any]:
    sort = normalize_sort(sort)
    # Offset (the number of comments already on screen) instead of a page
    # number: deleting your own comment shifts both sides by one, so
    # "Show more" neither skips nor repeats a comment.
    window = list(movie_comments(movie, request.user, sort)[offset : offset + COMMENTS_PER_PAGE + 1])
    return {
        "movie": movie,
        "sort": sort,
        "sort_options": COMMENT_SORT_OPTIONS,
        "comments": window[:COMMENTS_PER_PAGE],
        "has_more": len(window) > COMMENTS_PER_PAGE,
        "total": Comment.objects.filter(movie=movie).count(),  # whole thread, not just the visible batch
        "comment_max_length": COMMENT_MAX_LENGTH,
    }


def _comments_context(request: HttpRequest, movie: Movies, form: CommentForm | None = None) -> dict[str, Any]:
    return {**_compose_context(request, movie, form), **_feed_context(request, movie)}


@require_GET
def comment_list(request: HttpRequest, movie_id: int) -> HttpResponse:
    """Comment feed fragment: the whole feed for a sort switch, or the next batch with `append=1`."""
    movie = get_object_or_404(Movies, pk=movie_id)
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        offset = 0
    context = _feed_context(request, movie, request.GET.get("sort"), offset)
    # append=1 -> only the next batch + a fresh "Show more" button; otherwise the whole feed (sort switch)
    template = "page.html" if request.GET.get("append") else "feed.html"
    return render(request, f"movies/partials/comments/{template}", context)


@require_POST
@comment_login_required
def comment_create(request: HttpRequest, movie_id: int) -> HttpResponse:
    """Post a comment; re-renders the feed from the top, or the form with errors (422)."""
    movie = get_object_or_404(Movies, pk=movie_id)
    # The throttle is checked before validation on purpose: rejected (blank/too long)
    # submissions count towards the limit too, so they can't be used to hammer the endpoint.
    throttle = CommentCreateThrottle()
    if not throttle.allow_request(request, view=None):
        return _throttled_error(request, throttle)

    form = CommentForm(request.POST)
    if not form.is_valid():
        return render(
            request, "movies/partials/comments/compose.html", _compose_context(request, movie, form), status=422
        )

    # movie and user come from the URL/session, never from POST data
    form.instance.movie = movie
    form.instance.user = request.user
    form.save()

    # The new comment is shown by re-rendering the feed from the top, sorted "Newest"
    return render(request, "movies/partials/comments/created.html", _comments_context(request, movie))


@require_POST
@comment_login_required
def comment_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete your own comment; returns the new comment total."""
    comment = get_object_or_404(Comment.objects.select_related("movie"), pk=pk)
    # Authors only; there is no edit flow, deleting is the one thing an author can do to their comment.
    # Votes are removed with the comment (CASCADE).
    if comment.user_id != request.user.id:
        security_event(
            "comment_delete_denied",
            request,
            logging.WARNING,
            comment_id=pk,
            user_id=request.user.pk,
            owner_id=comment.user_id,
        )
        return _comment_error(request, "You can only delete your own comments.", 403)

    movie = comment.movie
    comment.delete()
    security_event("comment_deleted", request, comment_id=pk, movie_id=movie.pk, user_id=request.user.pk)
    context = {"total": Comment.objects.filter(movie=movie).count()}
    return render(request, "movies/partials/comments/deleted.html", context)


@require_POST
@comment_login_required
def comment_vote(request: HttpRequest, pk: int) -> HttpResponse:
    """Like (1) / dislike (-1) someone else's comment; voting the same way again removes the vote."""
    comment = get_object_or_404(Comment, pk=pk)
    # Cheap input checks come before the throttle so a malformed request doesn't burn the voter's quota.
    # toggle_vote() re-checks the own-comment rule; the check here just gives a flash message instead of a 500.
    try:
        value = int(request.POST.get("value", ""))
    except ValueError:
        value = 0
    if value not in (CommentVote.LIKE, CommentVote.DISLIKE):
        return _comment_error(request, "Invalid vote.", 400)
    if comment.user_id == request.user.id:
        return _comment_error(request, "You can't vote on your own comment.", 403)

    throttle = CommentVoteThrottle()
    if not throttle.allow_request(request, view=None):
        return _throttled_error(request, throttle)

    toggle_vote(comment, request.user, value)
    return render(request, "movies/partials/comments/votes.html", {"comment": get_annotated_comment(pk, request.user)})
