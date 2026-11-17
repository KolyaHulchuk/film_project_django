import logging
import math
from collections.abc import Iterable
from typing import Any

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import DeleteView, ListView

from movies.models import Movies
from movies.views import get_or_create_media

from .emails import (
    DUPLICATE_EMAIL_MESSAGE,
    is_email_verified,
    mark_email_verified,
    replace_email_address,
    send_verification,
)
from .forms import ProfileUpdateForm, SitePasswordResetForm, UserRegisterForm, UserUpdateForm
from .lockout import clear_lockout
from .models import Watchlist
from .security_log import mask, security_event
from .throttling import PasswordResetEmailThrottle, PasswordResetIPThrottle, SignupIPThrottle, throttle_wait

logger = logging.getLogger(__name__)

# Watchlist page filter panel. Both lists are hardcoded, so the years go stale in 2027.
WATCHLIST_YEARS = range(2026, 2020, -1)
WATCHLIST_GENRES = ("Comedy", "Horror", "Adventure", "Action")

MOVIE_NOT_FOUND_MESSAGE = "Could not find data for this movie"


# == Auth & profile ==

SIGNUP_THROTTLED_MESSAGE = "Too many sign-up attempts from your network. Try again in {minutes} min."
PASSWORD_RESET_THROTTLED_MESSAGE = "Too many password reset requests. Try again in {minutes} min."


def _minutes(seconds: int) -> int:
    return max(1, math.ceil(seconds / 60))


def register(request: HttpRequest) -> HttpResponse:
    """Sign-up form. On success: send the verification link, flash a message and redirect home."""
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        wait = throttle_wait(request, SignupIPThrottle())
        if wait is not None:
            form.add_error(None, SIGNUP_THROTTLED_MESSAGE.format(minutes=_minutes(wait)))
            security_event("signup_throttled", request, logging.WARNING)
            return render(request, "users/register.html", {"form": form, "title": "Register"}, status=429)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except IntegrityError:
                # Concurrent request won the race for this email (DB unique index)
                form.add_error("email", DUPLICATE_EMAIL_MESSAGE)
            else:
                # The email starts unverified; logging in with the password does not verify it.
                send_verification(request, user)
                security_event("signup", request, user_id=user.pk, via="site")
                username = form.cleaned_data.get("username")
                messages.success(request, f"Your account has been created! You are now able to log in {username}")
                return redirect("movies-home")
    else:
        form = UserRegisterForm()

    context = {"form": form, "title": "Register"}
    return render(request, "users/register.html", context)


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    """Profile page: edit username, email and avatar; also shows the email-verified and Google-connected state."""
    if request.method == "POST":
        old_email = request.user.email  # form validation writes the new value onto request.user
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)

        if u_form.is_valid() and p_form.is_valid():
            email_changed = "email" in u_form.changed_data
            try:
                with transaction.atomic():
                    u_form.save()
            except IntegrityError:
                u_form.add_error("email", DUPLICATE_EMAIL_MESSAGE)
            else:
                p_form.save()
                if email_changed:
                    # A new address has to be verified again.
                    replace_email_address(request, request.user)
                    security_event(
                        "email_changed",
                        request,
                        user_id=request.user.pk,
                        old=mask(old_email),
                        new=mask(request.user.email),
                    )
                messages.success(request, "Your account has been update")

    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        "u_form": u_form,
        "p_form": p_form,
        "title": "Profile",
        "email_verified": is_email_verified(request.user),
        "google_connected": request.user.socialaccount_set.filter(provider="google").exists(),
    }

    return render(request, "users/profile.html", context)


@login_required
@require_POST
def resend_verification(request: HttpRequest) -> HttpResponse:
    """Profile button: re-send the confirmation link for the current email (allauth rate-limits repeats)."""
    if is_email_verified(request.user):
        messages.info(request, "Your email is already verified.")
    elif not send_verification(request, request.user):
        # allauth's rate limit (or no email set)
        messages.error(request, "Could not send the verification email right now. Please try again later.")
    return redirect("profile")


class SitePasswordResetView(auth_views.PasswordResetView):
    """Django's "send me a reset link" form, rate limited per client IP and per typed-in address
    (users/throttling.py). A refused request sends nothing and shows the form with an error."""

    template_name = "users/password_reset.html"
    form_class = SitePasswordResetForm

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        email = request.POST.get("email")
        wait = throttle_wait(request, PasswordResetIPThrottle(), PasswordResetEmailThrottle(email))
        if wait is None:
            return super().post(request, *args, **kwargs)
        form = self.get_form()
        form.add_error(None, PASSWORD_RESET_THROTTLED_MESSAGE.format(minutes=_minutes(wait)))
        security_event("password_reset_throttled", request, logging.WARNING, ident=mask(email))
        return self.render_to_response(self.get_context_data(form=form), status=429)


class SitePasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Django's "set a new password" step that also marks the user's email as verified
    and lifts a login lockout (users/lockout.py) of this account from this client."""

    def form_valid(self, form: SetPasswordForm) -> HttpResponse:
        response = super().form_valid(form)
        # Following the emailed link proves the user owns this address.
        mark_email_verified(form.user)
        clear_lockout(self.request, form.user)
        security_event("password_reset_completed", self.request, user_id=form.user.pk, via="site")
        return response


# == Watchlist ==


def wants_json(request: HttpRequest) -> bool:
    """True for fetch() calls from static/movies/watchlist_toggle.js (plain form posts keep redirect + messages)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@method_decorator(login_required, name="dispatch")
