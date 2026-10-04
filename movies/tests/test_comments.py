from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from movies.models import Comment, CommentVote, Movies
from movies.throttling import CommentCreateThrottle, CommentVoteThrottle


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    # Throttles and sessions live in the default cache (Redis in dev/prod);
    # keep tests independent of a running Redis and of each other's hit counts.
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@pytest.fixture
def movie(db):
    return Movies.objects.create(title="Dune", country="US", author="Legendary", actors="", tmdb_id=438631)


@pytest.fixture
def other_movie(db):
    return Movies.objects.create(title="Arrival", country="US", author="Paramount", actors="", tmdb_id=329865)


@pytest.fixture
def alice(db):
    return User.objects.create_user("alice", password="pass12345")


@pytest.fixture
def bob(db):
    return User.objects.create_user("bob", password="pass12345")


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def create_url(movie):
    return reverse("comment-create", args=[movie.id])


def vote(client, comment, value):
    return client.post(reverse("comment-vote", args=[comment.id]), {"value": value})


# == Access for anonymous users ==


@pytest.mark.django_db
def test_detail_page_shows_login_prompt_and_locked_votes_to_anonymous(client, mocker, movie, alice):
    mocker.patch("movies.views.TMDBClient").return_value.get_credit.return_value = {}
    comment = Comment.objects.create(movie=movie, user=alice, text="Great film")

    response = client.get(reverse("movie-detail", args=[movie.tmdb_id, movie.media_type]))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Log in</a> to leave a comment" in html
    assert 'name="text"' not in html
    assert "Great film" in html
    assert "Log in to vote" in html
    assert reverse("comment-vote", args=[comment.id]) not in html  # no hx-post on locked vote buttons


@pytest.mark.django_db
def test_anonymous_cannot_create_delete_or_vote(client, movie, alice):
    comment = Comment.objects.create(movie=movie, user=alice, text="Mine")

    responses = [
        client.post(create_url(movie), {"text": "hi"}),
        client.post(reverse("comment-delete", args=[comment.id])),
        vote(client, comment, 1),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401]
    assert all(r["HX-Retarget"] == "#cm-flash" for r in responses)
    assert Comment.objects.count() == 1
    assert not CommentVote.objects.exists()


@pytest.mark.django_db
def test_comment_endpoints_enforce_csrf(movie, alice):
    client = Client(enforce_csrf_checks=True)
    client.force_login(alice)

    response = client.post(create_url(movie), {"text": "no token"})

    assert response.status_code == 403
    assert not Comment.objects.exists()


# == Creating ==


@pytest.mark.django_db
def test_create_strips_whitespace_and_renders_feed(movie, alice):
    response = client_for(alice).post(create_url(movie), {"text": "   Loved it   "})

    assert response.status_code == 200
    comment = Comment.objects.get()
    assert (comment.user, comment.movie, comment.text) == (alice, movie, "Loved it")
    html = response.content.decode()
    assert 'id="cm-feed" class="cm-feed" hx-swap-oob="true"' in html
    assert 'name="text"' in html  # the form is still there, ready for another comment


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["", "     \n\t  ", "x" * 1001])
def test_create_rejects_blank_and_too_long_text(movie, alice, text):
    response = client_for(alice).post(create_url(movie), {"text": text})

    assert response.status_code == 422
    assert "cm-error" in response.content.decode()
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_create_accepts_exactly_max_length(movie, alice):
    response = client_for(alice).post(create_url(movie), {"text": "x" * 1000})

    assert response.status_code == 200
    assert len(Comment.objects.get().text) == 1000


