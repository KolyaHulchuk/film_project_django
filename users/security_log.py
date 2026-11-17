"""Security event log: one line per event on the "security" logger (stdout, see LOGGING in config/settings.py).

Line format: ``<event> key=value ... ip=... path=...``, e.g.
``login_failed ident='jo***@example.com' ip='10.0.0.1' path='/users/login/'``, so `grep login_failed`
on the Render logs finds every failed login.

Events written by the signal receivers below:
login, login_failed, logout (site, /admin/, allauth and Google), signup (allauth and Google),
password_changed / password_set / password_reset_completed (allauth's own pages), email_confirmed,
email_changed (allauth's own pages), google_connected, google_disconnected.
Written directly by the views: signup (site form), password_reset_requested, password_reset_completed,
email_changed (profile), comment_deleted / comment_delete_denied, login via /api/token/
(api.serializers.LoggedTokenObtainPairSerializer), google_login_refused (users.adapters).

Never logged: passwords (Django's user_login_failed already replaces them with stars), tokens,
session ids. An email or username typed into a login/reset form is masked (`mask()`), because anyone
can type anyone's address there and the logs shouldn't become a list of other people's emails.
"""

import logging
from typing import Any

from allauth.account import signals as account_signals
from allauth.socialaccount import signals as social_signals
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.http import HttpRequest

logger = logging.getLogger("security")


def mask(value: str | None) -> str:
    """The first two characters of an email's local part or a username, then ***: "jo***@example.com"."""
    value = (value or "").strip()
    if not value:
        return "-"
    local, at, domain = value.partition("@")
    return f"{local[:2]}***{at}{domain}"


def _format(value: Any) -> str:
    # repr() for strings: quotes them and escapes newlines, so a crafted value
    # (a path, a username, a forwarded-for header) can't forge extra log lines.
    return repr(value) if isinstance(value, str) else str(value)


def _request_fields(request: HttpRequest | None) -> dict[str, Any]:
    """Client address and path of the request. `fwd` is X-Forwarded-For as received: on Render
    REMOTE_ADDR is the proxy, and the real client is in that header (which the client can prepend to)."""
    if request is None:
        return {}
    meta = getattr(request, "META", {})
    fields = {"ip": meta.get("REMOTE_ADDR") or "-"}
    if meta.get("HTTP_X_FORWARDED_FOR"):
        fields["fwd"] = meta["HTTP_X_FORWARDED_FOR"]
    fields["path"] = getattr(request, "path", "-")
    return fields


def security_event(event: str, request: HttpRequest | None = None, level: int = logging.INFO, **fields: Any) -> None:
    """Write one security log line: the event name, the given fields, then the request's ip/fwd/path."""
    parts = [event]
    parts += [f"{key}={_format(value)}" for key, value in {**fields, **_request_fields(request)}.items()]
    logger.log(level, "%s", " ".join(parts))


def _user_id(user: Any) -> Any:
    return getattr(user, "pk", None)


def _backend_name(user: Any) -> str:
    # Set by authenticate()/login(): EmailBackend (site form), ModelBackend (/admin/),
    # AuthenticationBackend (allauth's pages and Google).
    return (getattr(user, "backend", "") or "-").rsplit(".", 1)[-1]


# == Django auth signals (site form, /admin/, allauth, Google, /api/token/ failures) ==


@receiver(user_logged_in, dispatch_uid="security_log_login")
def log_login(sender, request, user, **kwargs):
    security_event("login", request, user_id=_user_id(user), backend=_backend_name(user))


@receiver(user_login_failed, dispatch_uid="security_log_login_failed")
def log_login_failed(sender, credentials, request=None, **kwargs):
    # credentials: {"email": ...} from the site form and allauth, {"username": ...} from /admin/ and /api/token/
    ident = credentials.get("email") or credentials.get("username")
    security_event("login_failed", request, logging.WARNING, ident=mask(ident))


@receiver(user_logged_out, dispatch_uid="security_log_logout")
def log_logout(sender, request, user, **kwargs):
    security_event("logout", request, user_id=_user_id(user))


# == allauth signals (its own /accounts/... pages and Google) ==


@receiver(account_signals.user_signed_up, dispatch_uid="security_log_signup")
def log_allauth_signup(sender, request, user, **kwargs):
    via = "google" if kwargs.get("sociallogin") else "allauth"
    security_event("signup", request, user_id=_user_id(user), via=via)


@receiver(account_signals.password_changed, dispatch_uid="security_log_password_changed")
def log_password_changed(sender, request, user, **kwargs):
    security_event("password_changed", request, user_id=_user_id(user), via="allauth")


@receiver(account_signals.password_set, dispatch_uid="security_log_password_set")
def log_password_set(sender, request, user, **kwargs):
    security_event("password_set", request, user_id=_user_id(user), via="allauth")


@receiver(account_signals.password_reset, dispatch_uid="security_log_password_reset")
def log_allauth_password_reset(sender, request, user, **kwargs):
    security_event("password_reset_completed", request, user_id=_user_id(user), via="allauth")


@receiver(account_signals.email_confirmed, dispatch_uid="security_log_email_confirmed")
def log_email_confirmed(sender, request, email_address, **kwargs):
    security_event("email_confirmed", request, user_id=email_address.user_id)


@receiver(account_signals.email_changed, dispatch_uid="security_log_email_changed")
def log_allauth_email_changed(sender, request, user, from_email_address=None, to_email_address=None, **kwargs):
    security_event(
        "email_changed",
        request,
        user_id=_user_id(user),
        old=mask(getattr(from_email_address, "email", None)),
        new=mask(getattr(to_email_address, "email", None)),
        via="allauth",
    )


@receiver(social_signals.social_account_added, dispatch_uid="security_log_social_added")
def log_social_account_added(sender, request, sociallogin, **kwargs):
    # Both the profile's "Connect Google" and the automatic link to a verified local email (users.adapters).
    account = sociallogin.account
    security_event("google_connected", request, user_id=account.user_id, provider=account.provider)


@receiver(social_signals.social_account_removed, dispatch_uid="security_log_social_removed")
def log_social_account_removed(sender, request, socialaccount, **kwargs):
    security_event("google_disconnected", request, user_id=socialaccount.user_id, provider=socialaccount.provider)
