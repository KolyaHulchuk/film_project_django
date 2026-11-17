"""Rate limits on the site's password reset and sign-up forms (DRF throttles used outside DRF,
like movies/throttling.py). Counters live in the default cache (Redis)."""

import hashlib

from django.http import HttpRequest
from rest_framework.throttling import SimpleRateThrottle

from .client_ip import client_ip
from .emails import normalize_email


class ClientIPMixin:
    """Identify anonymous clients by users.client_ip instead of DRF's default, which uses the whole
    X-Forwarded-For header - a client can put anything there and get a fresh counter every time."""

    def get_ident(self, request: HttpRequest) -> str:
        return client_ip(request) or "unknown"


class _FixedRateThrottle(SimpleRateThrottle):
    def get_rate(self) -> str:
        return self.rate


class PasswordResetIPThrottle(ClientIPMixin, _FixedRateThrottle):
    """Reset requests per client IP, whatever addresses are typed in."""

    scope = "password_reset_ip"
    rate = "5/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PasswordResetEmailThrottle(_FixedRateThrottle):
    """Reset requests per typed-in address (from any IP), so one inbox can't be flooded. Counts
    unknown addresses too, so hitting the limit tells nothing about whether an account exists."""

    scope = "password_reset_email"
    rate = "3/hour"

    def __init__(self, email: str | None):
        self.email = normalize_email(email)
        super().__init__()

    def get_cache_key(self, request, view):
        if not self.email:
            return None  # nothing typed in: the form rejects it anyway
        digest = hashlib.sha256(self.email.encode()).hexdigest()  # no raw emails in cache keys
        return self.cache_format % {"scope": self.scope, "ident": digest}


class SignupIPThrottle(ClientIPMixin, _FixedRateThrottle):
    """Sign-up form submissions per client IP (valid or not: the form also tells whether an email
    is taken, so this caps that lookup too)."""

    scope = "signup_ip"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def throttle_wait(request: HttpRequest, *throttles: SimpleRateThrottle) -> int | None:
    """Check (and count) the throttles in order. None if all allow the request, else the seconds
    to wait. Stops at the first refusal, so later throttles don't count a refused request."""
    for throttle in throttles:
        if not throttle.allow_request(request, view=None):
            return int(throttle.wait() or 3600)
    return None
