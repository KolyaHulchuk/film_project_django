from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import (
    SAFE_METHODS,
    AllowAny,
    BasePermission,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from movies.comments import COMMENTS_PER_PAGE, annotate_comments, get_annotated_comment, movie_comments, toggle_vote
from movies.models import Comment, Genre, Movies, Rating
from movies.services import get_ai
from movies.throttling import (
    AIRecommendationAnonThrottle,
    AIRecommendationThrottle,
    CommentCreateThrottle,
    CommentVoteThrottle,
)
from movies.tmdb_service import TMDBClient
from users.models import Watchlist

from .serializers import (
    CommentSerializer,
    CommentVoteSerializer,
    GerneSerializer,
    MovieSerializer,
    ProfileSerializer,
    RatingSerializer,
    WatchlistSerializer,
)


class MovieListView(generics.ListAPIView):
    serializer_class = MovieSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Movies.objects.all()
        genre = self.request.query_params.get("genre", "")
        if genre:
            queryset = queryset.filter(genres__name=genre)
        return queryset


class MovieDetailView(generics.RetrieveAPIView):
    queryset = Movies.objects.all()
    serializer_class = MovieSerializer
    permission_classes = [AllowAny]


class GenreListView(generics.ListAPIView):
    queryset = Genre.objects.all()
    serializer_class = GerneSerializer
    permission_classes = [AllowAny]


class RatingView(generics.ListCreateAPIView):
    queryset = Rating.objects.all()
    serializer_class = RatingSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class ProfileView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user.profile


class WatchlistListView(generics.ListCreateAPIView):
    serializer_class = WatchlistSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Watchlist.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class WatchlistDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WatchlistSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Watchlist.objects.filter(user=self.request.user)


class RecommendationsAiView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [AIRecommendationThrottle, AIRecommendationAnonThrottle]

    def get(self, request):
        message = request.query_params.get("message", "")
        media_type = request.query_params.get("type", "all")

        result = get_ai(request.user, message, media_type)
        return Response(result)


class PopularActorsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        client = TMDBClient()
        page = int(request.GET.get("page", 1))
        data = client.get_popular_actors(page)
        return Response(data)


class CommentPagination(PageNumberPagination):
    page_size = COMMENTS_PER_PAGE


class IsCommentOwner(BasePermission):
    message = "You can only delete your own comments."

    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.user_id == request.user.id


class CommentListCreateView(generics.ListCreateAPIView):
    """GET ?sort=new|old&page=N lists a movie's comments; POST {"text": ...} adds a comment."""

    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = CommentPagination

    def get_throttles(self):
        return [CommentCreateThrottle()] if self.request.method == "POST" else []

    def get_movie(self):
        return get_object_or_404(Movies, pk=self.kwargs["movie_id"])

    def get_queryset(self):
        return movie_comments(self.get_movie(), self.request.user, self.request.query_params.get("sort"))

    def perform_create(self, serializer):
        serializer.save(movie=self.get_movie(), user=self.request.user)


class CommentDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsCommentOwner]

    def get_queryset(self):
        return annotate_comments(Comment.objects.all(), self.request.user)


class CommentVoteView(APIView):
    """POST {"value": 1 | -1}: same value again removes the vote, the opposite one switches it."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [CommentVoteThrottle]

    def post(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        serializer = CommentVoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            toggle_vote(comment, request.user, serializer.validated_data["value"])
        except DjangoPermissionDenied as err:
            raise PermissionDenied(str(err)) from None

        comment = get_annotated_comment(pk, request.user)
        return Response({"likes": comment.likes, "dislikes": comment.dislikes, "user_vote": comment.user_vote})
