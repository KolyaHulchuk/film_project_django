from django.urls import path
from django.contrib.auth import views as auth_views # набір готових в’юх Django для автентифікації.
from . import views

urlpatterns = [
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout' ),
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    

    path('watchlist/', views.WatchlistView.as_view(), name="watchlist"),
    path('watchlist/add/<int:tmdb_id>/<str:media_type>', views.AddToWatchlist.as_view(), name="add_watchlist"),
    path('profile/', views.profile, name='profile'),

    # reset password
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name="users/password_reset.html"), name="password_reset"),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name="users/password_reset_complete.html"), name="password_reset_complete"),
]