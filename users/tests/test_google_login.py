"""Google login linking. The Google response is mocked: we feed the id_token payload
straight into allauth's own flow (sociallogin_from_response -> complete_social_login)."""

import pytest
from allauth.account.models import EmailAddress
from allauth.core import context
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import SESSION_KEY
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.test import RequestFactory

from users.adapters import SOCIAL_EXISTING_UNVERIFIED_MESSAGE, SOCIAL_NO_EMAIL_MESSAGE, SOCIAL_UNVERIFIED_MESSAGE

PASSWORD = "Password_123"


def google_payload(email="kolya@example.com", verified=True, uid="google-uid-1"):
    data = {"sub": uid, "given_name": "Коля", "family_name": "Х"}
    if email is not None:
        data["email"] = email
        data["email_verified"] = verified
    return data


def google_login(data, user=None, process="login"):
    request = RequestFactory().get("/accounts/google/login/callback/")
    SessionMiddleware(lambda r: None).process_request(request)
    request.user = AnonymousUser()
    request._messages = FallbackStorage(request)
    if user is not None:
        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.save()
    with context.request_context(request):
        provider = get_adapter().get_provider(request, "google")
        sociallogin = provider.sociallogin_from_response(request, data)
        sociallogin.state = {"process": process}
        response = complete_social_login(request, sociallogin)
    return request, response


def logged_in_id(request):
    value = request.session.get(SESSION_KEY)
    return int(value) if value else None


def message_texts(request):
    return [str(m) for m in get_messages(request)]


@pytest.fixture
def local_user(db):
    """Registered with email + password, email NOT verified yet."""
    return User.objects.create_user("kolya", email="kolya@example.com", password=PASSWORD)


@pytest.fixture
def verified_user(local_user):
    EmailAddress.objects.create(user=local_user, email=local_user.email, verified=True, primary=True)
    return local_user


# --- existing account with a verified email: link, keep the password ---


@pytest.mark.django_db
def test_verified_email_links_to_existing_account(verified_user):
    request, response = google_login(google_payload())

    assert response.status_code == 302
    assert User.objects.count() == 1
    assert logged_in_id(request) == verified_user.pk
    assert SocialAccount.objects.get(provider="google", uid="google-uid-1").user_id == verified_user.pk


@pytest.mark.django_db
@pytest.mark.parametrize("google_email", ["KOLYA@Example.com", "  kolya@example.com  ", " Kolya@EXAMPLE.com\t"])
def test_linking_ignores_case_and_whitespace(verified_user, google_email):
    request, _ = google_login(google_payload(email=google_email))

    assert User.objects.count() == 1
    assert logged_in_id(request) == verified_user.pk
    assert SocialAccount.objects.get(uid="google-uid-1").user_id == verified_user.pk


@pytest.mark.django_db
def test_linking_keeps_password_login(client, verified_user):
    google_login(google_payload())

    verified_user.refresh_from_db()
    assert verified_user.check_password(PASSWORD)
    response = client.post("/users/login/", {"email": "kolya@example.com", "password": PASSWORD})
    assert response.status_code == 302
    assert client.session[SESSION_KEY] == str(verified_user.pk)


@pytest.mark.django_db
def test_linking_does_not_touch_permissions(verified_user):
    verified_user.is_staff = True
    verified_user.is_superuser = True
    verified_user.save()

    google_login(google_payload())

    verified_user.refresh_from_db()
    assert verified_user.is_staff
    assert verified_user.is_superuser


@pytest.mark.django_db
def test_repeat_google_login_after_linking(verified_user):
    google_login(google_payload())
    request, response = google_login(google_payload())

    assert response.status_code == 302
    assert User.objects.count() == 1
    assert SocialAccount.objects.count() == 1
    assert logged_in_id(request) == verified_user.pk


# --- existing account with an UNverified email: no auto-link ---


@pytest.mark.django_db
def test_unverified_local_email_is_not_linked(local_user):
    request, response = google_login(google_payload())

    assert response.status_code == 302
    assert response.url == "/users/login/"
    assert User.objects.count() == 1
    assert not SocialAccount.objects.exists()
    assert logged_in_id(request) is None
    assert SOCIAL_EXISTING_UNVERIFIED_MESSAGE in message_texts(request)
    local_user.refresh_from_db()
    assert local_user.check_password(PASSWORD)


@pytest.mark.django_db
def test_unverified_local_email_gets_a_verification_link(local_user):
    google_login(google_payload())

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["kolya@example.com"]
    assert "/accounts/confirm-email/" in mail.outbox[0].body
    assert not EmailAddress.objects.get(user=local_user).verified


@pytest.mark.django_db
def test_connect_from_profile_links_unverified_account(local_user):
    """A logged-in owner can link Google explicitly, even before verifying the email."""
    google_login(google_payload(), user=local_user, process="connect")

    assert SocialAccount.objects.get(uid="google-uid-1").user_id == local_user.pk
    assert User.objects.count() == 1
    local_user.refresh_from_db()
    assert local_user.check_password(PASSWORD)


# --- new users ---


@pytest.mark.django_db
def test_new_email_creates_google_only_account():
    request, _ = google_login(google_payload(email="  New.Person@Gmail.com "))

    user = User.objects.get()
    assert user.email == "new.person@gmail.com"
    assert not user.has_usable_password()
    assert logged_in_id(request) == user.pk
    assert SocialAccount.objects.get(uid="google-uid-1").user_id == user.pk
    assert EmailAddress.objects.get(user=user).verified


@pytest.mark.django_db
def test_repeat_google_login_uses_sub_not_email():
    google_login(google_payload(email="new@gmail.com"))
    # Same Google account (same sub), email changed on Google's side.
    request, _ = google_login(google_payload(email="renamed@gmail.com"))

    assert User.objects.count() == 1
    assert logged_in_id(request) == User.objects.get().pk


# --- what Google sends is not good enough ---


@pytest.mark.django_db
@pytest.mark.parametrize("existing", [True, False])
def test_unverified_google_email_is_rejected(db, existing):
    if existing:
        User.objects.create_user("kolya", email="kolya@example.com", password=PASSWORD)
    users_before = User.objects.count()

    request, response = google_login(google_payload(verified=False))

    assert response.url == "/users/login/"
    assert User.objects.count() == users_before
    assert not SocialAccount.objects.exists()
    assert logged_in_id(request) is None
    assert SOCIAL_UNVERIFIED_MESSAGE in message_texts(request)


@pytest.mark.django_db
@pytest.mark.parametrize("email", [None, "", "   ", "not-an-email"])
def test_missing_email_creates_no_account(db, email):
    request, response = google_login(google_payload(email=email))

    assert response.url == "/users/login/"
    assert not User.objects.exists()
    assert not SocialAccount.objects.exists()
    assert SOCIAL_NO_EMAIL_MESSAGE in message_texts(request)
