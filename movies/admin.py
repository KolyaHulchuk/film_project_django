
from django.contrib import admin
from .models import Movies

admin.site.register(Movies) # відправляєм нашу базу на сервер і там підвязуєм в admin сторінці


