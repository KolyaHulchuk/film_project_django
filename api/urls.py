from django.urls import path

from .views import (
    CommentDetailView,
    CommentListCreateView,
    CommentVoteView,
    GenreListView,
    MovieDetailView,
    MovieListView,
    PopularActorsView,
    ProfileView,
    RatingView,
    RecommendationsAiView,
    WatchlistDetailView,
    WatchlistListView,
)

urlpatterns = [
    path("movie/", MovieListView.as_view(), name="api-movie-list"),
    path("movie/<int:pk>/", MovieDetailView.as_view(), name="api-movie-datail"),
    path("genre/", GenreListView.as_view(), name="api-genre"),
    path("rating/", RatingView.as_view(), name="api-rating"),
    path("profile/", ProfileView.as_view(), name="api-profile"),
    path("watchlist/", WatchlistListView.as_view(), name="api-watchlist"),
    path("watchlist/<int:pk>/", WatchlistDetailView.as_view(), name="api-watchlist-detail"),
    path("recommendations/", RecommendationsAiView.as_view(), name="ai-recommendations"),
    path("popular-actor/", PopularActorsView.as_view(), name="popular-actor"),
    path("movie/<int:movie_id>/comments/", CommentListCreateView.as_view(), name="api-comment-list"),
    path("comments/<int:pk>/", CommentDetailView.as_view(), name="api-comment-detail"),
    path("comments/<int:pk>/vote/", CommentVoteView.as_view(), name="api-comment-vote"),
]
