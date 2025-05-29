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
        search_mode = request.POST.get('search_mode', 'destinations')
        origins = request.POST.getlist('Origin')
        destinations = request.POST.getlist('Destination')
        departure_date = request.POST.get('Departuredate')
        return_date = request.POST.get('Returndate')
        currency = request.POST.get('Currency', 'USD')  # Default to USD if not specified

        logger.info(f"Flight search request - Mode: {search_mode}, Origins: {origins}, Destinations: {destinations}, Departure: {departure_date}, Return: {return_date}")

        # Validate inputs based on mode
        if search_mode == 'destinations':
            # Multiple destinations mode: 1 origin, multiple destinations
            if not origins or len(origins) != 1 or not destinations:
                messages.error(request, 'Please provide one origin and at least one destination')
                return render(request, 'flight_price/home.html')
            origin = origins[0]
            search_list = destinations
            search_type = 'destination'
        else:
            # Multiple origins mode: multiple origins, 1 destination
            if not destinations or len(destinations) != 1 or not origins:
                messages.error(request, 'Please provide multiple origins and one destination')
                return render(request, 'flight_price/home.html')
            destination = destinations[0]
            search_list = origins
            search_type = 'origin'

        if not departure_date:
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'flight_price/home.html')

        all_results = []
        trip_purposes = {}
        metrics = {}
        cheapest_flights = {}
        is_good_deals = {}

        for search_item in search_list:
            try:
                # Set up origin and destination based on mode
                if search_mode == 'destinations':
                    current_origin = origin
                    current_destination = search_item
                else:
                    current_origin = search_item
                    current_destination = destination

                kwargs = {'originLocationCode': current_origin,
                         'destinationLocationCode': current_destination,
                         'departureDate': departure_date,
                         'adults': 1,
                         'currencyCode': currency
                         }

                kwargs_metrics = {'originIataCode': current_origin,
                                'destinationIataCode': current_destination,
                                'departureDate': departure_date,
                                'currencyCode': currency
                                }

                if return_date:
                    kwargs['returnDate'] = return_date
                    kwargs_trip_purpose = {'originLocationCode': current_origin,
                                         'destinationLocationCode': current_destination,
                                         'departureDate': departure_date,
                                         'returnDate': return_date
                                         }
                    trip_purposes[search_item] = get_trip_purpose(**kwargs_trip_purpose)
                else:
                    kwargs_metrics['oneWay'] = 'true'

                flight_offers = get_flight_offers(**kwargs)
                metrics[search_item] = get_flight_price_metrics(**kwargs_metrics)
                cheapest_flights[search_item] = get_cheapest_flight_price(flight_offers)
                
                if metrics[search_item] is not None:
                    is_good_deals[search_item] = rank_cheapest_flight(
                        cheapest_flights[search_item], 
                        metrics[search_item]['first'], 
                        metrics[search_item]['third']
                    )
                    is_cheapest_flight_out_of_range(cheapest_flights[search_item], metrics[search_item])

                # Store result with consistent structure
                if search_mode == 'destinations':
                    all_results.append({
                        'flight_offers': flight_offers,
                        'origin': current_origin,
                        'origin_name': get_airport_name(current_origin),
                        'destination': current_destination,
                        'destination_name': get_airport_name(current_destination),
                        'metrics': metrics[search_item],
                        'cheapest_flight': cheapest_flights[search_item],
                        'is_good_deal': is_good_deals.get(search_item, 'NO FLIGHTS'),
                        'trip_purpose': trip_purposes.get(search_item, '')
                    })
                else:
                    all_results.append({
                        'flight_offers': flight_offers,
                        'origin': current_origin,
                        'origin_name': get_airport_name(current_origin),
                        'destination': current_destination,
                        'destination_name': get_airport_name(current_destination),
                        'metrics': metrics[search_item],
                        'cheapest_flight': cheapest_flights[search_item],
                        'is_good_deal': is_good_deals.get(search_item, 'NO FLIGHTS'),
                        'trip_purpose': trip_purposes.get(search_item, '')
                    })

            except ResponseError as error:
                logger.error(f"Amadeus API error for {current_origin} to {current_destination}: {error.response.result['errors'][0]['detail']}")
                messages.add_message(request, messages.ERROR, f"Error searching flights from {current_origin} to {current_destination}: {error.response.result['errors'][0]['detail']}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error for {current_origin} to {current_destination}: {str(e)}")
                messages.add_message(request, messages.ERROR, f"Unexpected error searching flights from {current_origin} to {current_destination}")
                continue

        if not all_results:
            messages.error(request, 'No flights found for the given criteria')
            return render(request, 'flight_price/home.html')

        # Create summary based on mode
        if search_mode == 'destinations':
            summary = create_country_summary(all_results) if len(all_results) > 1 else None
            single_origin = origins[0]
            single_origin_name = get_airport_name(single_origin)
            single_destination = None
            single_destination_name = None
        else:
            summary = create_origin_summary(all_results) if len(all_results) > 1 else None
            single_origin = None
            single_origin_name = None
            single_destination = destinations[0]
            single_destination_name = get_airport_name(single_destination)

        return render(request, 'flight_price/results.html', {
            'all_results': all_results,
            'country_summary': summary,  # This name is kept for template compatibility
            'search_mode': search_mode,
            'single_origin': single_origin,
            'single_origin_name': single_origin_name,
            'single_destination': single_destination,
            'single_destination_name': single_destination_name,
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
    """Add all major South American airports as destinations or origins"""
    if request.method == 'POST':
        mode = request.POST.get('mode', 'destinations')  # Default to destinations for backward compatibility
        
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
        
        # Adjust message based on mode
        airport_type = 'destinations' if mode == 'destinations' else 'origins'
        message = f'Added {len(south_america_airports)} South American airports as {airport_type}'
        
        # Create a JSON response with the airport data for the frontend
        return HttpResponse(json.dumps({
            'success': True,
            'airports': south_america_airports,
            'message': message
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')


def get_airport_name(iata_code):
    """Get airport name with country from IATA code using Amadeus API"""
    try:
        if not iata_code:
            return iata_code
        
        # Use the same API endpoint as the search functions
        data = amadeus.reference_data.locations.get(keyword=iata_code, subType=Location.ANY).data
        
        # Find exact match for the IATA code
        for location in data:
            if location.get('iataCode') == iata_code:
                name = location.get('name', iata_code)
                # Try to get country information
                address = location.get('address', {})
                country = address.get('countryName', '')
                city = address.get('cityName', '')
                
                # Format: "Airport Name, City, Country" or just "Airport Name" if no additional info
                if country and city:
                    return f"{name}, {city}, {country}"
                elif country:
                    return f"{name}, {country}"
                elif city:
                    return f"{name}, {city}"
                else:
                    return name
        
        # If no exact match found, return the original code
        return iata_code
    except Exception as e:
        logger.warning(f"Could not get airport name for {iata_code}: {str(e)}")
        return iata_code


def extract_country_from_airport_name(airport_name):
    """Extract country name from airport name string"""
    # Airport names are formatted as "Airport Name, City, Country" or "Airport Name, Country"
    if ',' in airport_name:
        parts = airport_name.split(',')
        if len(parts) >= 2:
            # Last part should be the country
            country = parts[-1].strip()
            return country
    return "Unknown"


def create_origin_summary(all_results):
    """Create a summary of flight results grouped by origin country with price ranges"""
    country_data = {}
    
    for result in all_results:
        if not result['flight_offers']:
            continue
            
        # Extract country from origin name
        country = extract_country_from_airport_name(result['origin_name'])
        
        # Get all prices for this origin
        prices = []
        for flight in result['flight_offers']:
            try:
                price = float(flight['price'])
                prices.append(price)
            except (ValueError, KeyError):
                continue
        
        if not prices:
            continue
            
        # Initialize country entry if not exists
        if country not in country_data:
            country_data[country] = {
                'country': country,
                'airports': [],
                'min_price': float('inf'),
                'max_price': 0
            }
        
        # Add airport data
        airport_info = {
            'code': result['origin'],
            'name': result['origin_name'],
            'min_price': min(prices),
            'max_price': max(prices),
            'flight_count': len(prices)
        }
        
        country_data[country]['airports'].append(airport_info)
        
        # Update country min/max prices
        country_data[country]['min_price'] = min(country_data[country]['min_price'], min(prices))
        country_data[country]['max_price'] = max(country_data[country]['max_price'], max(prices))
    
    # Convert to list and sort by minimum price
    country_summary = list(country_data.values())
    
    # Sort countries by minimum price
    country_summary.sort(key=lambda x: x['min_price'])
    
    # Sort airports within each country by minimum price
    for country in country_summary:
        country['airports'].sort(key=lambda x: x['min_price'])
    
    return country_summary


def create_country_summary(all_results):
    """Create a summary of flight results grouped by country with price ranges"""
    country_data = {}
    
    for result in all_results:
        if not result['flight_offers']:
            continue
            
        # Extract country from destination name
        country = extract_country_from_airport_name(result['destination_name'])
        
        # Get all prices for this destination
        prices = []
        for flight in result['flight_offers']:
            try:
                price = float(flight['price'])
                prices.append(price)
            except (ValueError, KeyError):
                continue
        
        if not prices:
            continue
            
        # Initialize country entry if not exists
        if country not in country_data:
            country_data[country] = {
                'country': country,
                'airports': [],
                'min_price': float('inf'),
                'max_price': 0
            }
        
        # Add airport data
        airport_info = {
            'code': result['destination'],
            'name': result['destination_name'],
            'min_price': min(prices),
            'max_price': max(prices),
            'flight_count': len(prices)
        }
        
        country_data[country]['airports'].append(airport_info)
        
        # Update country min/max prices
        country_data[country]['min_price'] = min(country_data[country]['min_price'], min(prices))
        country_data[country]['max_price'] = max(country_data[country]['max_price'], max(prices))
    
    # Convert to list and sort by minimum price
    country_summary = list(country_data.values())
    
    # Sort countries by minimum price
    country_summary.sort(key=lambda x: x['min_price'])
    
    # Sort airports within each country by minimum price
    for country in country_summary:
        country['airports'].sort(key=lambda x: x['min_price'])
    
    return country_summary


def add_europe_airports(request):
    """Add all major European airports as destinations or origins"""
    if request.method == 'POST':
        mode = request.POST.get('mode', 'destinations')  # Default to destinations for backward compatibility
        
        europe_airports = [
            {'code': 'LHR', 'name': 'Heathrow Airport', 'city': 'London, United Kingdom'},
            {'code': 'CDG', 'name': 'Charles de Gaulle Airport', 'city': 'Paris, France'},
            {'code': 'FRA', 'name': 'Frankfurt Airport', 'city': 'Frankfurt, Germany'},
            {'code': 'AMS', 'name': 'Amsterdam Airport Schiphol', 'city': 'Amsterdam, Netherlands'},
            {'code': 'MAD', 'name': 'Adolfo Suárez Madrid–Barajas Airport', 'city': 'Madrid, Spain'},
            {'code': 'BCN', 'name': 'Barcelona–El Prat Airport', 'city': 'Barcelona, Spain'},
            {'code': 'FCO', 'name': 'Leonardo da Vinci International Airport', 'city': 'Rome, Italy'},
            {'code': 'MUC', 'name': 'Munich Airport', 'city': 'Munich, Germany'},
            {'code': 'ZUR', 'name': 'Zurich Airport', 'city': 'Zurich, Switzerland'},
            {'code': 'VIE', 'name': 'Vienna International Airport', 'city': 'Vienna, Austria'},
            {'code': 'CPH', 'name': 'Copenhagen Airport', 'city': 'Copenhagen, Denmark'},
            {'code': 'ARN', 'name': 'Stockholm Arlanda Airport', 'city': 'Stockholm, Sweden'},
            {'code': 'OSL', 'name': 'Oslo Airport', 'city': 'Oslo, Norway'},
            {'code': 'HEL', 'name': 'Helsinki Airport', 'city': 'Helsinki, Finland'},
            {'code': 'LIS', 'name': 'Humberto Delgado Airport', 'city': 'Lisbon, Portugal'},
            {'code': 'WAW', 'name': 'Warsaw Chopin Airport', 'city': 'Warsaw, Poland'},
            {'code': 'PRG', 'name': 'Václav Havel Airport Prague', 'city': 'Prague, Czech Republic'},
            {'code': 'BUD', 'name': 'Budapest Ferenc Liszt International Airport', 'city': 'Budapest, Hungary'},
            {'code': 'ATH', 'name': 'Athens International Airport', 'city': 'Athens, Greece'},
            {'code': 'IST', 'name': 'Istanbul Airport', 'city': 'Istanbul, Turkey'},
        ]
        
        airport_type = 'destinations' if mode == 'destinations' else 'origins'
        message = f'Added {len(europe_airports)} European airports as {airport_type}'
        
        return HttpResponse(json.dumps({
            'success': True,
            'airports': europe_airports,
            'message': message
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')


def add_asia_airports(request):
    """Add all major Asian airports as destinations or origins"""
    if request.method == 'POST':
        mode = request.POST.get('mode', 'destinations')  # Default to destinations for backward compatibility
        
        asia_airports = [
            {'code': 'NRT', 'name': 'Narita International Airport', 'city': 'Tokyo, Japan'},
            {'code': 'HND', 'name': 'Haneda Airport', 'city': 'Tokyo, Japan'},
            {'code': 'ICN', 'name': 'Incheon International Airport', 'city': 'Seoul, South Korea'},
            {'code': 'PEK', 'name': 'Beijing Capital International Airport', 'city': 'Beijing, China'},
            {'code': 'PVG', 'name': 'Shanghai Pudong International Airport', 'city': 'Shanghai, China'},
            {'code': 'HKG', 'name': 'Hong Kong International Airport', 'city': 'Hong Kong'},
            {'code': 'SIN', 'name': 'Singapore Changi Airport', 'city': 'Singapore'},
            {'code': 'BKK', 'name': 'Suvarnabhumi Airport', 'city': 'Bangkok, Thailand'},
            {'code': 'KUL', 'name': 'Kuala Lumpur International Airport', 'city': 'Kuala Lumpur, Malaysia'},
            {'code': 'CGK', 'name': 'Soekarno–Hatta International Airport', 'city': 'Jakarta, Indonesia'},
            {'code': 'MNL', 'name': 'Ninoy Aquino International Airport', 'city': 'Manila, Philippines'},
            {'code': 'TPE', 'name': 'Taiwan Taoyuan International Airport', 'city': 'Taipei, Taiwan'},
            {'code': 'BOM', 'name': 'Chhatrapati Shivaji Maharaj International Airport', 'city': 'Mumbai, India'},
            {'code': 'DEL', 'name': 'Indira Gandhi International Airport', 'city': 'New Delhi, India'},
            {'code': 'DXB', 'name': 'Dubai International Airport', 'city': 'Dubai, UAE'},
            {'code': 'DOH', 'name': 'Hamad International Airport', 'city': 'Doha, Qatar'},
            {'code': 'KWI', 'name': 'Kuwait International Airport', 'city': 'Kuwait City, Kuwait'},
            {'code': 'RUH', 'name': 'King Khalid International Airport', 'city': 'Riyadh, Saudi Arabia'},
            {'code': 'TLV', 'name': 'Ben Gurion Airport', 'city': 'Tel Aviv, Israel'},
            {'code': 'BAH', 'name': 'Bahrain International Airport', 'city': 'Manama, Bahrain'},
        ]
        
        airport_type = 'destinations' if mode == 'destinations' else 'origins'
        message = f'Added {len(asia_airports)} Asian airports as {airport_type}'
        
        return HttpResponse(json.dumps({
            'success': True,
            'airports': asia_airports,
            'message': message
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')


def add_north_america_airports(request):
    """Add all major North American airports as destinations or origins"""
    if request.method == 'POST':
        mode = request.POST.get('mode', 'destinations')  # Default to destinations for backward compatibility
        
        north_america_airports = [
            {'code': 'JFK', 'name': 'John F. Kennedy International Airport', 'city': 'New York, USA'},
            {'code': 'LAX', 'name': 'Los Angeles International Airport', 'city': 'Los Angeles, USA'},
            {'code': 'ORD', 'name': "O'Hare International Airport", 'city': 'Chicago, USA'},
            {'code': 'DFW', 'name': 'Dallas/Fort Worth International Airport', 'city': 'Dallas, USA'},
            {'code': 'ATL', 'name': 'Hartsfield-Jackson Atlanta International Airport', 'city': 'Atlanta, USA'},
            {'code': 'MIA', 'name': 'Miami International Airport', 'city': 'Miami, USA'},
            {'code': 'SEA', 'name': 'Seattle–Tacoma International Airport', 'city': 'Seattle, USA'},
            {'code': 'SFO', 'name': 'San Francisco International Airport', 'city': 'San Francisco, USA'},
            {'code': 'LAS', 'name': 'McCarran International Airport', 'city': 'Las Vegas, USA'},
            {'code': 'YYZ', 'name': 'Toronto Pearson International Airport', 'city': 'Toronto, Canada'},
            {'code': 'YVR', 'name': 'Vancouver International Airport', 'city': 'Vancouver, Canada'},
            {'code': 'YUL', 'name': 'Montréal–Pierre Elliott Trudeau International Airport', 'city': 'Montreal, Canada'},
            {'code': 'MEX', 'name': 'Mexico City International Airport', 'city': 'Mexico City, Mexico'},
            {'code': 'CUN', 'name': 'Cancún International Airport', 'city': 'Cancún, Mexico'},
            {'code': 'GDL', 'name': 'Miguel Hidalgo y Costilla Guadalajara International Airport', 'city': 'Guadalajara, Mexico'},
            {'code': 'HAV', 'name': 'José Martí International Airport', 'city': 'Havana, Cuba'},
            {'code': 'SJU', 'name': 'Luis Muñoz Marín International Airport', 'city': 'San Juan, Puerto Rico'},
            {'code': 'GUA', 'name': 'La Aurora International Airport', 'city': 'Guatemala City, Guatemala'},
            {'code': 'SJO', 'name': 'Juan Santamaría International Airport', 'city': 'San José, Costa Rica'},
            {'code': 'PTY', 'name': 'Tocumen International Airport', 'city': 'Panama City, Panama'},
        ]
        
        airport_type = 'destinations' if mode == 'destinations' else 'origins'
        message = f'Added {len(north_america_airports)} North American airports as {airport_type}'
        
        return HttpResponse(json.dumps({
            'success': True,
            'airports': north_america_airports,
            'message': message
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')


def add_africa_airports(request):
    """Add all major African airports as destinations or origins"""
    if request.method == 'POST':
        mode = request.POST.get('mode', 'destinations')  # Default to destinations for backward compatibility
        
        africa_airports = [
            {'code': 'CAI', 'name': 'Cairo International Airport', 'city': 'Cairo, Egypt'},
            {'code': 'CPT', 'name': 'Cape Town International Airport', 'city': 'Cape Town, South Africa'},
            {'code': 'JNB', 'name': 'O.R. Tambo International Airport', 'city': 'Johannesburg, South Africa'},
            {'code': 'LOS', 'name': 'Murtala Muhammed International Airport', 'city': 'Lagos, Nigeria'},
            {'code': 'ABV', 'name': 'Nnamdi Azikiwe International Airport', 'city': 'Abuja, Nigeria'},
            {'code': 'CMN', 'name': 'Mohammed V International Airport', 'city': 'Casablanca, Morocco'},
            {'code': 'ALG', 'name': 'Houari Boumediene Airport', 'city': 'Algiers, Algeria'},
            {'code': 'TUN', 'name': 'Tunis Carthage International Airport', 'city': 'Tunis, Tunisia'},
            {'code': 'ACC', 'name': 'Kotoka International Airport', 'city': 'Accra, Ghana'},
            {'code': 'ADD', 'name': 'Addis Ababa Bole International Airport', 'city': 'Addis Ababa, Ethiopia'},
            {'code': 'NBO', 'name': 'Jomo Kenyatta International Airport', 'city': 'Nairobi, Kenya'},
            {'code': 'DAR', 'name': 'Julius Nyerere International Airport', 'city': 'Dar es Salaam, Tanzania'},
            {'code': 'EBB', 'name': 'Entebbe International Airport', 'city': 'Entebbe, Uganda'},
            {'code': 'KGL', 'name': 'Kigali International Airport', 'city': 'Kigali, Rwanda'},
            {'code': 'LUN', 'name': 'Kenneth Kaunda International Airport', 'city': 'Lusaka, Zambia'},
            {'code': 'HRE', 'name': 'Robert Gabriel Mugabe International Airport', 'city': 'Harare, Zimbabwe'},
            {'code': 'GBE', 'name': 'Sir Seretse Khama International Airport', 'city': 'Gaborone, Botswana'},
            {'code': 'WDH', 'name': 'Hosea Kutako International Airport', 'city': 'Windhoek, Namibia'},
            {'code': 'MRU', 'name': 'Sir Seewoosagur Ramgoolam International Airport', 'city': 'Mauritius'},
            {'code': 'SEZ', 'name': 'Seychelles International Airport', 'city': 'Victoria, Seychelles'},
        ]
        
        airport_type = 'destinations' if mode == 'destinations' else 'origins'
        message = f'Added {len(africa_airports)} African airports as {airport_type}'
        
        return HttpResponse(json.dumps({
            'success': True,
            'airports': africa_airports,
            'message': message
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')


def add_oceania_airports(request):
    """Add all major Oceania airports as destinations or origins"""
    if request.method == 'POST':
        mode = request.POST.get('mode', 'destinations')  # Default to destinations for backward compatibility
        
        oceania_airports = [
            {'code': 'SYD', 'name': 'Kingsford Smith Airport', 'city': 'Sydney, Australia'},
            {'code': 'MEL', 'name': 'Melbourne Airport', 'city': 'Melbourne, Australia'},
            {'code': 'BNE', 'name': 'Brisbane Airport', 'city': 'Brisbane, Australia'},
            {'code': 'PER', 'name': 'Perth Airport', 'city': 'Perth, Australia'},
            {'code': 'ADL', 'name': 'Adelaide Airport', 'city': 'Adelaide, Australia'},
            {'code': 'DRW', 'name': 'Darwin Airport', 'city': 'Darwin, Australia'},
            {'code': 'HBA', 'name': 'Hobart Airport', 'city': 'Hobart, Australia'},
            {'code': 'CNS', 'name': 'Cairns Airport', 'city': 'Cairns, Australia'},
            {'code': 'OOL', 'name': 'Gold Coast Airport', 'city': 'Gold Coast, Australia'},
            {'code': 'AKL', 'name': 'Auckland Airport', 'city': 'Auckland, New Zealand'},
            {'code': 'CHC', 'name': 'Christchurch Airport', 'city': 'Christchurch, New Zealand'},
            {'code': 'WLG', 'name': 'Wellington Airport', 'city': 'Wellington, New Zealand'},
            {'code': 'ZQN', 'name': 'Queenstown Airport', 'city': 'Queenstown, New Zealand'},
            {'code': 'NAN', 'name': 'Nadi International Airport', 'city': 'Nadi, Fiji'},
            {'code': 'SUV', 'name': 'Nausori Airport', 'city': 'Suva, Fiji'},
            {'code': 'PPT', 'name': 'Faa\'a International Airport', 'city': 'Tahiti, French Polynesia'},
            {'code': 'HNL', 'name': 'Daniel K. Inouye International Airport', 'city': 'Honolulu, Hawaii, USA'},
            {'code': 'GUM', 'name': 'Antonio B. Won Pat International Airport', 'city': 'Guam'},
            {'code': 'NOU', 'name': 'La Tontouta International Airport', 'city': 'Nouméa, New Caledonia'},
            {'code': 'VLI', 'name': 'Bauerfield International Airport', 'city': 'Port Vila, Vanuatu'},
        ]
        
        airport_type = 'destinations' if mode == 'destinations' else 'origins'
        message = f'Added {len(oceania_airports)} Oceania airports as {airport_type}'
        
        return HttpResponse(json.dumps({
            'success': True,
            'airports': oceania_airports,
            'message': message
        }), 'application/json')
    
    return HttpResponse(json.dumps({'success': False, 'message': 'Invalid request method'}), 'application/json')
