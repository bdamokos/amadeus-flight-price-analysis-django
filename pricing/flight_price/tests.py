from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from . import views


class DjangoCompatibilityTests(SimpleTestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse('flight_offers'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'flight_price/home.html')

    @patch('flight_price.views.get_flight_offers')
    def test_invalid_search_does_not_call_amadeus(self, get_flight_offers):
        response = self.client.post(
            reverse('flight_offers'),
            {
                'search_mode': 'destinations',
                'Origin': 'BRU',
                'Departuredate': '2026-09-01',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Please provide one origin and at least one destination',
        )
        get_flight_offers.assert_not_called()


class AmadeusCompatibilityTests(SimpleTestCase):
    def test_application_api_resources_remain_available(self):
        getters = (
            views.amadeus.shopping.flight_offers_search.get,
            views.amadeus.analytics.itinerary_price_metrics.get,
            views.amadeus.travel.predictions.trip_purpose.get,
            views.amadeus.reference_data.locations.get,
        )

        self.assertTrue(all(callable(getter) for getter in getters))
