import math
import time
from datetime import datetime
from functools import wraps

from celery.result import AsyncResult
from django.contrib.auth.decorators import login_required

# instance – the model object
# created – a boolean value:
# True if the object was created,
# False if it already existed in the database
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.decorators.http import require_GET, require_POST

from movies.tasks import get_ai_recommendation_task
from users.models import Watchlist

from .comments import COMMENTS_PER_PAGE, get_annotated_comment, movie_comments, normalize_sort, toggle_vote
from .forms import CommentForm
from .models import COMMENT_MAX_LENGTH, Comment, CommentVote, Genre, Movies
from .redis_services import TMDBFetchError, cache_search_results
from .throttling import AIRecommendationThrottle, CommentCreateThrottle, CommentVoteThrottle
from .tmdb_service import (
    TMDBClient,
)
from .utils import COUNTRY_CODES, normalize_countries


class AllMoviesView(View):
    """
    Base view for all movie and TV category pages.
    Subclasses override title, template_name, base_filters and media_type.
    """

    title = "Default Title"
    template_name = "movies/category/default.html"  # class attribute, can be overridden in subclasses
    parials_name = "movies/partials/movie_list.html"  # class attribute, overriden in subclasses
    item_func = None
    media_type = "movie"

    def get(self, request):
        view_start = time.perf_counter()
        client = TMDBClient()
        try:
            page = int(request.GET.get("page", 1))
        except ValueError:
            page = 1

        step_start = time.perf_counter()
        data = self.item_func(page)  #  Call the function that returns raw data from TMDB
        print(f"[timing] item_func/get_list: {(time.perf_counter() - step_start) * 1000:.1f}ms")

        total_pages = data.get("total_pages", 1)

        page = max(1, min(page, total_pages))

        step_start = time.perf_counter()
        genres = client.get_genres(self.media_type)
        print(f"[timing] get_genres: {(time.perf_counter() - step_start) * 1000:.1f}ms")

        step_start = time.perf_counter()
        items = client.annotate_items(
            data["results"], self.media_type, genres
        )  #  Add extra data for each item (rating, genres, etc.) from data already in the list response - no TMDB calls
        print(f"[timing] annotate_items: {(time.perf_counter() - step_start) * 1000:.1f}ms")

        if request.user.is_authenticated:
            step_start = time.perf_counter()
            watchlist = Watchlist.objects.filter(user=request.user).select_related("movie")

            watched_map = {}

            for w in watchlist:
                watched_map[w.movie.tmdb_id] = w

            for item in items:
                if item["id"] in watched_map:
                    watchlist_obj = watched_map[item["id"]]
                    item["is_watched"] = watchlist_obj.watched  # is_watched — flag from watchlist
                    item["watchlist_id"] = watchlist_obj.id
            print(f"[timing] watchlist_annotation: {(time.perf_counter() - step_start) * 1000:.1f}ms")

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
        }

        # # If the request comes from HTMX, render only the partial template
        if request.headers.get("HX-Request"):
            template = self.parials_name
        else:
            template = self.template_name

        step_start = time.perf_counter()
        response = render(request, template, context)
        print(f"[timing] render: {(time.perf_counter() - step_start) * 1000:.1f}ms")
        print(f"[timing] AllMoviesView.get total: {(time.perf_counter() - view_start) * 1000:.1f}ms")
        return response

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


class PopularActorView(View):
    # TMDB's "popular people" endpoint returns actors, directors, producers,
    # etc. mixed together; get_popular_actors() filters that down to actors
    # only, since the template just needs poster/name/one known-for title.
    def get(self, request):
        client = TMDBClient()
        try:
            page = int(request.GET.get("page", 1))
        except ValueError:
            page = 1

        context = client.get_popular_actors(page)

        return render(request, "movies/popular_actors.html", context)


class HomeView(View):
    def get(self, request):
        page = 1
        client = TMDBClient()

        now_playings = client.get_list("movie/now_playing", page)  # Fetch data from TMDB
        upcoming = client.get_list("movie/upcoming", page)
        tv_serilas_popular = client.get_list("tv/popular", page)
        now_popular = client.get_list("movie/popular", page)
        top_rated = client.get_list("movie/top_rated", page)
        filtered_upcoming = [
            m for m in upcoming["results"] if m["id"] not in {x["id"] for x in now_playings["results"]}
        ]
        filtered_now_playings = [
            m for m in now_playings["results"] if m["id"] not in {x["id"] for x in now_popular["results"]}
        ]
        actors = client.get_person().get("results", [])
        actors = [a for a in actors if a.get("known_for_department") == "Acting"]

        context = {
            "now_popular": now_popular["results"],
            "tv_serials_popular": tv_serilas_popular["results"],
            "top_rated": top_rated["results"],
            "now_playings": now_playings["results"],
            "upcoming": upcoming["results"],
            "filtered_upcoming": filtered_upcoming,
            "filtered_now_playings": filtered_now_playings,
            "actors": actors,
        }

        return render(request, "movies/home.html", context)


