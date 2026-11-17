"""django-axes hooks (AXES_* in config/settings.py): which "username" a login attempt is counted
under, the lockout response and clearing a lockout.

Axes counts failed logins per (username, client IP) pair in the cache and, at AXES_FAILURE_LIMIT,
refuses that pair for AXES_COOLOFF_TIME, even with the right password. Its backend is first in
AUTHENTICATION_BACKENDS, so this covers every authenticate() call: the site's email login, /admin/,
allauth's /accounts/login/ and /api/token/ (see api.serializers for the API's 429).
"""

import math

from axes.utils import reset
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .client_ip import client_ip
from .emails import normalize_email

LOCKOUT_TEMPLATE = "users/lockout.html"


def cooloff_seconds() -> int:
    return int(settings.AXES_COOLOFF_TIME.total_seconds())


def lockout_message() -> str:
    minutes = math.ceil(cooloff_seconds() / 60)
    return f"Too many failed login attempts. Try again in {minutes} minutes."


def _login_field(data, credentials) -> str | None:
    # The site form and allauth's pages log in by email ("email" in the credentials; allauth's
    # form field is "login"), /admin/ and /api/token/ by username. user_logged_in only passes
    # {"username": <the account's username>}, so the typed-in value is read from the POST data
    # first: that's what lets a successful login clear the counter of the failures before it.
    for value in (credentials.get("email"), data.get("email"), data.get("login")):
        if value:
            return value
    return data.get("username") or credentials.get("username")


def axes_username(request: HttpRequest, credentials: dict | None) -> str | None:
    """AXES_USERNAME_CALLABLE: the typed-in email or username, trimmed and lowercased, so
    "John@Example.com " and "john@example.com" share one counter."""
    data = getattr(request, "data", None)  # DRF request (/api/token/): JSON or form body
    if not hasattr(data, "get"):
        data = getattr(request, "POST", {})
    value = _login_field(data, credentials or {})
    return normalize_email(str(value)) if value else None


def lockout_response(request: HttpRequest, original_response=None, credentials=None) -> HttpResponse:
    """AXES_LOCKOUT_CALLABLE: 429 with the site's page (or JSON for fetch() calls) instead of the
    login form, for the 5th wrong password and every attempt during the cool-off."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        response = JsonResponse({"detail": lockout_message()}, status=429)
    else:
        minutes = math.ceil(cooloff_seconds() / 60)
        response = render(request, LOCKOUT_TEMPLATE, {"minutes": minutes}, status=429)
    response["Retry-After"] = str(cooloff_seconds())
    return response


def clear_lockout(request: HttpRequest, user) -> None:
    """Drop the failed-login counters of this account from this client, e.g. after the user proved
    they own the email by completing a password reset."""
    ip = client_ip(request)
    for login in {normalize_email(user.email), normalize_email(user.get_username())} - {""}:
        reset(ip=ip, username=login)
