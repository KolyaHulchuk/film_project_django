import pytest
from users.views import UserRegisterForm
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_register(client, mocker):

    response = client.post("/users/register/", {"username": "Kolya",
                                                "email": "blabla@gmail.com",
                                                "password1": "Password_123",
                                                "password2": "Password_123"
                                                })


    assert response.status_code == 302
    assert User.objects.filter(username="Kolya").exists() # Was there a user with that name


@pytest.mark.django_db
def test_register_invalid(client):
    
    response = client.post("/users/register/", {"username": "Kolya",
                                                "email": "dub@gamil.com",
                                                "password1": "Kolya6",
                                                "password2": "Kolya6"
                                                })

    assert response.status_code == 200
    assert User.objects.count() == 0

@pytest.mark.django_db
def test_register_get(client):
    
    response = client.get("/users/register/")
    

    assert response.status_code == 200
    assert response.context["title"] == "Register"
    assert "form" in response.context