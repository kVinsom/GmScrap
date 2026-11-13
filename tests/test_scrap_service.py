import json
import unittest
from unittest.mock import Mock, patch

import requests
from geopy.exc import ConfigurationError, GeocoderTimedOut

from my_package.main import main
from my_package.services.scrap import GeocodingError, OverpassError, ScrapService


class ScrapServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(
            patch(
                "my_package.infrastructure.website.WebsiteContactEnricher._fetch",
                return_value=None,
            )
        )
        self.service = ScrapService()
        self.post_patch = patch("my_package.infrastructure.overpass.requests.post")
        self.post = self.post_patch.start()
        self.addCleanup(self.post_patch.stop)
        self.response = self.post.return_value
        self.response.json.return_value = {"elements": []}

    def test_known_coordinates_query_and_empty_success(self) -> None:
        with patch("my_package.infrastructure.geocoding.Nominatim") as geocoder:
            result = self.service.search("49.8419, 24.0315", "coffee shop", 2000)
        self.assertEqual(json.loads(result), [])
        geocoder.assert_not_called()
        self.assertEqual(
            self.post.call_args.kwargs["data"]["data"],
            "[out:json][timeout:25];\n"
            'nwr["amenity"="cafe"](around:2000,49.8419,24.0315);\nout center;',
        )
        self.assertEqual(self.post.call_args.kwargs["timeout"], (10, 35))
        self.response.raise_for_status.assert_called_once_with()

    def test_contacts_fallbacks_nulls_and_outline_centers(self) -> None:
        self.response.json.return_value = {
            "elements": [
                {
                    "type": "node",
                    "id": 123,
                    "lat": 49.84,
                    "lon": 24.03,
                    "tags": {
                        "name": "Lviv coffee",
                        "contact:website": "https://primary.example",
                        "website": "https://fallback.example",
                        "instagram": "cafe",
                        "contact:facebook": "primary",
                        "facebook": "fallback",
                    },
                },
                {
                    "type": "way",
                    "id": 456,
                    "center": {"lat": 49.85, "lon": 24.04},
                    "tags": {"website": "https://fallback.example"},
                },
                {
                    "type": "relation",
                    "id": 789,
                    "center": {"lat": 49.86, "lon": 24.05},
                },
            ]
        }
        raw = self.service.search("49.8419,24.0315", "cafe", 2000)
        places = json.loads(raw)
        self.assertIn("Lviv", raw)
        self.assertEqual(
            places[0],
            {
                "osm_id": "node/123",
                "name": "Lviv coffee",
                "latitude": 49.84,
                "longitude": 24.03,
                "website": "https://primary.example",
                "instagram": "cafe",
                "facebook": "primary",
                "email": None,
                "phone": None,
                "address": None,
                "google_maps_url": "https://www.google.com/maps/search/?api=1&query=Lviv%20coffee,%2049.84,24.03",
                "distance_m": places[0]["distance_m"],
            },
        )
        self.assertEqual(places[1]["osm_id"], "way/456")
        self.assertEqual(places[1]["latitude"], 49.85)
        self.assertEqual(places[1]["website"], "https://fallback.example")
        self.assertIsNone(places[1]["instagram"])
        self.assertEqual(places[2]["osm_id"], "relation/789")
        self.assertEqual(places[2]["longitude"], 24.05)
        self.assertIsNone(places[2]["website"])
        filtered = json.loads(
            self.service.search("49.8419,24.0315", "cafe", 2000, "lViV")
        )
        self.assertEqual(filtered, places[:1])
        self.assertEqual(
            json.loads(self.service.search("49,24", "cafe", 2000, ".*")), []
        )

    def test_request_errors_are_not_empty_success(self) -> None:
        for error in (requests.Timeout("slow"), requests.HTTPError("503")):
            with self.subTest(error=error):
                self.post.side_effect = error
                with self.assertRaises(OverpassError):
                    self.service.search("49,24", "cafe", 2000)
        self.post.side_effect = None
        self.response.raise_for_status.side_effect = requests.HTTPError("429")
        with self.assertRaises(OverpassError):
            self.service.search("49,24", "cafe", 2000)

    def test_invalid_json_and_overpass_runtime_errors(self) -> None:
        self.response.json.side_effect = ValueError("invalid JSON")
        with self.assertRaises(OverpassError):
            self.service.search("49,24", "cafe", 2000)
        self.response.json.side_effect = None
        for payload in (
            None,
            {},
            {"elements": None},
            {"elements": [], "remark": "runtime error: timeout"},
            {"elements": [None]},
            {"elements": [{"type": "node"}]},
        ):
            with self.subTest(payload=payload):
                self.response.json.return_value = payload
                with self.assertRaises(OverpassError):
                    self.service.search("49,24", "cafe", 2000)

    def test_malformed_elements_raise_overpass_errors(self) -> None:
        for changes in (
            {"tags": {"name": 42}},
            {"tags": {"website": []}},
            {"center": None},
            {"center": []},
            {"center": {"lat": float("nan"), "lon": 24}},
            {"center": {"lat": 49, "lon": float("inf")}},
            {"center": {"lat": "49", "lon": 24}},
            {"center": {"lat": True, "lon": 24}},
            {"center": {"lat": 91, "lon": 24}},
            {"id": None},
            {"id": True},
            {"id": -1},
            {"type": []},
        ):
            for name in (None, "unmatched"):
                with self.subTest(changes=changes, name=name):
                    element: dict[str, object] = {
                        "type": "way",
                        "id": 123,
                        "center": {"lat": 49, "lon": 24},
                    }
                    element.update(changes)
                    self.response.json.return_value = {"elements": [element]}
                    with self.assertRaises(OverpassError):
                        self.service.search("49,24", "cafe", 2000, name)

    def test_geocoder_configuration_errors_are_wrapped(self) -> None:
        with patch(
            "my_package.infrastructure.geocoding.Nominatim",
            side_effect=ConfigurationError("Invalid user agent"),
        ):
            with self.assertRaises(GeocodingError):
                self.service.search("Lviv", "cafe", 2000)
        self.post.assert_not_called()

    def test_validation_before_network(self) -> None:
        for arguments, error in (
            ({"radius_m": True}, TypeError),
            ({"radius_m": 1.5}, TypeError),
            ({"radius_m": 0}, ValueError),
            ({"radius_m": -1}, ValueError),
            ({"category": "unknown"}, ValueError),
            ({"category": 'cafe"];out;'}, ValueError),
            ({"category": None}, TypeError),
            ({"name": 1}, TypeError),
            ({"center": ""}, ValueError),
            ({"center": None}, TypeError),
            ({"center": "91,24"}, ValueError),
            ({"center": "49,181"}, ValueError),
            ({"center": "nan,24"}, ValueError),
            ({"center": "49,inf"}, ValueError),
            ({"center": "49,abc"}, ValueError),
            ({"center": "49,24,10"}, ValueError),
        ):
            with self.subTest(arguments=arguments):
                params = dict(center="49,24", category="cafe", radius_m=2000)
                params.update(arguments)
                with self.assertRaises(error):
                    self.service.search(**params)
        self.post.assert_not_called()

    def test_city_geocoding_and_errors(self) -> None:
        with patch("my_package.infrastructure.geocoding.Nominatim") as geocoder:
            geocode = geocoder.return_value.geocode
            geocode.return_value = Mock(latitude=49.8419, longitude=24.0315)
            self.service.search("Lviv, Ukraine", "cafe", 2000)
            geocoder.assert_called_once_with(user_agent="GmScrap/0.1", timeout=10)
            geocode.assert_called_once_with("Lviv, Ukraine", exactly_one=True)
        self.assertIn("49.8419,24.0315", self.post.call_args.kwargs["data"]["data"])
        with patch("my_package.infrastructure.geocoding.Nominatim") as geocoder:
            geocoder.return_value.geocode.return_value = None
            with self.assertRaises(GeocodingError):
                ScrapService().search("Missing city", "cafe", 2000)
            geocoder.return_value.geocode.side_effect = GeocoderTimedOut("slow")
            with self.assertRaises(GeocodingError):
                ScrapService().search("Lviv", "cafe", 2000)

    def test_legacy_kilometers_and_multiple_categories(self) -> None:
        self.service.scrape("49,24", "coffee shop, restaurant, cafe", 2)
        query = self.post.call_args.kwargs["data"]["data"]
        self.assertIn("around:2000,49.0,24.0", query)
        self.assertEqual(query.count('"amenity"="cafe"'), 1)
        self.assertIn('"amenity"="restaurant"', query)
        self.assertIn("\n(nwr", query)


class CliTests(unittest.TestCase):
    def test_success_and_failure_have_distinct_streams_and_exit_codes(self) -> None:
        arguments = ["--center", "49,24", "--category", "cafe", "--radius", "2000"]
        with (
            patch("my_package.main.ScrapService") as service,
            patch("sys.stdout") as stdout,
            patch("sys.stderr") as stderr,
        ):
            service.return_value.search.return_value = "[]"
            self.assertEqual(main(arguments), 0)
            stdout.write.assert_any_call("[]")
            stderr.write.assert_not_called()
            stdout.reset_mock()
            service.return_value.search.side_effect = OverpassError("Unavailable")
            self.assertEqual(main(arguments), 1)
            stdout.write.assert_not_called()
            stderr.write.assert_any_call('{"error": "Unavailable"}')
