import json
import ast
import logging
from amadeus import Client, ResponseError, Location
from django.shortcuts import render
from django.contrib import messages
from .flight import Flight
from .metrics import Metrics
from django.http import HttpResponse

# Configure logging
logger = logging.getLogger(__name__)

amadeus = Client()


def flight_offers(request):
    if request.method == 'GET':
        return render(request, 'flight_price/home.html')
        
    try:
        origin = request.POST.get('Origin')
        destinations = request.POST.getlist('Destination')
        departure_date = request.POST.get('Departuredate')
        return_date = request.POST.get('Returndate')
        currency = request.POST.get('Currency', 'USD')  # Default to USD if not specified

        logger.info(f"Flight search request - Origin: {origin}, Destinations: {destinations}, Departure: {departure_date}, Return: {return_date}")

        if not origin or not destinations or not departure_date:
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'flight_price/home.html')

        all_results = []
        trip_purposes = {}
        metrics = {}
        cheapest_flights = {}
        is_good_deals = {}

        for destination in destinations:
            try:
                kwargs = {'originLocationCode': origin,
                         'destinationLocationCode': destination,
                         'departureDate': departure_date,
                         'adults': 1,
                         'currencyCode': currency
                         }

                kwargs_metrics = {'originIataCode': origin,
                                'destinationIataCode': destination,
                                'departureDate': departure_date,
                                'currencyCode': currency
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
                        'is_good_deal': is_good_deals.get(destination, 'NO FLIGHTS'),
                        'trip_purpose': trip_purposes.get(destination, '')
                    })

            except ResponseError as error:
                logger.error(f"Amadeus API error for {origin} to {destination}: {error.response.result['errors'][0]['detail']}")
                messages.add_message(request, messages.ERROR, f"Error searching flights from {origin} to {destination}: {error.response.result['errors'][0]['detail']}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error for {origin} to {destination}: {str(e)}")
                messages.add_message(request, messages.ERROR, f"Unexpected error searching flights from {origin} to {destination}")
                continue

        if not all_results:
            messages.error(request, 'No flights found for the given criteria')
            return render(request, 'flight_price/home.html')

        return render(request, 'flight_price/results.html', {
            'all_results': all_results,
            'origin': origin,
            'departure_date': departure_date,
            'return_date': return_date,
            'currency': currency
        })

    except Exception as e:
        logger.error(f"Unexpected error in flight_offers view: {str(e)}")
        messages.error(request, 'An unexpected error occurred. Please try again later.')
        return render(request, 'flight_price/home.html')


def get_flight_offers(**kwargs):
    try:
        logger.info(f"Making Amadeus API request with parameters: {kwargs}")
        search_flights = amadeus.shopping.flight_offers_search.get(**kwargs)
        logger.info(f"Amadeus API response status: {search_flights.status_code}")
        logger.info(f"Number of flights found: {len(search_flights.data) if search_flights.data else 0}")
        
        if not search_flights.data:
            logger.warning("No flight offers found in the response")
            return []
            
        flight_offers = []
        for flight in search_flights.data:
            offer = Flight(flight).construct_flights()
            flight_offers.append(offer)
        return flight_offers
    except Exception as e:
        logger.error(f"Error in get_flight_offers: {str(e)}")
        raise


def get_flight_price_metrics(**kwargs_metrics):
    metrics = amadeus.analytics.itinerary_price_metrics.get(**kwargs_metrics)
    return Metrics(metrics.data).construct_metrics()


def get_trip_purpose(**kwargs_trip_purpose):
    trip_purpose = amadeus.travel.predictions.trip_purpose.get(**kwargs_trip_purpose).data
    return trip_purpose['result']


def get_cheapest_flight_price(flight_offers):
    if not flight_offers:
        return None
    return flight_offers[0]['price']


def rank_cheapest_flight(cheapest_flight_price, first_price, third_price):
    if cheapest_flight_price is None:
        return 'NO FLIGHTS'
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
    if cheapest_flight_price is None:
        return
    min_price = float(metrics['min'])
    max_price = float(metrics['max'])
    cheapest_flight_price_to_number = float(cheapest_flight_price)
    if cheapest_flight_price_to_number < min_price:
        metrics['min'] = cheapest_flight_price
    elif cheapest_flight_price_to_number > max_price:
        metrics['max'] = cheapest_flight_price


