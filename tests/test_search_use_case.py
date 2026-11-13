import json
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

from my_package.application.ports import Geocoder, PlaceSource
from my_package.application.search import SearchPlaces
from my_package.domain.errors import GeocodingError, OverpassError
from my_package.domain.models import Coordinates, Place, SearchRequest
from my_package.infrastructure.geocoding import NominatimGeocoder
from my_package.services.scrap import ScrapService


class SearchUseCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.geocoder = Mock(spec=Geocoder)
        self.source = Mock(spec=PlaceSource)
        self.source.search.return_value = []
        self.use_case = SearchPlaces(self.geocoder, self.source)

    def test_coordinate_search_skips_geocoding(self) -> None:
        request = SearchRequest("49,24", "cafe", 2000)
        self.assertEqual(self.use_case.execute(request), [])
        self.geocoder.geocode.assert_not_called()
        self.source.search.assert_called_once_with(request, Coordinates(49, 24))

    def test_city_search_uses_geocoded_center(self) -> None:
        request = SearchRequest(" Lviv, Ukraine ", "cafe", 2000)
        center = Coordinates(49.84, 24.03)
        self.geocoder.geocode.return_value = center
        self.use_case.execute(request)
        self.geocoder.geocode.assert_called_once_with("Lviv, Ukraine")
        self.source.search.assert_called_once_with(request, center)

    def test_filter_preserves_source_results(self) -> None:
        places = [
            Place("node/1", "Lviv coffee", 49, 24),
            Place("way/2", None, None, None),
        ]
        self.source.search.return_value = places
        result = self.use_case.execute(SearchRequest("49,24", "cafe", 1, " LVIV "))
        self.assertEqual(result[0].osm_id, places[0].osm_id)
        self.assertEqual(result[0].distance_m, 0)
        self.assertIsNone(places[0].distance_m)
        self.assertEqual(len(places), 2)

    def test_geocoder_failure_stops_before_place_search(self) -> None:
        error = GeocodingError("Unavailable")
        self.geocoder.geocode.side_effect = error
        with self.assertRaises(GeocodingError) as raised:
            self.use_case.execute(SearchRequest("Lviv", "cafe", 1))
        self.assertIs(raised.exception, error)
        self.source.search.assert_not_called()

    def test_source_failure_is_not_an_empty_result(self) -> None:
        error = OverpassError("Unavailable")
        self.source.search.side_effect = error
        with self.assertRaises(OverpassError) as raised:
            self.use_case.execute(SearchRequest("49,24", "cafe", 1))
        self.assertIs(raised.exception, error)

    def test_facade_supports_injected_ports_without_concrete_clients(self) -> None:
        with (
            patch("my_package.services.scrap.NominatimGeocoder") as geocoder_factory,
            patch("my_package.services.scrap.OverpassPlaceSource") as source_factory,
        ):
            service = ScrapService(geocoder=self.geocoder, place_source=self.source)
            self.source.search.return_value = [Place("node/1", "Coffee", 49, 24)]
            result = json.loads(service.search("49,24", "cafe", 1))
        self.assertEqual(result[0]["name"], "Coffee")
        self.assertIsNone(result[0]["website"])
        geocoder_factory.assert_not_called()
        source_factory.assert_not_called()

    def test_invalid_request_does_not_reach_either_port(self) -> None:
        service = ScrapService(geocoder=self.geocoder, place_source=self.source)
        with self.assertRaises(ValueError):
            service.search("Lviv", "cafe", 0)
        self.source.search.assert_not_called()
        self.geocoder.geocode.assert_not_called()


class DomainModelTests(unittest.TestCase):
    def test_models_are_immutable(self) -> None:
        for model, attribute in (
            (Coordinates(49, 24), "latitude"),
            (SearchRequest("49,24", "cafe", 1), "radius_m"),
            (Place("node/1", None, None, None), "name"),
        ):
            with self.subTest(model=model):
                with self.assertRaises(FrozenInstanceError):
                    setattr(model, attribute, None)

    def test_coordinate_value_object_rejects_invalid_values(self) -> None:
        for latitude, longitude in (
            (True, 24),
            (49, None),
            ("49", 24),
            (float("nan"), 24),
            (49, float("inf")),
            (-91, 24),
            (49, -181),
        ):
            with self.subTest(latitude=latitude, longitude=longitude):
                with self.assertRaises(ValueError):
                    Coordinates(latitude, longitude)

    def test_request_normalizes_categories_and_deduplicates_tags(self) -> None:
        request = SearchRequest("49,24", " CAFE, coffee shop, Supermarket ", 1)
        self.assertEqual(request.tags, (("amenity", "cafe"), ("shop", "supermarket")))
        self.assertEqual(request.origin, Coordinates(49, 24))

    def test_invalid_geocoder_coordinates_are_provider_errors(self) -> None:
        with patch("my_package.infrastructure.geocoding.Nominatim") as geocoder:
            geocoder.return_value.geocode.return_value = Mock(latitude=91, longitude=24)
            with self.assertRaises(GeocodingError) as raised:
                NominatimGeocoder().geocode("Lviv")
        self.assertIsInstance(raised.exception.__cause__, ValueError)
