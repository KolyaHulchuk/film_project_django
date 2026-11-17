"""Security event log (users/security_log.py): which actions write a line to the "security" logger,
and that passwords and full typed-in emails never end up in it."""

import logging
import re

import pytest
from allauth.account.models import EmailAddress
from allauth.core import context
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils.log import AdminEmailHandler
from rest_framework.test import APIClient

from movies.models import Comment, Movies
from users.security_log import mask, security_event

PASSWORD = "Password_123"
NEW_PASSWORD = "Another_Pass_456"


@pytest.fixture
def security_log(caplog):
    """The "security" records written during the test, as (level name, message) pairs."""
    caplog.set_level(logging.INFO, logger="security")

    def records():
        return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "security"]

    return records


def messages_of(records, event):
    return [message for _level, message in records() if message.split(" ", 1)[0] == event]


def assert_no_secrets(records, *secrets):
    for _level, message in records():
        for secret in secrets:
            assert secret not in message


@pytest.fixture
def user(db):
    return User.objects.create_user("john", email="john@example.com", password=PASSWORD)


# == mask() / security_event() ==


@pytest.mark.parametrize(
    "value, masked",
    [
        ("john@example.com", "jo***@example.com"),
        ("  k@example.com ", "k***@example.com"),
        ("admin", "ad***"),
        ("", "-"),
        (None, "-"),
    ],
)
def test_mask(value, masked):
    assert mask(value) == masked


def test_event_line_has_fields_then_request_ip_and_path(security_log):
    request = RequestFactory().get("/users/login/", REMOTE_ADDR="10.0.0.7", HTTP_X_FORWARDED_FOR="1.2.3.4")

    security_event("login", request, user_id=5, backend="EmailBackend")

    assert security_log() == [
        ("INFO", "login user_id=5 backend='EmailBackend' ip='10.0.0.7' fwd='1.2.3.4' path='/users/login/'")
    ]


def test_crafted_values_cannot_forge_extra_log_lines(security_log):
    request = RequestFactory().get("/x%0Alogin%20user_id=1")  # the path decodes to "/x\nlogin user_id=1"

    security_event("login_failed", request, logging.WARNING, ident="a\nb")

    [(level, message)] = security_log()
    assert level == "WARNING"
    assert "\n" not in message
    assert r"path='/x\nlogin user_id=1'" in message


# == Logins and logouts ==


@pytest.mark.django_db
def test_site_login_is_logged(client, user, security_log):
    client.post("/users/login/", {"email": "john@example.com", "password": PASSWORD})

    [message] = messages_of(security_log, "login")
    assert f"user_id={user.pk}" in message
    assert "backend='EmailBackend'" in message
    assert "path='/users/login/'" in message
    assert_no_secrets(security_log, PASSWORD)


@pytest.mark.django_db
def test_failed_site_login_is_logged_with_masked_email(client, user, security_log):
    client.post("/users/login/", {"email": "john@example.com", "password": "wrong-password"})

    assert messages_of(security_log, "login") == []
    [message] = messages_of(security_log, "login_failed")
    assert "ident='jo***@example.com'" in message
    assert ("WARNING", message) in security_log()
    assert_no_secrets(security_log, "wrong-password", "john@example.com")


@pytest.mark.django_db
def test_failed_login_for_unknown_email_is_logged_the_same_way(client, security_log):
    client.post("/users/login/", {"email": "stranger@example.com", "password": "whatever-1"})

    [message] = messages_of(security_log, "login_failed")
    assert "ident='st***@example.com'" in message


@pytest.mark.django_db
def test_logout_is_logged(client, user, security_log):
    client.force_login(user)

    client.post("/users/logout/")

    [message] = messages_of(security_log, "logout")
    assert f"user_id={user.pk}" in message


@pytest.mark.django_db
def test_admin_login_attempts_are_logged(client, user, security_log):
    user.is_staff = True
    user.save()

    client.post("/admin/login/", {"username": "john", "password": "wrong-password"})
    client.post("/admin/login/", {"username": "john", "password": PASSWORD})

    [failed] = messages_of(security_log, "login_failed")
    assert "ident='jo***'" in failed
    [ok] = messages_of(security_log, "login")
    assert "backend='ModelBackend'" in ok
    assert "path='/admin/login/'" in ok
    assert_no_secrets(security_log, "wrong-password", PASSWORD)


@pytest.mark.django_db
def test_jwt_token_requests_are_logged(user, security_log):
    api = APIClient()

    assert api.post("/api/token/", {"username": "john", "password": "wrong-password"}).status_code == 401
    ok = api.post("/api/token/", {"username": "john", "password": PASSWORD})

    assert ok.status_code == 200
    assert set(ok.data) == {"access", "refresh"}  # the logging serializer still returns the default pair
    [failed] = messages_of(security_log, "login_failed")
    assert "ident='jo***'" in failed
    [logged_in] = messages_of(security_log, "login")
    assert f"user_id={user.pk}" in logged_in
    assert "backend='jwt'" in logged_in
    assert "path='/api/token/'" in logged_in
    assert_no_secrets(security_log, "wrong-password", PASSWORD, ok.data["access"], ok.data["refresh"])


# == Sign-up, password reset, email change ==


@pytest.mark.django_db
def test_site_signup_is_logged(client, security_log):
    client.post(
        "/users/register/",
        {"username": "newbie", "email": "newbie@example.com", "password1": PASSWORD, "password2": PASSWORD},
    )

    user = User.objects.get(username="newbie")
    [message] = messages_of(security_log, "signup")
    assert f"user_id={user.pk}" in message
    assert "via='site'" in message
    assert_no_secrets(security_log, PASSWORD)