def origin_airport_search(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            data = amadeus.reference_data.locations.get(keyword=request.GET.get('term', None),
                                                        subType=Location.ANY).data
            return HttpResponse(get_city_airport_list(data), 'application/json')
        except ResponseError as error:
            messages.add_message(request, messages.ERROR, error.response.result['errors'][0]['detail'])
            return HttpResponse(json.dumps([]), 'application/json')
    return HttpResponse(json.dumps([]), 'application/json')


def destination_airport_search(request):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            data = amadeus.reference_data.locations.get(keyword=request.GET.get('term', None),
                                                        subType=Location.ANY).data
            return HttpResponse(get_city_airport_list(data), 'application/json')
        except ResponseError as error:
            messages.add_message(request, messages.ERROR, error.response.result['errors'][0]['detail'])
            return HttpResponse(json.dumps([]), 'application/json')
    return HttpResponse(json.dumps([]), 'application/json')


def get_city_airport_list(data):
    result = []
    for i, val in enumerate(data):
        result.append({
            'label': f"{data[i]['iataCode']}, {data[i]['name']}",
            'value': data[i]['iataCode']
        })
    result = list({v['value']: v for v in result}.values())  # Remove duplicates based on value
    return json.dumps(result)


def add_south_america_airports(request):
    """Add all major South American airports as destinations"""
    if request.method == 'POST':
        # Major South American airports with their IATA codes and cities
        south_america_airports = [
            {'code': 'GRU', 'name': 'São Paulo–Guarulhos International Airport', 'city': 'São Paulo, Brazil'},
            {'code': 'BOG', 'name': 'El Dorado International Airport', 'city': 'Bogotá, Colombia'},
            {'code': 'LIM', 'name': 'Jorge Chávez International Airport', 'city': 'Lima, Peru'},
            {'code': 'SCL', 'name': 'Arturo Merino Benítez International Airport', 'city': 'Santiago, Chile'},
            {'code': 'CGH', 'name': 'São Paulo–Congonhas Airport', 'city': 'São Paulo, Brazil'},
            {'code': 'BSB', 'name': 'Brasília International Airport', 'city': 'Brasília, Brazil'},
            {'code': 'MDE', 'name': 'José María Córdova International Airport', 'city': 'Medellín, Colombia'},
            {'code': 'AEP', 'name': 'Aeroparque Jorge Newbery', 'city': 'Buenos Aires, Argentina'},
            {'code': 'VCP', 'name': 'Viracopos International Airport', 'city': 'Campinas, Brazil'},
            {'code': 'SDU', 'name': 'Santos Dumont Airport', 'city': 'Rio de Janeiro, Brazil'},
            {'code': 'CNF', 'name': 'Belo Horizonte International Airport', 'city': 'Belo Horizonte, Brazil'},
            {'code': 'REC', 'name': 'Recife/Guararapes–Gilberto Freyre International Airport', 'city': 'Recife, Brazil'},
            {'code': 'CCS', 'name': 'Simón Bolívar International Airport', 'city': 'Caracas, Venezuela'},
            {'code': 'CLO', 'name': 'Alfonso Bonilla Aragón International Airport', 'city': 'Cali, Colombia'},
            {'code': 'CTG', 'name': 'Rafael Núñez International Airport', 'city': 'Cartagena, Colombia'},
            {'code': 'POA', 'name': 'Salgado Filho Porto Alegre International Airport', 'city': 'Porto Alegre, Brazil'},
            {'code': 'EZE', 'name': 'Ministro Pistarini International Airport', 'city': 'Buenos Aires, Argentina'},
            {'code': 'GIG', 'name': 'Rio de Janeiro/Galeão International Airport', 'city': 'Rio de Janeiro, Brazil'},
            {'code': 'FOR', 'name': 'Fortaleza Airport', 'city': 'Fortaleza, Brazil'},
            {'code': 'SSA', 'name': 'Salvador International Airport', 'city': 'Salvador, Brazil'},
            {'code': 'CWB', 'name': 'Afonso Pena International Airport', 'city': 'Curitiba, Brazil'},
            {'code': 'BEL', 'name': 'Belém/Val-de-Cans International Airport', 'city': 'Belém, Brazil'},
            {'code': 'FLN', 'name': 'Hercílio Luz International Airport', 'city': 'Florianópolis, Brazil'},
            {'code': 'MAO', 'name': 'Eduardo Gomes International Airport', 'city': 'Manaus, Brazil'},
            {'code': 'UIO', 'name': 'Mariscal Sucre International Airport', 'city': 'Quito, Ecuador'},
            {'code': 'GYE', 'name': 'José Joaquín de Olmedo International Airport', 'city': 'Guayaquil, Ecuador'},
            {'code': 'CUZ', 'name': 'Alejandro Velasco Astete International Airport', 'city': 'Cusco, Peru'},
            {'code': 'VIX', 'name': 'Eurico de Aguiar Salles Airport', 'city': 'Vitória, Brazil'},
            {'code': 'MVD', 'name': 'Carrasco International Airport', 'city': 'Montevideo, Uruguay'},
            {'code': 'ASU', 'name': 'Silvio Pettirossi International Airport', 'city': 'Asunción, Paraguay'},
            {'code': 'GEO', 'name': 'Cheddi Jagan International Airport', 'city': 'Georgetown, Guyana'},
            {'code': 'PBM', 'name': 'Johan Adolf Pengel International Airport', 'city': 'Paramaribo, Suriname'},
            {'code': 'POS', 'name': 'Piarco International Airport', 'city': 'Port of Spain, Trinidad and Tobago'},
            {'code': 'CAY', 'name': 'Cayenne – Félix Eboué Airport', 'city': 'Cayenne, French Guiana'},
            {'code': 'LPB', 'name': 'El Alto International Airport', 'city': 'La Paz, Bolivia'},
            {'code': 'VVI', 'name': 'Viru Viru International Airport', 'city': 'Santa Cruz, Bolivia'},
            {'code': 'CBB', 'name': 'Jorge Wilstermann Airfield', 'city': 'Cochabamba, Bolivia'},
        ]
        
        # Create a JSON response with the airport data for the frontend
        return HttpResponse(json.dumps({
            'success': True,
            'airports': south_america_airports,
            'message': f'Added {len(south_america_airports)} South American airports as destinations'
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')
