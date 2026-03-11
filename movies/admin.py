
from django.contrib import admin
from .models import Movies

class MoviesAdmin(admin.ModelAdmin):
    list_display = [ 'tmdb_id', 'title', 'release_date', 'country', 'description', 'country', 'tmdb_rating' ]
    search_fields = ("authorpython mana  ","title")

admin.site.register(Movies, MoviesAdmin) # відправляєм нашу базу на сервер і там підвязуєм в admin сторінці


