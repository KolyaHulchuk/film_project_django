"""Email + password login, registration with email verification, password reset, profile email changes."""

import re

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.core import mail
from django.db import IntegrityError, transaction

from users.forms import INVALID_LOGIN_MESSAGE

PASSWORD = "Password_123"
NEW_PASSWORD = "Another_Pass_456"


def login(client, email, password=PASSWORD):
    return client.post("/users/login/", {"email": email, "password": password})


def link_from(message, pattern):
    return re.search(pattern, message.body).group(0)


def confirm_url(message):
    return link_from(message, r"/accounts/confirm-email/[^/\s]+/")


def reset_url(message):
    return link_from(message, r"/users/password-reset-confirm/[^/\s]+/[^/\s]+/")


def register(client, username="kolya", email="kolya@example.com"):
    return client.post(
        "/users/register/",
        {"username": username, "email": email, "password1": PASSWORD, "password2": PASSWORD},
    )


@pytest.fixture
def user(db):
    return User.objects.create_user("kolya", email="kolya@example.com", password=PASSWORD)


@pytest.fixture
def google_only_user(db):
    u = User.objects.create_user("googler", email="googler@gmail.com")
    u.set_unusable_password()
    u.save()
    EmailAddress.objects.create(user=u, email=u.email, verified=True, primary=True)
    return u


# --- login ---


@pytest.mark.django_db
@pytest.mark.parametrize("email", ["kolya@example.com", "  KOLYA@Example.com "])
def test_login_with_email_and_password(client, user, email):
    response = login(client, email)
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)


@pytest.mark.django_db
@pytest.mark.parametrize(("email", "password"), [("kolya@example.com", "wrong"), ("nobody@example.com", PASSWORD)])
def test_login_failure_shows_same_error(client, user, email, password):
    response = login(client, email, password)
    assert response.status_code == 200
    assert SESSION_KEY not in client.session
    assert INVALID_LOGIN_MESSAGE in response.content.decode()


@pytest.mark.django_db
def test_login_by_username_is_not_accepted_on_site_form(client, user):
    response = client.post("/users/login/", {"email": "kolya", "password": PASSWORD})
    assert SESSION_KEY not in client.session
    assert response.status_code == 200


@pytest.mark.django_db
def test_inactive_user_cannot_log_in(client, user):
    user.is_active = False
    user.save()
    login(client, "kolya@example.com")
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_google_only_user_cannot_log_in_with_password(client, google_only_user):
    login(client, "googler@gmail.com", "")
    login(client, "googler@gmail.com", "anything")
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_admin_login_by_username_still_works(client, user):
    user.is_staff = True
    user.save()
    response = client.post("/admin/login/?next=/admin/", {"username": "kolya", "password": PASSWORD})
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(user.pk)


# --- registration + email verification ---


@pytest.mark.django_db
def test_register_sends_verification_and_starts_unverified(client):
    response = register(client)

    assert response.status_code == 302
    user = User.objects.get(username="kolya")
    assert user.has_usable_password()
    address = EmailAddress.objects.get(user=user)
    assert address.email == "kolya@example.com"
    assert not address.verified
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["kolya@example.com"]


@pytest.mark.django_db
def test_password_login_does_not_verify_email(client):
    register(client)
    login(client, "kolya@example.com")

    assert SESSION_KEY in client.session
    assert not EmailAddress.objects.get(email="kolya@example.com").verified


@pytest.mark.django_db
def test_confirmation_link_verifies_email(client):
    register(client)
    url = confirm_url(mail.outbox[0])

    client.post(url)

    assert EmailAddress.objects.get(email="kolya@example.com").verified


@pytest.mark.django_db
def test_register_with_taken_email_still_rejected(client, user):
    response = register(client, username="other", email=" KOLYA@example.com")
    assert response.status_code == 200
    assert not User.objects.filter(username="other").exists()
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_allauth_signup_with_taken_email_still_rejected(client, user):
    response = client.post(
        "/accounts/signup/",
        {"username": "other", "email": "Kolya@Example.com ", "password1": PASSWORD, "password2": PASSWORD},
    )
    assert response.status_code == 200
    assert not User.objects.filter(username="other").exists()


