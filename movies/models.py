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
    release_date = models.DateField(blank=True, null=True) # blank=True	Поле можна залишити порожнім у формі
    country = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    poster_url = models.URLField(blank=True, null=True)
    tmdb_id = models.IntegerField(null=True, blank=True, unique=True)
    genres = models.ManyToManyField(Genre, related_name="movies")
    author = models.CharField(max_length=200)
    actors = models.CharField(max_length=200)
    media_type = models.CharField(max_length=20, default="movie")
    tmdb_rating = models.FloatField(blank=True, null=True)

    def __str__(self):
        return self.title
    
    def average_user_ratings(self):
        ratings = self.ratings.all()
        if ratings.exists():
            return round(sum(r.score for r in ratings) / ratings.count(), 1)
        return None

class Rating(models.Model):
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE, related_name="ratings") # Кожен рейтинг належить одному фільму
    user =models.ForeignKey(User, on_delete=models.CASCADE)
    score = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "movie"], name="rating_unique_user_movie")
        ]

    def __str__(self):
        return f"{self.user.username} - {self.movie.title} ({self.score})"


class Comment(models.Model):
    movie = models.ForeignKey(Movies, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.movie.title}"


