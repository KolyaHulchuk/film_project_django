from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from .forms import UserRegisterForm, UserUpdateForm, ProfileUpdateForm
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from movies.views import get_or_create_media
from .models import Watchlist
from django.views import View
from movies.models import Movies
from django.http import HttpResponse
from django.views.generic import (
    ListView,
    DeleteView
)

import math

# Truncate to 1 decimal place
def truncate(number, decimals=1):
    multiplier = 10 ** decimals
    return math.floor(number * multiplier) / multiplier # math.floor always rounds down

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f"Your account has been created! You are now able to log in {username}")
            return redirect("movies-home")
    else:
        form = UserRegisterForm()
    
    context = {
        'form': form,
        'title': 'Register'
    }
    return render(request, 'users/register.html', context)

@login_required
def profile(request):
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)

        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            messages.success(request, f"Your account has been update")
        
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = ProfileUpdateForm(instance=request.user.profile)


    context = {
        "u_form": u_form,
        "p_form": p_form,
        "title": "Profile"
    }

    return render(request, 'users/profile.html', context)

@method_decorator(login_required, name="dispatch")
class AddToWatchlist(View):
    def post(self, request, tmdb_id, media_type):
        movie = get_or_create_media(tmdb_id, media_type)
        if movie:
            watchlist_item, created =  Watchlist.objects.get_or_create(user=request.user, movie=movie)
            if created: # if just create
                messages.success(request, f"{movie.title or movie.name} додано у ваш список")
            else:
                messages.info(request, f"{movie.title or movie.name} вже є у вашом списку")
        else:
            messages.error(request, "Не вдалося знайти дані про цей фільм")
        next_url = request.POST.get("next") or request.META.get("HTTP-REFERER") or "movies-home"
        print("AddToWatchlist called")

        return redirect(next_url)

  
@method_decorator(login_required, name="dispatch")
class DeleteWatchlist(DeleteView):
    model = Watchlist

    def get_queryset(self): # filter movies by current user
        return Watchlist.objects.filter(user=self.request.user)

    def delete(self, request, *args, **kwargs):
        self.object  = self.get_object()
        self.object.delete()

        if request.headers.get("HX-Request"):
            return HttpResponse("") # return empty response for HTMX requests
        return redirect("watchlist") # regular request — redirect to watchlist page


@login_required    
def toggle_watched(request, watchlist_id):
    item = Watchlist.objects.get(id=watchlist_id, user=request.user)
    if request.method == "POST":
        item.watched = not item.watched
        item.save()
        return HttpResponse("OK")


@login_required
def search_watchlist(request):
    watchlist_items = Watchlist.objects.filter(user=request.user)
    
  
    
    years_search = (request.GET.get("years_search") or "").strip()
    if years_search:
        watchlist_items = watchlist_items.filter(movie__release_date__icontains=years_search) #  __icontains performs case-insensitive search in the DB

    country_search = (request.GET.get("country_search") or "").strip()
    if country_search:
        watchlist_items = watchlist_items.filter(movie__country__icontains=country_search) #  movie is the relation between Movie and Watchlist tables

    genre_search = (request.GET.get("genre_search") or "").strip()
    if genre_search:
        watchlist_items = watchlist_items.filter(movie__genres__name__icontains=genre_search)


    rating_search = (request.GET.get("rating_search") or '').strip()
    if rating_search:
        try:
            rating = float(rating_search)
        
            # Create a range: rating=5.0, add 1 gives 6.0, resulting in range from 5.0 to 6.0
            watchlist_items = watchlist_items.filter(
                movie__tmdb_rating__gte=rating, # gte operator >= (greater than or equal)
                movie__tmdb_rating__lt=rating + 1  # lt operator < (less than)
                                                     )
        except ValueError:
            pass

    name_search = (request.GET.get("name_search") or "").strip()
    if name_search:
        watchlist_items = watchlist_items.filter(movie__title__icontains=name_search)

    return render(request, "users/partials/watchlist_result.html",
                    {
                    "watchlist": watchlist_items,
                    }
                )


            
     

class WatchlistView(ListView):
    model = Watchlist
    template_name="users/watchlist.html"
    context_object_name = "watchlist"
    paginate_by = 20

    def get_queryset(self):
        return Watchlist.objects.filter(user=self.request.user).order_by("-id")



    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["years"] = range(2026, 2020, -1)
        context["genres"] = ['Comedy', 'Horror', 'Adventure', 'Action']

        countries_list = Watchlist.objects.filter(
            user=self.request.user
        ).values_list("movie__country", flat=True).distinct() # distinct removes duplicates, flat returns a plain list instead of tuples

        all_countries = set()

        for country_str in countries_list:
            if country_str:
                for country in country_str.split(','): # split by comma where one entry may contain multiple countries
                    all_countries.add(country.strip())
                
        context["countries"] = sorted(all_countries) # sort alphabetically

        return context

       