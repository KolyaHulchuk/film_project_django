from django.contrib import admin
from .models import Profile, Watchlist

# Register your models here.

admin.site.register(Profile)

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ("user", "movie") # створиться таблиця в адмінці з цими полями
    search_fields = ("user__username", "movie__title") # можна шукати по імені і назві в адмінці