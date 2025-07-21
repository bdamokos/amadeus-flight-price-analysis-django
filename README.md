# Flight Search and AI APIs showcase

## What is this?

This prototype retrieves flight offers using the [Flight Offers Search API](https://developers.amadeus.com/self-service/category/air/api-doc/flight-offers-search) for a given itinerary. Then it displays if the cheapest available flight is a good deal based on the [Flight Price Analysis API](https://developers.amadeus.com/self-service/category/air/api-doc/flight-price-analysis). 
We finally predict if the trip is for business or leisure using the [Trip Purpose Prediction API](https://developers.amadeus.com/self-service/category/trip/api-doc/trip-purpose-prediction).

![title](pricing/flight_price/static/images/demo.png)

## How to run the project via Docker (recommended)

Build the image from the Dockerfile. The following command will 

```sh
make
```

The container receives your API key/secret from the environment variables.
Before running the container, make sure your have your credentials correctly
set:

```sh
export AMADEUS_CLIENT_ID=YOUR_API_KEY
export AMADEUS_CLIENT_SECRET=YOUR_API_SECRET
export AMADEUS_HOSTNAME="test" or "production"
export DEBUG_VALUE="True"
```

Finally, start the container from the image:

```
make run
```

At this point you can open a browser and go to `https://0.0.0.0:8000`.

Note that it is also possible to run in detached mode so your terminal is still
usable:

```
make start
```

Stop the container with:

```
make stop
```

## How to run the project locally

Clone the repository.

```sh
git clone https://github.com/amadeus4dev/amadeus-flight-price-analysis-django.git
cd flight-price-analysis
```

Next create a virtual environment and install the dependencies.

```sh
virtualenv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables Setup

The application now supports automatic loading of environment variables from a `.env` file. This is the recommended approach for local development.

1. Copy the example environment file:
```sh
cp env.example .env
```

2. Edit the `.env` file with your actual Amadeus API credentials:
```sh
# Get your API credentials from https://developers.amadeus.com/
AMADEUS_CLIENT_ID=your_actual_api_key
AMADEUS_CLIENT_SECRET=your_actual_api_secret
AMADEUS_HOSTNAME=test  # or "production"
DEBUG_VALUE=True
```

Alternatively, you can still set environment variables manually:

```sh
export AMADEUS_CLIENT_ID=YOUR_API_KEY
export AMADEUS_CLIENT_SECRET=YOUR_API_SECRET
```

You can easily switch between `test` and `production` environments by setting:

```
export AMADEUS_HOSTNAME="test" # an empty value will also set the environment to test
```

or

```
export AMADEUS_HOSTNAME="production"
```

> Each environment has different API keys. Do not forget to update them!

Finally, run the Django server.

```sh
python pricing/manage.py runserver
```

Finally, open a browser and go to `http://127.0.0.1:8000/`

## Fork Enhancements

This fork extends the original flight price analysis application with several key enhancements focused on multi-destination and multi-origin search capabilities:

### Multi-City Search Functionality
- **Multiple Destinations Mode**: Search flights from one origin to multiple destinations simultaneously
- **Multiple Origins Mode**: Search flights from multiple origins to one destination
- **Dynamic UI**: Toggle between search modes with an intuitive interface that adapts based on your selection

### Continental Airport Integration
- **Quick Add by Continent**: One-click buttons to add all major airports from:
  - 🌎 South America (37+ airports)
  - 🇪🇺 Europe (20+ airports)  
  - 🌏 Asia (20+ airports)
  - 🌎 North America (20+ airports)
  - 🌍 Africa (20+ airports)
  - 🌏 Oceania (20+ airports)


### Enhanced User Experience
- **Currency Support**: Multiple currency options (USD, EUR) with proper price display

### Advanced Results Display
- **Country-Based Grouping**: Results organized by destination/origin countries with price ranges
- **Price Comparison**: Clear visualization of cheapest flights across multiple destinations/origins
- **Summary Views**: Comprehensive overviews when searching multiple locations

These enhancements make the application particularly useful for travelers comparing flights across multiple destinations (like exploring South America) or finding the best departure city for a specific destination.

## License

This library is released under the [MIT License](LICENSE).

## Help

You can find us on [StackOverflow](https://stackoverflow.com/questions/tagged/amadeus) or join our developer community on
[Discord](https://discord.gg/cVrFBqx).