class AddToWatchlist(View):
    """POST: add a TMDB title to the user's watchlist, creating its local Movies row if needed."""

    def post(self, request: HttpRequest, tmdb_id: int, media_type: str) -> HttpResponse:
        movie = get_or_create_media(tmdb_id, media_type)
        if wants_json(request):
            return self._json_response(request, movie)
        return self._form_response(request, movie)

    @staticmethod
    def _json_response(request: HttpRequest, movie: Movies | None) -> JsonResponse:
        """The entry's id and remove URL for watchlist_toggle.js, or a 404 when there's no movie data."""
        if not movie:
            return JsonResponse({"ok": False, "error": MOVIE_NOT_FOUND_MESSAGE}, status=404)
        item, created = Watchlist.objects.get_or_create(user=request.user, movie=movie)
        return JsonResponse(
            {
                "ok": True,
                "in_watchlist": True,
                "created": created,
                "watchlist_id": item.id,
                "remove_url": reverse("delete_watchlist", args=[item.id]),
            }
        )

    @staticmethod
    def _form_response(request: HttpRequest, movie: Movies | None) -> HttpResponse:
        """A flash message, then a redirect to POST `next` or, without it, to the home page."""
        if movie:
            _, created = Watchlist.objects.get_or_create(user=request.user, movie=movie)
            title = movie.title or movie.name
            if created:
                messages.success(request, f"{title} added to your watchlist")
            else:
                messages.info(request, f"{title} is already in your watchlist")
        else:
            messages.error(request, MOVIE_NOT_FOUND_MESSAGE)
        next_url = request.POST.get("next") or request.META.get("HTTP-REFERER") or "movies-home"
        logger.debug("AddToWatchlist: user_id=%s redirect to %r", request.user.pk, next_url)

        return redirect(next_url)


@method_decorator(login_required, name="dispatch")
class DeleteWatchlist(DeleteView):
    """DELETE: remove one of the user's watchlist entries."""

    model = Watchlist

    def get_queryset(self) -> QuerySet[Watchlist]:
        """Only the current user's entries, so someone else's id is a 404."""
        return Watchlist.objects.filter(user=self.request.user)

    def delete(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """JSON for fetch(), an empty 200 for HTMX (the card is swapped out), otherwise a redirect to the watchlist."""
        self.object = self.get_object()
        self.object.delete()

        if wants_json(request):
            return JsonResponse({"ok": True, "in_watchlist": False})
        if request.headers.get("HX-Request"):
            return HttpResponse("")
        return redirect("watchlist")


@login_required
def toggle_watched(request: HttpRequest, watchlist_id: int) -> HttpResponse | None:
    """POST: flip the entry's `watched` flag and answer "OK". Any other method returns None."""
    item = Watchlist.objects.get(id=watchlist_id, user=request.user)
    if request.method == "POST":
        item.watched = not item.watched
        item.save()
        return HttpResponse("OK")


def _param(request: HttpRequest, name: str) -> str:
    """A GET parameter with surrounding whitespace stripped; "" when it's missing."""
    return (request.GET.get(name) or "").strip()


def _rating_bounds(value: str) -> tuple[float, float] | None:
    """The half-open range [rating, rating + 1) for a rating filter, or None if it isn't a number."""
    try:
        rating = float(value)
    except ValueError:
        return None
    return rating, rating + 1


@login_required
def search_watchlist(request: HttpRequest) -> HttpResponse:
    """HTMX filter of the Watchlist page: the user's entries narrowed by every non-blank GET filter.

    years_search, country_search, genre_search and name_search are case-insensitive substring
    matches on the related movie's release date, country, genre names and title; rating_search=7
    keeps ratings in [7, 8). A non-numeric rating is ignored. Renders the results partial.
    """
    watchlist_items = Watchlist.objects.filter(user=request.user)

    years_search = _param(request, "years_search")
    if years_search:
        watchlist_items = watchlist_items.filter(movie__release_date__icontains=years_search)

    country_search = _param(request, "country_search")
    if country_search:
        watchlist_items = watchlist_items.filter(movie__country__icontains=country_search)

    genre_search = _param(request, "genre_search")
    if genre_search:
        watchlist_items = watchlist_items.filter(movie__genres__name__icontains=genre_search)

    rating_bounds = _rating_bounds(_param(request, "rating_search"))
    if rating_bounds:
        low, high = rating_bounds
        watchlist_items = watchlist_items.filter(movie__tmdb_rating__gte=low, movie__tmdb_rating__lt=high)

    name_search = _param(request, "name_search")
    if name_search:
        watchlist_items = watchlist_items.filter(movie__title__icontains=name_search)

    return render(
        request,
        "users/partials/watchlist_result.html",
        {
            "watchlist": watchlist_items,
        },
    )


def _split_countries(values: Iterable[str]) -> list[str]:
    """Sorted unique names from Movies.country values, each of which may list several countries.

    A blank value is skipped, but an empty part after a stray comma is kept as "".
    """
    countries: set[str] = set()
    for value in values:
        if value:
            countries.update(part.strip() for part in value.split(","))
    return sorted(countries)


@method_decorator(login_required, name="dispatch")
class WatchlistView(ListView):
    """The Watchlist page: the user's entries, newest first, 20 per page, plus the filter panel options."""

    model = Watchlist
    template_name = "users/watchlist.html"
    context_object_name = "watchlist"
    paginate_by = 20

    def get_queryset(self) -> QuerySet[Watchlist]:
        return Watchlist.objects.filter(user=self.request.user).order_by("-id")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add `years`, `genres` and `countries` (taken from all the user's entries, not just this page)."""
        context = super().get_context_data(**kwargs)

        context["years"] = WATCHLIST_YEARS
        context["genres"] = list(WATCHLIST_GENRES)

        # A separate query, not get_queryset(): its ORDER BY id would be added to the DISTINCT.
        countries = Watchlist.objects.filter(user=self.request.user).values_list("movie__country", flat=True).distinct()
        context["countries"] = _split_countries(countries)

        return context
