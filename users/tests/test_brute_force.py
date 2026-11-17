"""Brute-force protection: the django-axes lockout (users/lockout.py) on every login entry point,
the client IP it is keyed on (users/client_ip.py) and the password reset / sign-up rate limits
(users/throttling.py). The cache is locmem (conftest), so every test starts with clean counters."""

import logging
import re

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, RequestFactory
from rest_framework.test import APIClient

from movies.throttling import AIRecommendationAnonThrottle
from users.client_ip import client_ip

PASSWORD = "Password_123"
WRONG = "wrong-password"
IP = "203.0.113.5"
OTHER_IP = "198.51.100.7"
LIMIT = 5  # AXES_FAILURE_LIMIT


@pytest.fixture
def user(db):
    return User.objects.create_user("john", email="john@example.com", password=PASSWORD)


@pytest.fixture
def bob(db):
    return User.objects.create_user("bob", email="bob@example.com", password=PASSWORD)


def site_login(client, email, password, ip=IP, **extra):
    return client.post("/users/login/", {"email": email, "password": password}, HTTP_CF_CONNECTING_IP=ip, **extra)


def logged_in(client):
    return "_auth_user_id" in client.session


def template_names(response):
    return [t.name for t in response.templates]


# == Site login (/users/login/) ==


@pytest.mark.django_db
def test_fifth_wrong_password_locks_the_site_login(client, user):
    for _ in range(LIMIT - 1):
        assert site_login(client, "john@example.com", WRONG).status_code == 200  # the form with an error

    locked = site_login(client, "john@example.com", WRONG)

    assert locked.status_code == 429
    assert "users/lockout.html" in template_names(locked)
    assert locked["Retry-After"] == "900"
    assert b"Try again in 15 minutes" in locked.content
    # Even the right password is refused while locked out.
    assert site_login(client, "john@example.com", PASSWORD).status_code == 429
    assert not logged_in(client)


@pytest.mark.django_db
def test_case_variants_of_the_email_share_one_counter(client, user):
    for email in ["john@example.com", "John@Example.com", "JOHN@EXAMPLE.COM", " john@example.com "]:
        site_login(client, email, WRONG)

    assert site_login(client, "jOhN@example.com", WRONG).status_code == 429


@pytest.mark.django_db
def test_successful_login_resets_the_counter(client, user):
    for _ in range(LIMIT - 1):
        site_login(client, "john@example.com", WRONG)
    assert site_login(client, "john@example.com", PASSWORD).status_code == 302
    client.post("/users/logout/")

    for _ in range(LIMIT - 1):
        assert site_login(client, "john@example.com", WRONG).status_code == 200
    assert site_login(client, "john@example.com", PASSWORD).status_code == 302


@pytest.mark.django_db
def test_lockout_only_applies_to_that_email_from_that_ip(user, bob):
    attacker = Client()
    for _ in range(LIMIT):
        site_login(attacker, "john@example.com", WRONG)
    assert site_login(attacker, "john@example.com", PASSWORD).status_code == 429

    # The owner, from their own network, isn't locked out of their account...
    owner = Client()
    assert site_login(owner, "john@example.com", PASSWORD, ip=OTHER_IP).status_code == 302
    # ...and other accounts still work from the attacker's IP.
    assert site_login(attacker, "bob@example.com", PASSWORD).status_code == 302


@pytest.mark.django_db
def test_spoofed_forwarded_for_does_not_reset_the_counter(client, user):
    for n in range(LIMIT - 1):
        site_login(client, "john@example.com", WRONG, HTTP_X_FORWARDED_FOR=f"10.0.0.{n}")

    assert site_login(client, "john@example.com", WRONG, HTTP_X_FORWARDED_FOR="10.9.9.9").status_code == 429


@pytest.mark.django_db
def test_unknown_email_is_locked_out_the_same_way(client):
    for _ in range(LIMIT - 1):
        assert site_login(client, "nobody@example.com", WRONG).status_code == 200

    assert site_login(client, "nobody@example.com", WRONG).status_code == 429  # no account enumeration


