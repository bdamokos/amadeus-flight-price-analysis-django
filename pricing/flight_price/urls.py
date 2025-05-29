from django.urls import path
from . import views


urlpatterns = [
    path('', views.flight_offers, name='flight_offers'),
    path('origin_airport_search/', views.origin_airport_search, name='origin_airport_search'),
    path('destination_airport_search/', views.destination_airport_search, name='destination_airport_search'),
    path('add_south_america_airports/', views.add_south_america_airports, name='add_south_america_airports'),
    path('add_europe_airports/', views.add_europe_airports, name='add_europe_airports'),
    path('add_asia_airports/', views.add_asia_airports, name='add_asia_airports'),
    path('add_north_america_airports/', views.add_north_america_airports, name='add_north_america_airports'),
    path('add_africa_airports/', views.add_africa_airports, name='add_africa_airports'),
    path('add_oceania_airports/', views.add_oceania_airports, name='add_oceania_airports'),
]
