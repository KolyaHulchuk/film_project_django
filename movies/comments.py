"""Comment queries and voting rules shared by the template views (movies/views.py) and the DRF API (api/views.py)."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value

from .models import Comment, CommentVote

COMMENTS_PER_PAGE = 10
# `id` is a tie-breaker: comments created within the same instant (or a seeded batch) would otherwise
# come back in an unstable order, which breaks offset-based "Show more" paging.
SORT_ORDERINGS = {
    "new": ("-created_at", "-id"),
    "old": ("created_at", "id"),
}
DEFAULT_SORT = "new"


def normalize_sort(sort):
    return sort if sort in SORT_ORDERINGS else DEFAULT_SORT


def annotate_comments(queryset, user):
    """Adds `likes`, `dislikes` and `user_vote` (1, -1 or None) in the same query - no per-comment lookups."""
    # select_related pulls author + avatar in the same query (no N+1 per rendered comment);
    # the two Counts share a single join on votes, each narrowed by its own filter.
    queryset = queryset.select_related("user__profile").annotate(
        likes=Count("votes", filter=Q(votes__value=CommentVote.LIKE)),
        dislikes=Count("votes", filter=Q(votes__value=CommentVote.DISLIKE)),
    )
    if user.is_authenticated:
        own_vote = CommentVote.objects.filter(comment=OuterRef("pk"), user=user).values("value")[:1]
        return queryset.annotate(user_vote=Subquery(own_vote, output_field=IntegerField()))
    # Anonymous visitors have no vote; annotate None so templates/serializers can read `user_vote` uniformly.
    return queryset.annotate(user_vote=Value(None, output_field=IntegerField()))


def movie_comments(movie, user, sort=DEFAULT_SORT):
    return annotate_comments(Comment.objects.filter(movie=movie), user).order_by(*SORT_ORDERINGS[normalize_sort(sort)])


def get_annotated_comment(pk, user):
    return annotate_comments(Comment.objects.filter(pk=pk), user).get()


def toggle_vote(comment, user, value):
    """
    Same value again removes the vote, the opposite value switches it.
    Returns the user's vote after the change (1, -1 or None).
    """
    if value not in (CommentVote.LIKE, CommentVote.DISLIKE):
        raise ValueError("value must be 1 or -1")
    if comment.user_id == user.id:
        raise PermissionDenied("You can't vote on your own comment.")

    with transaction.atomic():
        # select_for_update locks this vote row so a second fast click waits instead of
        # reading a stale vote.value; atomic ensures the delete/update below is all-or-nothing
        # get_or_create absorbs the unique-constraint race from a fast double click
        vote, created = CommentVote.objects.select_for_update().get_or_create(
            comment=comment, user=user, defaults={"value": value}
        )
        if created:
            return value
        if vote.value == value:
            vote.delete()
            return None
        vote.value = value
        vote.save(update_fields=["value"])
        return value
