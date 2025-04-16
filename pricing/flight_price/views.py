import json
import ast
from amadeus import Client, ResponseError, Location
from django.shortcuts import render
from django.contrib import messages
from .flight import Flight
from .metrics import Metrics
from django.http import HttpResponse

amadeus = Client()


def flight_offers(request):
    if request.method == 'GET':
        return render(request, 'flight_price/home.html')
        
    origin = request.POST.get('Origin')
    destinations = request.POST.getlist('Destination')
    departure_date = request.POST.get('Departuredate')
    return_date = request.POST.get('Returndate')

    if not origin or not destinations or not departure_date:
        messages.error(request, 'Please fill in all required fields')
        return render(request, 'flight_price/home.html')

    all_results = []
    trip_purposes = {}
    metrics = {}
    cheapest_flights = {}
    is_good_deals = {}

    try:
        for destination in destinations:
            kwargs = {'originLocationCode': origin,
                     'destinationLocationCode': destination,
                     'departureDate': departure_date,
                     'adults': 1
                     }

            kwargs_metrics = {'originIataCode': origin,
                            'destinationIataCode': destination,
                            'departureDate': departure_date
                            }

            if return_date:
                kwargs['returnDate'] = return_date
                kwargs_trip_purpose = {'originLocationCode': origin,
                                     'destinationLocationCode': destination,
                                     'departureDate': departure_date,
                                     'returnDate': return_date
                                     }
                trip_purposes[destination] = get_trip_purpose(**kwargs_trip_purpose)
            else:
                kwargs_metrics['oneWay'] = 'true'

            if origin and destination and departure_date:
                flight_offers = get_flight_offers(**kwargs)
                metrics[destination] = get_flight_price_metrics(**kwargs_metrics)
                cheapest_flights[destination] = get_cheapest_flight_price(flight_offers)
                
                if metrics[destination] is not None:
                    is_good_deals[destination] = rank_cheapest_flight(
                        cheapest_flights[destination], 
                        metrics[destination]['first'], 
                        metrics[destination]['third']
                    )
                    is_cheapest_flight_out_of_range(cheapest_flights[destination], metrics[destination])

                all_results.append({
                    'flight_offers': flight_offers,
                    'destination': destination,
                    'metrics': metrics[destination],
                    'cheapest_flight': cheapest_flights[destination],
                    'is_good_deal': is_good_deals.get(destination, ''),
                    'trip_purpose': trip_purposes.get(destination, '')
                })

        return render(request, 'flight_price/results.html', {
            'all_results': all_results,
            'origin': origin,
            'departure_date': departure_date,
            'return_date': return_date
        })

    except ResponseError as error:
        messages.add_message(request, messages.ERROR, error.response.result['errors'][0]['detail'])
        return render(request, 'flight_price/home.html', {})
    return render(request, 'flight_price/home.html', {})


def get_flight_offers(**kwargs):
    search_flights = amadeus.shopping.flight_offers_search.get(**kwargs)
    flight_offers = []
    for flight in search_flights.data:
        offer = Flight(flight).construct_flights()
        flight_offers.append(offer)
    return flight_offers


def get_flight_price_metrics(**kwargs_metrics):
    kwargs_metrics['currencyCode'] = 'USD'
    metrics = amadeus.analytics.itinerary_price_metrics.get(**kwargs_metrics)
    return Metrics(metrics.data).construct_metrics()


def get_trip_purpose(**kwargs_trip_purpose):
    trip_purpose = amadeus.travel.predictions.trip_purpose.get(**kwargs_trip_purpose).data
    return trip_purpose['result']


def get_cheapest_flight_price(flight_offers):
    return flight_offers[0]['price']


def rank_cheapest_flight(cheapest_flight_price, first_price, third_price):
    cheapest_flight_price_to_number = float(cheapest_flight_price)
    first_price_to_number = float(first_price)
    third_price_to_number = float(third_price)
    if cheapest_flight_price_to_number < first_price_to_number:
        return 'A GOOD DEAL'
    elif cheapest_flight_price_to_number > third_price_to_number:
        return 'HIGH'
    else:
        return 'TYPICAL'


def is_cheapest_flight_out_of_range(cheapest_flight_price, metrics):
    min_price = float(metrics['min'])
    max_price = float(metrics['max'])
    cheapest_flight_price_to_number = float(cheapest_flight_price)
    if cheapest_flight_price_to_number < min_price:
        metrics['min'] = cheapest_flight_price
    elif cheapest_flight_price_to_number > max_price:
        metrics['max'] = cheapest_flight_price


def origin_airport_search(request):
    if request.is_ajax():
        try:
            data = amadeus.reference_data.locations.get(keyword=request.GET.get('term', None),
                                                        subType=Location.ANY).data
        except ResponseError as error:
            messages.add_message(request, messages.ERROR, error.response.result['errors'][0]['detail'])
    return HttpResponse(get_city_airport_list(data), 'application/json')


def destination_airport_search(request):
    if request.is_ajax():
        try:
            data = amadeus.reference_data.locations.get(keyword=request.GET.get('term', None),
                                                        subType=Location.ANY).data
        except ResponseError as error:
            messages.add_message(request, messages.ERROR, error.response.result['errors'][0]['detail'])
    return HttpResponse(get_city_airport_list(data), 'application/json')


def get_city_airport_list(data):
    result = []
    for i, val in enumerate(data):
        result.append(data[i]['iataCode'] + ', ' + data[i]['name'])
    result = list(dict.fromkeys(result))
    return json.dumps(result)
