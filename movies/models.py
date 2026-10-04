from django.contrib.auth.models import User
from django.db import models


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    tmdb_id = models.IntegerField(null=True, blank=True, unique=True)

    def __str__(self):
        return self.name


class Movies(models.Model):
    title = models.CharField(max_length=200)
    release_date = models.DateField(blank=True, null=True)  # optional: TMDB doesn't always provide a release date
    country = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    poster_url = models.URLField(blank=True)
    tmdb_id = models.IntegerField(null=True, blank=True, unique=True)
    genres = models.ManyToManyField(Genre, related_name="movies")
    author = models.CharField(max_length=200)
    actors = models.CharField(max_length=200)
    media_type = models.CharField(max_length=20, default="movie")
    tmdb_rating = models.FloatField(blank=True, null=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.title

    def average_user_ratings(self):
        ratings = self.ratings.all()
        if ratings.exists():
            return round(sum(r.score for r in ratings) / ratings.count(), 1)
        return None


class Rating(models.Model):
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    score = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "movie"], name="rating_unique_user_movie")]

    def __str__(self):
        return f"{self.user.username} - {self.movie.title} ({self.score})"


COMMENT_MAX_LENGTH = 1000


class Comment(models.Model):
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # max_length on a TextField is not enforced by the database, only by forms/serializers,
    # which is why CommentForm and CommentSerializer both repeat the limit.
    text = models.TextField(max_length=COMMENT_MAX_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Serves the movie page's "newest first" feed (filter by movie, order by date)
        indexes = [models.Index(fields=["movie", "-created_at"], name="comment_movie_created_idx")]

    def __str__(self):
        return f"{self.user.username} - {self.movie.title}"

    @property
    def author_avatar_url(self):
        """Uploaded avatar URL, or None when the author still has the default image."""
        profile = getattr(self.user, "profile", None)  # RelatedObjectDoesNotExist is an AttributeError
        if profile and profile.image and profile.image.name != "default.jpg":
            return profile.image.url
        return None

    @property
    def author_hue(self):
        # Stable per-user hue for the letter placeholder, so the same person keeps the same colour.
        return sum(map(ord, self.user.username)) * 37 % 360


class CommentVote(models.Model):
    LIKE = 1
    DISLIKE = -1
    VALUE_CHOICES = [(LIKE, "Like"), (DISLIKE, "Dislike")]

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comment_votes")
    value = models.SmallIntegerField(choices=VALUE_CHOICES)

    class Meta:
        constraints = [
            # One vote per user per comment; the database guarantees it even under concurrent requests
            models.UniqueConstraint(fields=["comment", "user"], name="commentvote_unique_user_comment"),
            models.CheckConstraint(condition=models.Q(value__in=[1, -1]), name="commentvote_value_valid"),
        ]

    def __str__(self):
        return f"{self.user.username} {self.value:+d} on comment {self.comment_id}"
