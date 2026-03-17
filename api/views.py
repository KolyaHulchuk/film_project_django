from django.shortcuts import render
from rest_framework import generics
from .serializers import (
    MovieSerializer, 
    GerneSerializer, 
    RatingSerializer, 
    ProfileSerializer, 
    WatchlistSerializer
    )
from movies.models import Movies, Genre, Rating
from users.models import Profile, Watchlist
from rest_framework.permissions import (
    AllowAny, 
    IsAdminUser, 
    IsAuthenticated, 
    IsAuthenticatedOrReadOnly
    )


class MovieListView(generics.ListAPIView):
    serializer_class = MovieSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Movies.objects.all()
        genre = self.request.query_params.get('genre', '')
        if genre:
            queryset =queryset.filter(genres__name=genre)
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