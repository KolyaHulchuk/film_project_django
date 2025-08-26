from django.db import models
from django.contrib.auth.models import User


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    tmdb_id = models.IntegerField(null=True, blank=True, unique=True)

    def __str__(self):
        return self.name
    
class Actor(models.Model):
    name = models.CharField(max_length=200)
    tmdb_id = models.IntegerField(null=True, blank=True, unique=True)

    def __str__(self):
        return self.name

class Movies(models.Model):
    title = models.CharField(max_length=200)
    relase_date = models.DateTimeField(blank=True, null=True)
    country = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    poster_url = models.URLField(blank=True, null=True)
    tmdb_id = models.IntegerField(null=True, blank=True, unique=True)
    genres = models.ManyToManyField(Genre, related_name="movies")
    author = models.CharField(max_length=200)
    actors = models.CharField(max_length=200)

    def __str__(self):
        return self.title

class Rating(models.Model):
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE, related_name="ratings")
    user =models.ForeignKey(User, on_delete=models.CASCADE)
    score = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("user", "movie")

    def __str__(self):
        return f"{self.user.username} - {self.movie.title} ({self.score})"


class Comment(models.Model):
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.movie.title}"


class UserMovies(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE)
    added_to_wathclist = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.movie.title}"
    
