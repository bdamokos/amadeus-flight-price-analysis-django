from django.urls import path
from . import views


urlpatterns = [
    path('', views.flight_offers, name='flight_offers'),
    path('origin_airport_search/', views.origin_airport_search, name='origin_airport_search'),
    path('destination_airport_search/', views.destination_airport_search, name='destination_airport_search'),
    path('add_south_america_airports/', views.add_south_america_airports, name='add_south_america_airports'),
]
