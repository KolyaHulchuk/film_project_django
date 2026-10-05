import threading

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction

from movies.models import Comment, Movies
from users.models import Watchlist

PASSWORD = "Password_123"


def register(client, username, email):
    return client.post(
        "/users/register/",
        {"username": username, "email": email, "password1": PASSWORD, "password2": PASSWORD},
    )


@pytest.mark.django_db
def test_register_new_email_ok(client):
    response = register(client, "a", "a@example.com")
    assert response.status_code == 302
    assert User.objects.get(username="a").email == "a@example.com"


@pytest.mark.django_db
def test_register_existing_email_rejected(client):
    User.objects.create_user("first", "a@example.com", PASSWORD)
    response = register(client, "second", "a@example.com")
    assert response.status_code == 200
    assert "email" in response.context["form"].errors
    assert User.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("email", ["A@Example.COM", "  a@example.com  ", " A@EXAMPLE.com"])
def test_register_case_and_whitespace_rejected(client, email):
    User.objects.create_user("first", "a@example.com", PASSWORD)
    response = register(client, "second", email)
    assert response.status_code == 200
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_register_stores_normalized_email(client):
    register(client, "a", "  Mixed@Example.COM ")
    assert User.objects.get(username="a").email == "mixed@example.com"


@pytest.mark.django_db
def test_profile_change_to_taken_email_rejected(client):
    User.objects.create_user("first", "taken@example.com", PASSWORD)
    me = User.objects.create_user("me", "me@example.com", PASSWORD)
    client.force_login(me)
    response = client.post("/users/profile/", {"username": "me", "email": "TAKEN@example.com"})
    assert response.status_code == 200
    assert "email" in response.context["u_form"].errors
    me.refresh_from_db()
    assert me.email == "me@example.com"


@pytest.mark.django_db
def test_profile_keep_own_email_ok(client):
    me = User.objects.create_user("me", "me@example.com", PASSWORD)
    client.force_login(me)
    client.post("/users/profile/", {"username": "me", "email": "Me@example.com"})
    me.refresh_from_db()
    assert me.email == "me@example.com"


@pytest.mark.django_db
def test_db_index_blocks_duplicate_even_bypassing_forms():
    User.objects.create_user("first", "a@example.com", PASSWORD)
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(username="second", email="A@example.com")])  # bulk_create skips signals


@pytest.mark.django_db
def test_empty_emails_do_not_conflict():
    User.objects.create_user("a", "", PASSWORD)
    User.objects.create_user("b", "", PASSWORD)
    assert User.objects.filter(email="").count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_registrations_create_one_account(client):
    from django.test import Client

    results = []
    barrier = threading.Barrier(2)

    def worker(n):
        try:
            c = Client()
            barrier.wait()
            results.append(register(c, f"user{n}", "race@example.com").status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [200, 302]  # loser gets a form error, never a 500
    assert User.objects.filter(email="race@example.com").count() == 1


@pytest.fixture
def duplicates():
    """Duplicates can't exist while the index does, so drop it for the data-migration scenario."""
    with connection.cursor() as cur:
        cur.execute("DROP INDEX auth_user_email_lower_uniq")
    primary = User.objects.create_user("primary", "dup@example.com", PASSWORD)
    dup = User.objects.create_user("dup", "x@example.com", PASSWORD)
    User.objects.filter(pk=dup.pk).update(email="DUP@example.com ")
    return primary, dup


@pytest.mark.django_db(transaction=True)
def test_dedup_dry_run_changes_nothing(duplicates):
    primary, dup = duplicates
    call_command("find_duplicate_emails")
    dup.refresh_from_db()
    assert dup.is_active and dup.email == "DUP@example.com "
    # restore index for following tests
    User.objects.filter(pk=dup.pk).delete()
    with connection.cursor() as cur:
        cur.execute("CREATE UNIQUE INDEX auth_user_email_lower_uniq ON auth_user (LOWER(email)) WHERE email <> ''")


@pytest.mark.django_db(transaction=True)
def test_dedup_apply_moves_data_and_deactivates(duplicates):
    primary, dup = duplicates
    movie = Movies.objects.create(tmdb_id=1, title="M")
    Watchlist.objects.create(user=dup, movie=movie)
    Comment.objects.create(user=dup, movie=movie, text="hi")

    call_command("find_duplicate_emails", "--apply", "--keep", str(primary.id))

    dup.refresh_from_db()
    assert not dup.is_active and dup.email == ""
    assert Watchlist.objects.filter(user=primary).count() == 1
    assert Comment.objects.filter(user=primary).count() == 1
    assert User.objects.filter(is_active=True, email__iexact="dup@example.com").count() == 1

    with connection.cursor() as cur:
        cur.execute("CREATE UNIQUE INDEX auth_user_email_lower_uniq ON auth_user (LOWER(email)) WHERE email <> ''")
