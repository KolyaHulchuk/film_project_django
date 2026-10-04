from django.contrib import admin

from .models import Comment, Movies


class MoviesAdmin(admin.ModelAdmin):
    list_display = ["tmdb_id", "title", "release_date", "country", "description", "country", "tmdb_rating"]
    search_fields = ("authorpython mana  ", "title")


admin.site.register(Movies, MoviesAdmin)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["id", "movie", "user", "created_at"]
    list_select_related = ["movie", "user"]
    search_fields = ["text", "user__username", "movie__title"]
    raw_id_fields = ["movie", "user"]