@pytest.mark.django_db
def test_password_reset_request_is_logged_with_the_emailed_accounts(client, user, security_log):
    client.post("/users/password-reset/", {"email": "john@example.com"})
    client.post("/users/password-reset/", {"email": "nobody@example.com"})

    known, unknown = messages_of(security_log, "password_reset_requested")
    assert "ident='jo***@example.com'" in known
    assert f"emailed_user_ids=[{user.pk}]" in known
    assert "ident='no***@example.com'" in unknown
    assert "emailed_user_ids=[]" in unknown
    assert_no_secrets(security_log, "john@example.com", "nobody@example.com")


@pytest.mark.django_db
def test_completed_password_reset_is_logged(client, user, security_log):
    client.post("/users/password-reset/", {"email": "john@example.com"})
    reset_path = re.search(r"/users/password-reset-confirm/[^/\s]+/[^/\s]+/", mail.outbox[-1].body).group(0)
    response = client.get(reset_path, follow=True)  # Django swaps the token into the session
    form_url = response.redirect_chain[-1][0]

    client.post(form_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

    [message] = messages_of(security_log, "password_reset_completed")
    assert f"user_id={user.pk}" in message
    assert "via='site'" in message
    assert_no_secrets(security_log, NEW_PASSWORD)


@pytest.mark.django_db
def test_profile_email_change_is_logged_masked(client, user, security_log):
    client.force_login(user)

    client.post("/users/profile/", {"username": "john", "email": "new.address@example.com"})
    client.post("/users/profile/", {"username": "john", "email": "new.address@example.com"})  # unchanged

    [message] = messages_of(security_log, "email_changed")
    assert f"user_id={user.pk}" in message
    assert "old='jo***@example.com'" in message
    assert "new='ne***@example.com'" in message
    assert_no_secrets(security_log, "john@example.com", "new.address@example.com")


# == Google ==


def google_login(data):
    request = RequestFactory().get("/accounts/google/login/callback/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.user = AnonymousUser()
    request._messages = FallbackStorage(request)
    request.session.save()
    with context.request_context(request):
        provider = get_adapter().get_provider(request, "google")
        sociallogin = provider.sociallogin_from_response(request, data)
        sociallogin.state = {"process": "login"}
        complete_social_login(request, sociallogin)


def google_payload(email, verified=True):
    return {"sub": "google-uid-1", "email": email, "email_verified": verified}


@pytest.mark.django_db
def test_google_link_to_verified_account_is_logged(user, security_log):
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)

    google_login(google_payload("john@example.com"))

    [connected] = messages_of(security_log, "google_connected")
    assert f"user_id={user.pk}" in connected
    [logged_in] = messages_of(security_log, "login")
    assert f"user_id={user.pk}" in logged_in


@pytest.mark.django_db
def test_new_google_user_signup_is_logged(security_log):
    google_login(google_payload("fresh@example.com"))

    user = User.objects.get(email="fresh@example.com")
    [message] = messages_of(security_log, "signup")
    assert f"user_id={user.pk}" in message
    assert "via='google'" in message


@pytest.mark.django_db
@pytest.mark.parametrize(
    "email_verified_locally, google_verified, reason",
    [
        (False, True, "local_email_unverified"),
        (True, False, "google_email_unverified"),
    ],
)
def test_refused_google_login_is_logged(user, security_log, email_verified_locally, google_verified, reason):
    if email_verified_locally:
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)

    google_login(google_payload("john@example.com", verified=google_verified))

    [message] = messages_of(security_log, "google_login_refused")
    assert f"reason='{reason}'" in message
    assert "ident='jo***@example.com'" in message
    assert ("WARNING", message) in security_log()
    assert messages_of(security_log, "login") == []


# == Comment deletion ==


@pytest.fixture
def movie(db):
    return Movies.objects.create(title="Dune", country="US", author="Legendary", actors="", tmdb_id=438631)


@pytest.fixture
def bob(db):
    return User.objects.create_user("bob", password="pass12345")


@pytest.mark.django_db
def test_comment_deletion_is_logged(movie, user, bob, security_log):
    comment = Comment.objects.create(movie=movie, user=user, text="mine")
    as_bob, as_owner = Client(), Client()
    as_bob.force_login(bob)
    as_owner.force_login(user)
    url = reverse("comment-delete", args=[comment.id])

    assert as_bob.post(url).status_code == 403
    assert as_owner.post(url).status_code == 200

    [denied] = messages_of(security_log, "comment_delete_denied")
    assert f"comment_id={comment.id} user_id={bob.pk} owner_id={user.pk}" in denied
    [deleted] = messages_of(security_log, "comment_deleted")
    assert f"comment_id={comment.id} movie_id={movie.pk} user_id={user.pk}" in deleted


@pytest.mark.django_db
def test_api_comment_deletion_is_logged(movie, user, bob, security_log):
    comment = Comment.objects.create(movie=movie, user=user, text="mine")
    api = APIClient()
    url = reverse("api-comment-detail", args=[comment.id])

    api.force_authenticate(bob)
    assert api.delete(url).status_code == 403
    api.force_authenticate(user)
    assert api.delete(url).status_code == 204

    [denied] = messages_of(security_log, "comment_delete_denied")
    assert f"comment_id={comment.id} user_id={bob.pk} owner_id={user.pk}" in denied
    [deleted] = messages_of(security_log, "comment_deleted")
    assert f"comment_id={comment.id} movie_id={movie.pk} user_id={user.pk}" in deleted


# == LOGGING setting ==


def test_unhandled_errors_are_mailed_to_admins_and_security_logs_at_info():
    assert any(isinstance(h, AdminEmailHandler) for h in logging.getLogger("django.request").handlers)
    assert logging.getLogger("security").getEffectiveLevel() == logging.INFO