class SerachView(View):
    def get(self, request):
        query = request.GET.get("q", "").strip()
        results = []

        watched_map = {}

        if request.user.is_authenticated:
            watchlist = Watchlist.objects.filter(user=request.user)

            for w in watchlist:
                watched_map[w.movie.tmdb_id] = w

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
    def _search_fetcher(query):
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
            "poster_url": f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}"
            if data.get("poster_path")
            else "",
            "media_type": media_type,
            "tmdb_rating": data.get("vote_average"),
            "country": normalize,
            "author": data.get("production_companies")[0]["name"] if data.get("production_companies") else "",
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


class MoviesDetailView(View):
    def get(self, request, pk, media_type="movie"):
        data = Movies.objects.filter(tmdb_id=pk).first()
        if not data:
            data = get_or_create_media(pk, media_type)

        client = TMDBClient()
        credits = client.get_credit(pk, media_type)

        director = next((p for p in credits.get("crew", []) if p["job"] == "Director"), None)

        cast = credits.get("cast", [])[:12]
        trailer = credits.get("trailer")
        gallery = credits.get("backdrops", [])

        context = {
            "data": data,
            "director": director,
            "cast": cast,
            "trailer": trailer,
            "gallery": gallery,
        }
        if data:
            context.update(_comments_context(request, data))

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
        self.item_func = lambda page: TMDBClient().get_list("discover/tv", page, **filters)
        return super().get(request)


# Type tv/movie


class AnimeTVView(AllMoviesView):
    title = "Anime TV"
    template_name = "movies/type/anime.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_filters = {  # # Base TMDB query parameters
            "with_genres": 16,  # 16 = Animation in TMDB
            "with_original_language": "ja",  # Japan language
            "with_origin_country": "JP",  # Japanese production
            "max_page": 100,
        }

        self.media_type = "tv"

    def get(self, request):
        extra_filters = self.search_filter_movie(request)
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func = lambda page: TMDBClient().get_list("discover/tv", page, **filters)
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
        self.item_func = lambda page: TMDBClient().get_list("discover/tv", page, **filters)
        return super().get(request)


class CartoonTVView(AllMoviesView):
    title = "Cartoon TV"
    template_name = "movies/type/cartoons.html"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_filters = {"with_genres": 16, "with_origin_country": "US|GB|FR|CA|AU", "max_page": 100}
        self.media_type = "tv"

    def get(self, request):
        extra_filters = self.search_filter_movie(request)  # Additional filters from user input
        filters = {**self.base_filters, **(extra_filters or {})}
        self.item_func = lambda page: TMDBClient().get_list("discover/tv", page, **filters)
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
def ai_recommendation_status(request, task_id):
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


def _comment_error(request, message, status):
    response = render(request, "movies/partials/comments/flash.html", {"message": message}, status=status)
    response["HX-Retarget"] = "#cm-flash"
    response["HX-Reswap"] = "innerHTML"
    return response


def _throttled_error(request, throttle):
    minutes = max(1, math.ceil((throttle.wait() or 60) / 60))
    return _comment_error(request, f"Too many requests. Try again in {minutes} min.", 429)


def comment_login_required(view):
    # @login_required would answer with a 302 to the login page, which HTMX
    # follows and then swaps the whole login page into the comment list.
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _comment_error(request, "Log in to do that.", 401)
        return view(request, *args, **kwargs)

    return wrapper


def _compose_context(request, movie, form=None):
    # `form` is passed back in on a validation error so the textarea keeps what the user typed
    return {
        "movie": movie,
        "movie_url": reverse("movie-detail", args=[movie.tmdb_id, movie.media_type]),
        "form": form or CommentForm(),
        "comment_max_length": COMMENT_MAX_LENGTH,
    }


def _feed_context(request, movie, sort=None, offset=0):
    sort = normalize_sort(sort)
    # Offset (the number of comments already on screen) instead of a page
    # number: deleting your own comment shifts both sides by one, so
    # "Show more" neither skips nor repeats a comment.
    window = list(movie_comments(movie, request.user, sort)[offset : offset + COMMENTS_PER_PAGE + 1])
    return {
        "movie": movie,
        "sort": sort,
        "sort_options": [("new", "Newest"), ("old", "Oldest")],
        "comments": window[:COMMENTS_PER_PAGE],
        "has_more": len(window) > COMMENTS_PER_PAGE,
        "total": Comment.objects.filter(movie=movie).count(),  # whole thread, not just the visible batch
        "comment_max_length": COMMENT_MAX_LENGTH,
    }


def _comments_context(request, movie, form=None):
    return {**_compose_context(request, movie, form), **_feed_context(request, movie)}


@require_GET
def comment_list(request, movie_id):
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
def comment_create(request, movie_id):
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
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("movie"), pk=pk)
    # Authors only; there is no edit flow, deleting is the one thing an author can do to their comment.
    # Votes are removed with the comment (CASCADE).
    if comment.user_id != request.user.id:
        return _comment_error(request, "You can only delete your own comments.", 403)

    movie = comment.movie
    comment.delete()
    context = {"total": Comment.objects.filter(movie=movie).count()}
    return render(request, "movies/partials/comments/deleted.html", context)


@require_POST
@comment_login_required
def comment_vote(request, pk):
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
