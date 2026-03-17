from movies.models import Movies, Genre, Rating
from users.models import Profile, Watchlist
from rest_framework import serializers


class GerneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ['name']





class MovieSerializer(serializers.ModelSerializer):
    genres = GerneSerializer(many=True, read_only=True)
    average_rating = serializers.SerializerMethodField()


    class Meta:
        model = Movies

        
        fields = ['id', 'tmdb_id', 'title', 'release_date', 'country', 'description', 'genres', 'author', 'actors', 'tmdb_rating', 'media_type', 'average_rating']
        read_only_fields = ['id',  'tmdb_id', 'title', 'release_date', 'country', 'description', 'genres', 'author', 'actors', 'tmdb_rating', 'media_type']

    def validate_release_date(self, value):
        if value.year < 1888:
            raise serializers.ValidationError("cinema had not yet been invented")
        return value
        
    def validate_tmdb_rating(self, value):
        if value < 0 or value > 10:
            raise serializers.ValidationError('The rating should be between 0 and 10')
        return value
    
    def get_average_rating(self, obj):
        return obj.average_user_ratings()
        

class RatingSerializer(serializers.ModelSerializer):
    movie = serializers.StringRelatedField(read_only=True)
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Rating
        
        fields = ['id','movie', 'user', 'score']
        read_only_fields = ['id', 'movie', 'user']


    def validate_score(self, value):
        if value < 1 or value > 10:
            raise serializers.ValidationError('Rating from 1 to 10')
        return value









class ProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email=  serializers.CharField(source='user.email', read_only=True)
    class Meta:
        model = Profile
        fields = ['id', 'username', 'email', 'image']
        read_only_fields = ['id', 'username', 'email']


class WatchlistSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    movie = serializers.StringRelatedField(read_only=True)
    movie_id= serializers.PrimaryKeyRelatedField(
        queryset= Movies.objects.all(),
        source='movie',
        write_only=True,
        required=False
    )

    class Meta:
        model = Watchlist
        fields = ['id', 'user', 'movie', 'movie_id', 'watched']
        read_only_fields = ['id', 'user', 'movie']