@pytest.mark.django_db
def test_fetch_requests_get_a_json_lockout(client, user):
    for _ in range(LIMIT - 1):
        site_login(client, "john@example.com", WRONG)

    locked = site_login(client, "john@example.com", WRONG, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    assert locked.status_code == 429
    assert locked.json() == {"detail": "Too many failed login attempts. Try again in 15 minutes."}


# == /admin/, allauth, /api/token/ ==


@pytest.mark.django_db
def test_admin_login_is_locked_out(client, user):
    user.is_staff = True
    user.save()

    def admin_login(password):
        return client.post("/admin/login/", {"username": "john", "password": password}, HTTP_CF_CONNECTING_IP=IP)

    for _ in range(LIMIT - 1):
        assert admin_login(WRONG).status_code == 200
    assert admin_login(WRONG).status_code == 429
    assert admin_login(PASSWORD).status_code == 429
    assert not logged_in(client)


@pytest.mark.django_db
def test_allauth_login_page_is_locked_out(client, user):
    def allauth_login(password):
        return client.post(
            "/accounts/login/", {"login": "john@example.com", "password": password}, HTTP_CF_CONNECTING_IP=IP
        )

    for _ in range(LIMIT - 1):
        assert allauth_login(WRONG).status_code == 200
    assert allauth_login(WRONG).status_code == 429
    # allauth's own limit (5 failures per email in 5 min) answers first now, with its form error
    # instead of our page: the right password is refused either way.
    refused = allauth_login(PASSWORD)
    assert b"Too many failed login attempts" in refused.content
    assert not logged_in(client)


@pytest.mark.django_db
def test_allauth_and_site_logins_share_the_counter(client, user):
    for _ in range(LIMIT - 1):
        client.post("/accounts/login/", {"login": "john@example.com", "password": WRONG}, HTTP_CF_CONNECTING_IP=IP)

    assert site_login(client, "john@example.com", WRONG).status_code == 429


def jwt(api, password, ip=IP):
    return api.post("/api/token/", {"username": "john", "password": password}, HTTP_CF_CONNECTING_IP=ip)


@pytest.mark.django_db
def test_jwt_token_endpoint_is_locked_out_with_429(user):
    api = APIClient()
    for _ in range(LIMIT - 1):
        assert jwt(api, WRONG).status_code == 401

    locked = jwt(api, WRONG)

    assert locked.status_code == 429
    assert locked["Retry-After"] == "900"
    assert locked.json() == {"detail": "Too many failed login attempts. Try again in 15 minutes."}
    assert jwt(api, PASSWORD).status_code == 429
    assert jwt(api, PASSWORD, ip=OTHER_IP).status_code == 200


@pytest.mark.django_db
def test_jwt_token_success_resets_the_counter(user):
    api = APIClient()
    for _ in range(LIMIT - 1):
        jwt(api, WRONG)
    assert jwt(api, PASSWORD).status_code == 200

    for _ in range(LIMIT - 1):
        assert jwt(api, WRONG).status_code == 401
    assert jwt(api, PASSWORD).status_code == 200


# == Security log, unlocking ==


@pytest.mark.django_db
def test_lockout_is_in_the_security_log_with_the_client_ip(client, user, caplog):
    caplog.set_level(logging.INFO, logger="security")
    for _ in range(LIMIT):
        site_login(client, "john@example.com", WRONG)

    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("login_locked_out")]
    assert line == f"login_locked_out ident='jo***@example.com' ip='{IP}' path='/users/login/'"
    assert all(r.levelname == "WARNING" for r in caplog.records if r.getMessage().startswith("login_locked_out"))
    assert not [r for r in caplog.records if r.name.startswith("axes") and r.levelno < logging.ERROR]


@pytest.mark.django_db
def test_completed_password_reset_lifts_the_lockout(client, user):
    for _ in range(LIMIT):
        site_login(client, "john@example.com", WRONG)
    assert site_login(client, "john@example.com", PASSWORD).status_code == 429

    client.post("/users/password-reset/", {"email": "john@example.com"}, HTTP_CF_CONNECTING_IP=IP)
    reset_path = re.search(r"/users/password-reset-confirm/[^/\s]+/[^/\s]+/", mail.outbox[-1].body).group(0)
    form_url = client.get(reset_path, follow=True).redirect_chain[-1][0]
    new_password = "Another_Pass_456"
    client.post(form_url, {"new_password1": new_password, "new_password2": new_password}, HTTP_CF_CONNECTING_IP=IP)

    assert site_login(client, "john@example.com", new_password).status_code == 302


