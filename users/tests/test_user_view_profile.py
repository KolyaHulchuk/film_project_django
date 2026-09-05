import pytest
from django.contrib.auth.models import User

from users.views import ProfileUpdateForm, UserRegisterForm, UserUpdateForm


@pytest.mark.django_db
def test_profile(client):

    user = User.objects.create_user(username="Kolya", password="Password_123")

    #  Let's log in, because only logged-in users can access their profiles.
    client.login(username="Kolya", password="Password_123")

    response = client.post("/users/profile/", {"username": "Mac_Dub", "email": "mac@gmail.com", "image": "name.png"})

    user.refresh_from_db()  # pick up the changes saved by the view's POST handler

    assert user.email == "mack@gmail.com"
    assert user.username == "Mac_Dub"

    assert response.status_code == 200
    assert response.context["title"] == "Profile"


@pytest.mark.django_db
def test_profile_without_login(client):

    User.objects.create_user(username="Kolya", password="Password_123")

    response = client.post("/users/profile/", {"username": "Kolya", "email": "mac@gmail.com", "image": "name.png"})

    assert response.status_code == 302
