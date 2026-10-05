from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .emails import DUPLICATE_EMAIL_MESSAGE, email_taken, normalize_email
from .models import Profile, Watchlist

# Register your models here.

admin.site.register(Profile)


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ["user", "movie", "watched"]
    search_fields = ("user__username", "movie__title")


class UniqueEmailUserAdminMixin:
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        def clean_email(self_form):
            email = normalize_email(self_form.cleaned_data.get("email"))
            if email_taken(email, exclude_user_id=self_form.instance.pk):
                raise ValidationError(DUPLICATE_EMAIL_MESSAGE)
            return email

        form.clean_email = clean_email
        return form


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(UniqueEmailUserAdminMixin, DjangoUserAdmin):
    pass
