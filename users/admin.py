from django.contrib import admin
from .models import Profile, Watchlist

# Register your models here.

admin.site.register(Profile)

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ["user", "movie", "watched"]
    search_fields = ("user__username", "movie__title")