@pytest.mark.django_db
def test_unique_lower_email_index_still_enforced(user):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(username="other", email="KOLYA@example.com")])


# --- password reset ---


@pytest.mark.django_db
def test_password_reset_email_for_user_with_password(client, user):
    response = client.post("/users/password-reset/", {"email": " Kolya@Example.com"})

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["kolya@example.com"]
    assert "signing in with Google" not in mail.outbox[0].body


@pytest.mark.django_db
def test_password_reset_email_for_google_only_user_offers_to_set_password(client, google_only_user):
    response = client.post("/users/password-reset/", {"email": "googler@gmail.com"})

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert "signing in with Google" in mail.outbox[0].body


@pytest.mark.django_db
def test_password_reset_unknown_email_looks_the_same(client):
    response = client.post("/users/password-reset/", {"email": "nobody@example.com"})

    assert response.status_code == 302
    assert response.url == "/users/password-reset/done/"
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_password_reset_skips_inactive_user(client, user):
    user.is_active = False
    user.save()
    client.post("/users/password-reset/", {"email": "kolya@example.com"})
    assert len(mail.outbox) == 0


def complete_reset(client, email):
    client.post("/users/password-reset/", {"email": email})
    response = client.get(reset_url(mail.outbox[-1]), follow=True)  # Django swaps the token into the session
    form_url = response.redirect_chain[-1][0]
    return client.post(form_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})


@pytest.mark.django_db
def test_password_reset_marks_email_verified(client, user):
    response = complete_reset(client, "kolya@example.com")

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert EmailAddress.objects.get(user=user, email="kolya@example.com").verified


@pytest.mark.django_db
def test_google_only_user_can_set_password_and_log_in(client, google_only_user):
    complete_reset(client, "googler@gmail.com")

    response = login(client, "googler@gmail.com", NEW_PASSWORD)
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(google_only_user.pk)


# --- profile ---


def update_profile(client, email, username="kolya"):
    return client.post("/users/profile/", {"username": username, "email": email})


@pytest.mark.django_db
def test_profile_email_change_requires_new_verification(client, user):
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    client.force_login(user)

    update_profile(client, "new@example.com")

    user.refresh_from_db()
    assert user.email == "new@example.com"
    assert list(EmailAddress.objects.filter(user=user).values_list("email", "verified")) == [("new@example.com", False)]
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["new@example.com"]


@pytest.mark.django_db
def test_profile_save_without_email_change_keeps_verification(client, user):
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    client.force_login(user)

    update_profile(client, "kolya@example.com", username="kolya2")

    assert EmailAddress.objects.get(user=user).verified
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_profile_shows_verification_and_google_status(client, user):
    client.force_login(user)
    content = client.get("/users/profile/").content.decode()
    assert "Not verified" in content
    assert "Resend verification email" in content
    assert "process=connect" in content


@pytest.mark.django_db
def test_resend_verification(client, user):
    client.force_login(user)

    response = client.post("/users/profile/resend-verification/")

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    client.post(confirm_url(mail.outbox[0]))
    assert EmailAddress.objects.get(user=user).verified


@pytest.mark.django_db
def test_resend_verification_requires_post_and_login(client, user):
    assert client.post("/users/profile/resend-verification/").status_code == 302  # to login
    client.force_login(user)
    assert client.get("/users/profile/resend-verification/").status_code == 405
    assert len(mail.outbox) == 0


# --- how our emails look ---


@pytest.mark.django_db
def test_emails_are_branded_as_the_site(client, user):
    client.post("/users/password-reset/", {"email": "kolya@example.com"})
    register(client, username="other", email="other@example.com")

    assert len(mail.outbox) == 2
    for message in mail.outbox:
        assert message.from_email.startswith("Movies.hub <")
        assert "Movies.hub" in message.subject + message.body
        assert "local" not in (message.subject + message.body).lower().replace("localhost", "")
