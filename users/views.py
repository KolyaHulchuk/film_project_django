from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from .forms import UserRegisterForm, UserUpdateForm, ProfileUpdateForm
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from movies.views import get_or_create_media
from .models import Watchlist
from django.views import View
from django.views.generic import (
    ListView
)



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
            if created:
                messages.success(request, f"{movie.title or movie.name} додано у ваш список")
            else:
                messages.info(request, f"{movie.title or movie.name} вже є у вашом списку")
        else:
            messages.error(request, "Не вдалося знайти дані про цей фільм")
        next_url = request.POST.get("next") or request.META.get("HTTP-REFERER") or "movies-home"
        print("AddToWatchlist called")

        return redirect(next_url)

class WatchlistView(ListView):
    model = Watchlist
    template_name="users/watchlist.html"
    context_object_name = "watchlist"
    paginate_by = 20

    def get_queryset(self):
        return Watchlist.objects.filter(user=self.request.user)
