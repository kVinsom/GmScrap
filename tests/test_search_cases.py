"""Additional search scenarios; all external services are mocked."""

import json
import unittest
from unittest.mock import Mock, patch

import requests
from geopy.exc import GeocoderServiceError, GeocoderUnavailable

from my_package.handlers.scrap.scrap import ScrapHandler
from my_package.services.scrap import GeocodingError, OverpassError, ScrapService


class SearchCasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(
            patch(
                "my_package.infrastructure.website.WebsiteContactEnricher._fetch",
                return_value=None,
            )
        )
        self.service = ScrapService()
        post_patch = patch("my_package.infrastructure.overpass.requests.post")
        self.post = post_patch.start()
        self.addCleanup(post_patch.stop)
        geocoder_patch = patch("my_package.infrastructure.geocoding.Nominatim")
        self.geocoder = geocoder_patch.start()
        self.addCleanup(geocoder_patch.stop)
        self.post.return_value.json.return_value = {"elements": []}

    def test_all_categories_and_normalization(self) -> None:
        for category, tag in (
            (" coffee SHOP ", '"amenity"="cafe"'),
            ("CAFE", '"amenity"="cafe"'),
            ("restaurant", '"amenity"="restaurant"'),
            ("bar", '"amenity"="bar"'),
            ("pharmacy", '"amenity"="pharmacy"'),
            ("supermarket", '"shop"="supermarket"'),
        ):
            with self.subTest(category=category):
                self.service.search("49,24", category, 1)
                self.assertIn(tag, self.post.call_args.kwargs["data"]["data"])

    def test_coordinate_boundaries_and_whitespace(self) -> None:
        for center in ("-90,-180", "90,180", "0,0", " 49.84 , 24.03 ", "5e1,3e1"):
            with self.subTest(center=center):
                self.assertEqual(self.service.search(center, "cafe", 1), "[]")
        self.geocoder.assert_not_called()

    def test_more_invalid_inputs_never_call_external_services(self) -> None:
        cases = (
            ("category", "", ValueError),
            ("category", "cafe,", ValueError),
            ("category", ",cafe", ValueError),
            ("category", "cafe, ,bar", ValueError),
            ("category", [], TypeError),
            ("center", "   ", ValueError),
            ("center", [], TypeError),
            ("center", "49", ValueError),
            ("center", "49,", ValueError),
            ("center", "-90.00001,24", ValueError),
            ("center", "49,-180.00001", ValueError),
            ("center", "-inf,24", ValueError),
            ("center", "49,nan", ValueError),
            ("radius_m", False, TypeError),
            ("radius_m", "2000", TypeError),
            ("radius_m", None, TypeError),
            ("name", [], TypeError),
        )
        for key, value, error in cases:
            with self.subTest(key=key, value=value):
                arguments = dict(center="49,24", category="cafe", radius_m=2000)
                arguments[key] = value
                with self.assertRaises(error):
                    self.service.search(**arguments)
        self.post.assert_not_called()
        self.geocoder.assert_not_called()

    def test_contact_priority_for_every_contact_field(self) -> None:
        for field in ("website", "instagram", "facebook", "email"):
            primary, fallback = {
                "website": ("https://primary.example", "https://fallback.example"),
                "email": ("primary@example.org", "fallback@example.org"),
            }.get(field, ("primary", "fallback"))
            for tags, expected in (
                ({}, None),
                ({field: fallback}, fallback),
                ({f"contact:{field}": primary}, primary),
                ({field: fallback, f"contact:{field}": primary}, primary),
                ({field: fallback, f"contact:{field}": ""}, fallback),
            ):
                with self.subTest(field=field, tags=tags):
                    self.post.return_value.json.return_value = {
                        "elements": [{"type": "node", "id": 1, "tags": tags}]
                    }
                    places = json.loads(self.service.search("49,24", "cafe", 2000))
                    self.assertEqual(len(places), 1)
                    self.assertEqual(places[0][field], expected)

    def test_name_filter_is_literal_unicode_and_optional(self) -> None:
        self.post.return_value.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "tags": {"name": "Café [coffee].*"}},
                {"type": "node", "id": 2, "tags": {"name": "Other"}},
                {"type": "node", "id": 3},
            ]
        }
        for name, expected_ids in (
            (None, [1, 2, 3]),
            ("", [1, 2, 3]),
            ("   ", [1, 2, 3]),
            (" CAFÉ ", [1]),
            ("[coffee].*", [1]),
            ("other", [2]),
            (".*Other", []),
            ('";out;', []),
        ):
            with self.subTest(name=name):
                places = json.loads(self.service.search("49,24", "cafe", 2000, name))
                self.assertEqual(
                    [place["osm_id"] for place in places],
                    [f"node/{value}" for value in expected_ids],
                )

    def test_nodes_use_position_and_outlines_use_center(self) -> None:
        for kind in ("node", "way", "relation"):
            with self.subTest(kind=kind):
                self.post.return_value.json.return_value = {
                    "elements": [
                        {
                            "type": kind,
                            "id": 1,
                            "lat": 1,
                            "lon": 2,
                            "center": {"lat": 3, "lon": 4},
                        }
                    ]
                }
                place = json.loads(self.service.search("49,24", "cafe", 2000))[0]
                expected = (1, 2) if kind == "node" else (3, 4)
                self.assertEqual((place["latitude"], place["longitude"]), expected)

    def test_http_errors_preserve_cause_and_skip_json(self) -> None:
        for code in (400, 403, 429, 500, 502, 503, 504):
            with self.subTest(status=code):
                response = Mock()
                error = requests.HTTPError(str(code))
                response.raise_for_status.side_effect = error
                self.post.return_value = response
                with self.assertRaises(OverpassError) as raised:
                    self.service.search("49,24", "cafe", 2000)
                self.assertIs(raised.exception.__cause__, error)
                response.json.assert_not_called()

    def test_transport_errors_preserve_cause(self) -> None:
        for error_type in (
            requests.ConnectionError,
            requests.ConnectTimeout,
            requests.ReadTimeout,
            requests.exceptions.SSLError,
        ):
            with self.subTest(error_type=error_type):
                error = error_type("Unavailable")
                self.post.side_effect = error
                with self.assertRaises(OverpassError) as raised:
                    self.service.search("49,24", "cafe", 2000)
                self.assertIs(raised.exception.__cause__, error)

    def test_partial_response_with_runtime_error_is_rejected(self) -> None:
        self.post.return_value.json.return_value = {
            "remark": "runtime error: out of memory",
            "elements": [{"type": "node", "id": 1}],
        }
        with self.assertRaises(OverpassError):
            self.service.search("49,24", "cafe", 2000)

    def test_malformed_node_coordinates_and_tags(self) -> None:
        for changes in (
            {"lat": float("nan")},
            {"lon": -181},
            {"lat": []},
            {"lon": True},
            {"tags": None},
            {"tags": []},
            {"id": "1"},
            {"id": 1.5},
            {"id": 0},
            {"type": "area"},
        ):
            with self.subTest(changes=changes):
                element = {"type": "node", "id": 1, **changes}
                self.post.return_value.json.return_value = {"elements": [element]}
                with self.assertRaises(OverpassError):
                    self.service.search("49,24", "cafe", 2000)

    def test_custom_endpoint_and_user_agent(self) -> None:
        service = ScrapService(
            endpoint="https://overpass.example/api", user_agent="test"
        )
        service.search("49,24", "cafe", 2000)
        self.assertEqual(self.post.call_args.args, ("https://overpass.example/api",))
        self.assertEqual(self.post.call_args.kwargs["headers"]["User-Agent"], "test")

    def test_city_errors_do_not_call_overpass(self) -> None:
        for error in (GeocoderUnavailable("offline"), GeocoderServiceError("blocked")):
            with self.subTest(error=error):
                self.geocoder.return_value.geocode.side_effect = error
                with self.assertRaises(GeocodingError) as raised:
                    ScrapService().search("Lviv", "cafe", 2000)
                self.assertIs(raised.exception.__cause__, error)
        self.post.assert_not_called()

    def test_city_not_found_does_not_call_overpass(self) -> None:
        self.geocoder.return_value.geocode.return_value = None
        with self.assertRaisesRegex(GeocodingError, "City not found"):
            self.service.search("Missing city", "cafe", 2000)
        self.post.assert_not_called()

    def test_reuses_geocoder_and_configures_rate_limit(self) -> None:
        with patch("my_package.infrastructure.geocoding.RateLimiter") as limiter:
            limiter.return_value.return_value = Mock(latitude=49, longitude=24)
            self.service.search(" Lviv, Ukraine ", "cafe", 2000)
            self.service.search("Kyiv", "cafe", 2000)
            self.geocoder.assert_called_once()
            limiter.assert_called_once_with(
                self.geocoder.return_value.geocode,
                min_delay_seconds=1,
                max_retries=0,
                swallow_exceptions=False,
            )
            self.assertEqual(limiter.return_value.call_count, 2)
            self.assertEqual(
                limiter.return_value.call_args_list[0].args, ("Lviv, Ukraine",)
            )

    def test_legacy_radius_validation(self) -> None:
        for radius, error in (
            (True, TypeError),
            (None, TypeError),
            ("2", TypeError),
            (1.5, TypeError),
            (0, ValueError),
            (-1, ValueError),
        ):
            with self.subTest(radius=radius):
                with self.assertRaises(error):
                    self.service.scrape("49,24", "cafe", radius)
        self.post.assert_not_called()

    def test_handler_search_returns_service_json(self) -> None:
        self.assertEqual(
            ScrapHandler(self.service).search("49,24", "cafe", 2000, "Lviv"),
            "[]",
        )

    def test_handler_propagates_service_errors(self) -> None:
        error = requests.ConnectionError("offline")
        self.post.side_effect = error
        handler = ScrapHandler(self.service)
        for call in (
            lambda: handler.search("49,24", "cafe", 2000),
            lambda: handler.scrape("49,24", "cafe", 2),
        ):
            with self.subTest(call=call):
                with self.assertRaises(OverpassError) as raised:
                    call()
                self.assertIs(raised.exception.__cause__, error)
