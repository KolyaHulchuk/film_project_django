
from django.contrib import admin
from .models import Movies

class MoviesAdmin(admin.ModelAdmin):
    list_display = ['title', 'release_date', 'country', 'description', 'poster_url', 'tmdb_id']


admin.site.register(Movies, MoviesAdmin) # відправляєм нашу базу на сервер і там підвязуєм в admin сторінці


