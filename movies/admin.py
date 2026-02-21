
from django.contrib import admin
from .models import Movies

class MoviesAdmin(admin.ModelAdmin):
    list_display = ['title', 'release_date', 'country', 'description', 'poster_url', 'tmdb_id']
    search_fields = ("authorpython mana  ","title")

admin.site.register(Movies, MoviesAdmin) # відправляєм нашу базу на сервер і там підвязуєм в admin сторінці