# == Client IP ==


@pytest.mark.parametrize(
    "meta, expected",
    [
        ({"REMOTE_ADDR": "10.0.0.1", "HTTP_CF_CONNECTING_IP": "203.0.113.5"}, "203.0.113.5"),
        ({"REMOTE_ADDR": "10.0.0.1", "HTTP_CF_CONNECTING_IP": " 2001:DB8::1 "}, "2001:db8::1"),
        ({"REMOTE_ADDR": "10.0.0.1", "HTTP_CF_CONNECTING_IP": "not-an-ip"}, "10.0.0.1"),
        ({"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "1.2.3.4"}, "10.0.0.1"),  # XFF is never trusted
        ({}, None),
    ],
)
def test_client_ip(meta, expected):
    request = RequestFactory().get("/")
    request.META = meta

    assert client_ip(request) == expected


def test_client_ip_header_can_be_turned_off(settings):
    settings.CLIENT_IP_HEADER = ""
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.5")

    assert client_ip(request) == "10.0.0.1"


def test_anonymous_throttles_count_by_client_ip_not_forwarded_for():
    factory = RequestFactory()
    first = factory.get("/", HTTP_CF_CONNECTING_IP=IP, HTTP_X_FORWARDED_FOR="1.1.1.1")
    second = factory.get("/", HTTP_CF_CONNECTING_IP=IP, HTTP_X_FORWARDED_FOR="2.2.2.2")
    throttle = AIRecommendationAnonThrottle()

    assert throttle.get_ident(first) == throttle.get_ident(second) == IP


# == Password reset and sign-up rate limits ==


def reset_request(client, email, ip=IP):
    return client.post("/users/password-reset/", {"email": email}, HTTP_CF_CONNECTING_IP=ip)


@pytest.mark.django_db
def test_password_reset_is_limited_to_3_per_address_per_hour(client, user, caplog):
    caplog.set_level(logging.INFO, logger="security")
    for n in range(3):
        assert reset_request(client, "john@example.com", ip=f"203.0.113.{n + 10}").status_code == 302

    refused = reset_request(client, "John@Example.com", ip="203.0.113.99")

    assert refused.status_code == 429
    assert b"Too many password reset requests. Try again in 60 min." in refused.content
    assert len(mail.outbox) == 3  # the refused request sent nothing
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("password_reset_throttled")]
    assert "ident='Jo***@Example.com'" in line


@pytest.mark.django_db
def test_password_reset_is_limited_to_5_per_ip_per_hour(client):
    for n in range(5):
        assert reset_request(client, f"user{n}@example.com").status_code == 302

    assert reset_request(client, "user9@example.com").status_code == 429
    assert reset_request(client, "user9@example.com", ip=OTHER_IP).status_code == 302


@pytest.mark.django_db
def test_unknown_addresses_hit_the_same_reset_limit(client):
    for _ in range(3):
        reset_request(client, "nobody@example.com")

    assert reset_request(client, "nobody@example.com").status_code == 429  # same answer as for real accounts


def signup(client, username, ip=IP):
    data = {"username": username, "email": f"{username}@example.com", "password1": PASSWORD, "password2": PASSWORD}
    return client.post("/users/register/", data, HTTP_CF_CONNECTING_IP=ip)


@pytest.mark.django_db
def test_signup_is_limited_to_10_submissions_per_ip_per_hour(client):
    for _ in range(9):
        assert client.post("/users/register/", {}, HTTP_CF_CONNECTING_IP=IP).status_code == 200  # invalid ones count
    assert signup(client, "tenth").status_code == 302

    refused = signup(client, "eleventh")

    assert refused.status_code == 429
    assert b"Too many sign-up attempts from your network. Try again in 60 min." in refused.content
    assert not User.objects.filter(username="eleventh").exists()
    assert signup(client, "eleventh", ip=OTHER_IP).status_code == 302