@pytest.mark.django_db
def test_user_can_leave_several_comments_under_one_movie(movie, alice):
    client = client_for(alice)

    first = client.post(create_url(movie), {"text": "first"})
    second = client.post(create_url(movie), {"text": "second"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert list(Comment.objects.filter(movie=movie, user=alice).values_list("text", flat=True)) == ["first", "second"]


@pytest.mark.django_db
def test_comment_text_is_html_escaped(movie, alice):
    client_for(alice).post(create_url(movie), {"text": "<script>alert(1)</script>"})

    html = Client().get(reverse("comment-list", args=[movie.id])).content.decode()

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.django_db
def test_create_is_rate_limited(monkeypatch, movie, other_movie, alice):
    monkeypatch.setattr(CommentCreateThrottle, "rate", "1/min")
    client = client_for(alice)

    first = client.post(create_url(movie), {"text": "one"})
    second = client.post(create_url(other_movie), {"text": "two"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Too many requests" in second.content.decode()
    assert Comment.objects.count() == 1


# == Deleting: owner only, no editing ==


@pytest.mark.django_db
def test_non_owner_cannot_delete(movie, alice, bob):
    comment = Comment.objects.create(movie=movie, user=alice, text="alice's")

    response = client_for(bob).post(reverse("comment-delete", args=[comment.id]))

    assert response.status_code == 403
    assert Comment.objects.filter(pk=comment.pk).exists()


@pytest.mark.django_db
def test_owner_can_delete_own_comment_and_its_votes(movie, alice, bob):
    comment = Comment.objects.create(movie=movie, user=alice, text="first try")
    other = Comment.objects.create(movie=movie, user=alice, text="stays")
    CommentVote.objects.create(comment=comment, user=bob, value=1)

    response = client_for(alice).post(reverse("comment-delete", args=[comment.id]))

    assert response.status_code == 200
    assert list(Comment.objects.all()) == [other]
    assert not CommentVote.objects.exists()  # votes go with the comment


@pytest.mark.django_db
def test_delete_requires_post(movie, alice):
    comment = Comment.objects.create(movie=movie, user=alice, text="x")

    assert client_for(alice).get(reverse("comment-delete", args=[comment.id])).status_code == 405
    assert Comment.objects.exists()


@pytest.mark.django_db
def test_comments_cannot_be_edited(movie, alice):
    comment = Comment.objects.create(movie=movie, user=alice, text="final")
    client = client_for(alice)

    # the old edit endpoint no longer exists
    assert client.post(f"/movies/comments/{comment.id}/edit/", {"text": "changed"}).status_code == 404
    # and the page offers the owner no edit control
    html = client.get(reverse("comment-list", args=[movie.id])).content.decode()
    assert "Delete" in html
    assert "Edit" not in html
    comment.refresh_from_db()
    assert comment.text == "final"


# == Voting ==


@pytest.mark.django_db
def test_vote_toggle_and_switch(movie, alice, bob):
    comment = Comment.objects.create(movie=movie, user=alice, text="vote on me")
    client = client_for(bob)

    def state():
        return list(CommentVote.objects.filter(comment=comment, user=bob).values_list("value", flat=True))

    response = vote(client, comment, 1)
    assert response.status_code == 200
    assert state() == [1]
    assert "cm-vote-up is-active" in response.content.decode()

    vote(client, comment, -1)  # opposite value switches
    assert state() == [-1]

    response = vote(client, comment, -1)  # same value again removes
    assert state() == []
    assert "is-active" not in response.content.decode()


@pytest.mark.django_db
def test_vote_counts_are_per_user(movie, alice, bob):
    carol = User.objects.create_user("carol", password="pass12345")
    comment = Comment.objects.create(movie=movie, user=alice, text="popular")
    vote(client_for(bob), comment, 1)

    response = vote(client_for(carol), comment, -1)

    html = response.content.decode()
    assert 'aria-label="Like (1)"' in html
    assert 'aria-label="Dislike (1)"' in html
    assert "cm-vote-down is-active" in html
    assert "cm-vote-up is-active" not in html  # bob's like isn't highlighted for carol


@pytest.mark.django_db
def test_cannot_vote_on_own_comment(movie, alice):
    comment = Comment.objects.create(movie=movie, user=alice, text="self-promo")

    response = vote(client_for(alice), comment, 1)

    assert response.status_code == 403
    assert not CommentVote.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["0", "2", "abc", ""])
def test_invalid_vote_value_is_rejected(movie, alice, bob, value):
    comment = Comment.objects.create(movie=movie, user=alice, text="x")

    response = vote(client_for(bob), comment, value)

    assert response.status_code == 400
    assert not CommentVote.objects.exists()


@pytest.mark.django_db
def test_voting_is_rate_limited(monkeypatch, movie, alice, bob):
    monkeypatch.setattr(CommentVoteThrottle, "rate", "2/min")
    comment = Comment.objects.create(movie=movie, user=alice, text="x")
    client = client_for(bob)

    codes = [vote(client, comment, 1).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


# == Listing ==


@pytest.mark.django_db
def test_list_sorting_and_load_more(movie):
    users = [User.objects.create_user(f"u{i}", password="pass12345") for i in range(12)]
    base = timezone.now() - timedelta(days=1)
    for i, user in enumerate(users):
        c = Comment.objects.create(movie=movie, user=user, text=f"comment-{i:02d}")
        Comment.objects.filter(pk=c.pk).update(created_at=base + timedelta(minutes=i))
    url = reverse("comment-list", args=[movie.id])

    newest_first = Client().get(url).content.decode()
    oldest_first = Client().get(url, {"sort": "old"}).content.decode()
    more = Client().get(url, {"sort": "new", "append": 1, "offset": 10}).content.decode()

    assert newest_first.index("comment-11") < newest_first.index("comment-10")
    assert "comment-01" not in newest_first  # 10 per batch
    assert "Show more" in newest_first
    assert oldest_first.index("comment-00") < oldest_first.index("comment-01")
    assert "comment-01" in more and "comment-00" in more
    assert "comment-02" not in more
    assert "Show more" not in more
    assert 'id="cm-feed"' not in more  # append returns only the next batch


@pytest.mark.django_db
def test_empty_state(movie):
    html = Client().get(reverse("comment-list", args=[movie.id])).content.decode()

    assert "No comments yet." in html


# == DRF API ==


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_api_list_is_public_with_counts_and_own_vote(api, movie, alice, bob):
    comment = Comment.objects.create(movie=movie, user=alice, text="hello")
    CommentVote.objects.create(comment=comment, user=bob, value=-1)
    url = reverse("api-comment-list", args=[movie.id])

    anonymous = api.get(url)
    api.force_authenticate(bob)
    as_bob = api.get(url, {"sort": "old"})

    assert anonymous.status_code == 200
    row = anonymous.data["results"][0]
    assert (row["username"], row["likes"], row["dislikes"], row["user_vote"]) == ("alice", 0, 1, None)
    assert as_bob.data["results"][0]["user_vote"] == -1
    assert as_bob.data["results"][0]["is_owner"] is False


@pytest.mark.django_db
def test_api_create_requires_auth_and_validates(api, movie, alice):
    url = reverse("api-comment-list", args=[movie.id])

    assert api.post(url, {"text": "hi"}).status_code == 401
    api.force_authenticate(alice)
    assert api.post(url, {"text": "   "}).status_code == 400
    assert api.post(url, {"text": "x" * 1001}).status_code == 400
    created = api.post(url, {"text": "  hi  "})
    assert created.status_code == 201
    assert created.data["text"] == "hi"
    assert api.post(url, {"text": "again"}).status_code == 201  # several comments per movie are fine


@pytest.mark.django_db
def test_api_only_owner_can_delete_and_nobody_can_edit(api, movie, alice, bob):
    comment = Comment.objects.create(movie=movie, user=alice, text="original")
    url = reverse("api-comment-detail", args=[comment.id])

    api.force_authenticate(bob)
    assert api.delete(url).status_code == 403
    assert Comment.objects.exists()

    api.force_authenticate(alice)
    assert api.patch(url, {"text": "edited"}).status_code == 405
    assert api.put(url, {"text": "edited"}).status_code == 405
    comment.refresh_from_db()
    assert comment.text == "original"
    assert api.delete(url).status_code == 204
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_api_vote_toggle_and_own_comment(api, movie, alice, bob):
    comment = Comment.objects.create(movie=movie, user=alice, text="x")
    url = reverse("api-comment-vote", args=[comment.id])

    assert api.post(url, {"value": 1}).status_code == 401

    api.force_authenticate(bob)
    assert api.post(url, {"value": 1}).data == {"likes": 1, "dislikes": 0, "user_vote": 1}
    assert api.post(url, {"value": -1}).data == {"likes": 0, "dislikes": 1, "user_vote": -1}
    assert api.post(url, {"value": -1}).data == {"likes": 0, "dislikes": 0, "user_vote": None}
    assert api.post(url, {"value": 5}).status_code == 400

    api.force_authenticate(alice)
    own = api.post(url, {"value": 1})
    assert own.status_code == 403
    assert "own comment" in own.data["detail"]
