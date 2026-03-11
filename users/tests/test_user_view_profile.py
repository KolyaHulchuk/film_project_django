import pytest
from users.views import UserRegisterForm, ProfileUpdateForm, UserUpdateForm
from django.contrib.auth.models import User

@pytest.mark.django_db
def test_profile(client):

    user = User.objects.create_user(username="Kolya", password="Password_123")

    #  Let's log in, because only logged-in users can access their profiles.
    client.login(username="Kolya", password="Kolya6_333")


    response = client.post("/users/profile/", {"username": "Mac_Dub",
                                              "email": "mac@gmail.com",
                                              "image": "name.png"
                                              })
    

    user.refresh_from_db() #  оновлює дані user з бази

    assert user.email == "mack@gmail.com"
    assert user.username == "Mac_Dub"

    assert response.status_code == 200
    assert response.context["title"] == "Profile"



@pytest.mark.django_db
def test_profile_without_login(client):

    User.objects.create_user(username="Kolya", password="Password_123")



    response = client.post("/users/profile/", {"username": "Kolya",
                                              "email": "mac@gmail.com",
                                              "image": "name.png"
                                              })

    assert response.status_code == 302

