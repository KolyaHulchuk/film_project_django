from axes.handlers.proxy import AxesProxyHandler
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, Throttled
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from movies.models import COMMENT_MAX_LENGTH, Comment, CommentVote, Genre, Movies, Rating
from users.lockout import cooloff_seconds, lockout_message
from users.models import Profile, Watchlist
from users.security_log import security_event


class GerneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ["name"]


class MovieSerializer(serializers.ModelSerializer):
    genres = GerneSerializer(many=True, read_only=True)
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = Movies

        fields = [
            "id",
            "tmdb_id",
            "title",
            "release_date",
            "country",
            "description",
            "genres",
            "author",
            "actors",
            "tmdb_rating",
            "media_type",
            "average_rating",
        ]
        read_only_fields = [
            "id",
            "tmdb_id",
            "title",
            "release_date",
            "country",
            "description",
            "genres",
            "author",
            "actors",
            "tmdb_rating",
            "media_type",
        ]

    def validate_release_date(self, value):
        if value.year < 1888:
            raise serializers.ValidationError("cinema had not yet been invented")
        return value

    def validate_tmdb_rating(self, value):
        if value < 0 or value > 10:
            raise serializers.ValidationError("The rating should be between 0 and 10")
        return value

    def get_average_rating(self, obj):
        return obj.average_user_ratings()


class RatingSerializer(serializers.ModelSerializer):
    movie = serializers.StringRelatedField(read_only=True)
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Rating

        fields = ["id", "movie", "user", "score"]
        read_only_fields = ["id", "movie", "user"]

    def validate_score(self, value):
        if value < 1 or value > 10:
            raise serializers.ValidationError("Rating from 1 to 10")
        return value


class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = Profile
        fields = ["id", "username", "email", "image"]
        read_only_fields = ["id", "username", "email"]


class WatchlistSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    movie = serializers.StringRelatedField(read_only=True)
    movie_id = serializers.PrimaryKeyRelatedField(
        queryset=Movies.objects.all(), source="movie", write_only=True, required=False
    )

    class Meta:
        model = Watchlist
        fields = ["id", "user", "movie", "movie_id", "watched"]
        read_only_fields = ["id", "user", "movie"]


class CommentSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    # CharField trims surrounding whitespace and rejects blank strings by default
    text = serializers.CharField(max_length=COMMENT_MAX_LENGTH)
    is_owner = serializers.SerializerMethodField()
    # Annotated by movies.comments.annotate_comments(); the defaults cover a freshly created comment
    likes = serializers.IntegerField(read_only=True, default=0)
    dislikes = serializers.IntegerField(read_only=True, default=0)
    user_vote = serializers.IntegerField(read_only=True, allow_null=True, default=None)

    class Meta:
        model = Comment
        fields = [
            "id",
            "movie",
            "username",
            "avatar_url",
            "text",
            "created_at",
            "is_owner",
            "likes",
            "dislikes",
            "user_vote",
        ]
        read_only_fields = ["movie", "created_at"]

    def get_avatar_url(self, obj):
        url = obj.author_avatar_url
        request = self.context.get("request")
        return request.build_absolute_uri(url) if url and request else url

    def get_is_owner(self, obj):
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.user_id == request.user.id)


class CommentVoteSerializer(serializers.Serializer):
    value = serializers.ChoiceField(choices=[CommentVote.LIKE, CommentVote.DISLIKE])


class LoggedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """/api/token/ (SIMPLE_JWT["TOKEN_OBTAIN_SERIALIZER"]): the default serializer plus a security log line
    for each issued token pair. Wrong credentials are already logged by the user_login_failed signal.

    django-axes (users/lockout.py) counts the failures here too, but its middleware only sees Django's
    request, not DRF's, so the lockout answer (429 + Retry-After) and the reset on success are done here."""

    def validate(self, attrs):
        request = self.context.get("request")
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            if getattr(request, "axes_locked_out", False):
                locked = Throttled(detail=lockout_message())
                locked.wait = cooloff_seconds()  # Retry-After, without DRF's "Expected available in ..." suffix
                raise locked from None
            raise
        # The site's logins clear the failure counter through Django's user_logged_in signal,
        # which issuing a token doesn't send.
        AxesProxyHandler.user_logged_in(type(self), request, self.user)
        security_event("login", request, user_id=self.user.pk, backend="jwt")
        return data
