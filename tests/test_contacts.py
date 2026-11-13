import csv
import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from unittest.mock import Mock, patch

import requests

from my_package.application.search import SearchPlaces
from my_package.domain.models import Place, SearchRequest
from my_package.export import results_csv
from my_package.infrastructure.osm import parse_element
from my_package.infrastructure.website import WebsiteContactEnricher, public_url
from my_package.main import main


class ContactTests(unittest.TestCase):
    def test_duplicate_websites_reuse_contacts_without_copying_venue_identity(self):
        source = Mock()
        source.search.return_value = [
            Place("node/1", "First", 0, 0, website="https://cafe.example"),
            Place("node/2", "Second", 0, 1, website="https://cafe.example"),
        ]
        enricher = Mock()
        enricher.enrich.side_effect = lambda p: replace(p, email="hello@example.org")
        search = SearchPlaces(Mock(), source, enricher)
        for _ in range(2):
            result = search.execute(SearchRequest("0,0", "cafe", 1))
            self.assertEqual([p.name for p in result], ["First", "Second"])
            self.assertEqual([p.email for p in result], ["hello@example.org"] * 2)
        self.assertEqual(enricher.enrich.call_count, 2)

    def test_enrichment_budget_keeps_unenriched_places(self):
        source = Mock()
        source.search.return_value = [
            Place("node/1", "First", 0, 0),
            Place("node/2", "Second", 0, 1),
        ]
        enricher = Mock()
        enricher.enrich.side_effect = lambda p: replace(p, email="hello@example.org")
        with patch("my_package.application.search.monotonic", side_effect=[0, 1, 31]):
            result = SearchPlaces(Mock(), source, enricher).execute(
                SearchRequest("0,0", "cafe", 1)
            )
        self.assertEqual(enricher.enrich.call_count, 1)
        self.assertEqual(len(result), 2)
        self.assertIsNone(result[1].email)

    def test_osm_email_priority_and_address(self):
        place = parse_element(
            {
                "type": "node",
                "id": 1,
                "tags": {
                    "contact:email": "primary@example.org",
                    "email": "other@example.org",
                    "addr:street": "Main",
                    "addr:housenumber": "2",
                    "addr:city": "Lviv",
                },
            }
        )
        self.assertEqual(place.email, "primary@example.org")
        self.assertEqual(place.address, "Main 2, Lviv")

    def test_homepage_then_contact_page_preserves_osm(self):
        place = Place(
            "node/1", "Cafe", 49, 24, website="https://cafe.example", instagram="osm"
        )
        enricher = WebsiteContactEnricher()
        with patch.object(
            enricher,
            "_fetch",
            side_effect=[
                (
                    place.website,
                    '<a href="https://other.example/contact">Contact</a><a href="/contact">Contact us</a><a href="https://instagram.com/new">IG</a>',
                ),
                (
                    place.website + "/contact",
                    '<a href="mailto:hello%40cafe.example?subject=Hi">Email</a><a href="https://www.facebook.com/cafe">FB</a>',
                ),
            ],
        ) as fetch:
            result = enricher.enrich(place)
        self.assertEqual(result.email, "hello@cafe.example")
        self.assertEqual(result.instagram, "osm")
        self.assertEqual(result.facebook, "https://www.facebook.com/cafe")
        self.assertEqual(fetch.call_args.args, (place.website + "/contact",))
        self.assertIsNone(place.email)

    def test_plain_text_email_and_lookalike_social_host(self):
        enricher = WebsiteContactEnricher()
        with patch.object(
            enricher,
            "_fetch",
            return_value=(
                "https://cafe.example",
                '<p>hello@cafe.example</p><a href="https://instagram.com.evil.example/cafe">IG</a><script>bad@cafe.example</script>',
            ),
        ):
            result = enricher.enrich(
                Place("node/1", None, None, None, website="cafe.example")
            )
        self.assertEqual(result.email, "hello@cafe.example")
        self.assertIsNone(result.instagram)

    def test_website_failure_keeps_result(self):
        place = Place("node/1", None, None, None, website="https://cafe.example")
        with patch.object(
            WebsiteContactEnricher, "_fetch", side_effect=requests.Timeout()
        ):
            self.assertEqual(WebsiteContactEnricher().enrich(place), place)

    def test_malformed_links_do_not_hide_valid_contacts(self):
        with patch.object(
            WebsiteContactEnricher,
            "_fetch",
            return_value=(
                "https://cafe.example",
                '<a href="https://[broken/contact">Contact</a><a href="https://[broken">Bad</a><p>hello@cafe.example</p>',
            ),
        ):
            result = WebsiteContactEnricher().enrich(
                Place("node/1", None, None, None, website="cafe.example")
            )
        self.assertEqual(result.email, "hello@cafe.example")

    def test_complete_contacts_skip_fetch(self):
        place = Place(
            "node/1",
            None,
            None,
            None,
            website="cafe.example",
            email="cafe@example.org",
            instagram="cafe",
            facebook="cafe",
        )
        with patch.object(WebsiteContactEnricher, "_fetch") as fetch:
            self.assertEqual(WebsiteContactEnricher().enrich(place), place)
        fetch.assert_not_called()

    def test_public_url_rejects_private_addresses(self):
        for url in (
            "file:///etc/passwd",
            "https://user:pass@example.org",
            "http://127.0.0.1",
            "http://[::1]",
        ):
            self.assertFalse(public_url(url))
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, None, ("192.168.1.1", 443))],
        ):
            self.assertFalse(public_url("https://cafe.example"))

    def test_enrich_before_or_filter_then_distance_sort(self):
        source = Mock()
        source.search.return_value = [
            Place("node/1", "Cafe far", 0, 1, email="far@example.org"),
            Place("node/2", "Cafe near", 0, 0),
            Place("node/3", "Cafe unknown", None, None, email="unknown@example.org"),
            Place("node/4", "Cafe no contact", 0, 0),
        ]
        enricher = Mock()
        enricher.enrich.side_effect = lambda p: (
            replace(p, instagram="near") if p.osm_id == "node/2" else p
        )
        search = SearchPlaces(Mock(), source, enricher)
        result = search.execute(
            SearchRequest("0,0", "cafe", 200000, contacts=("email", "instagram"))
        )
        self.assertEqual([p.osm_id for p in result], ["node/2", "node/1", "node/3"])
        self.assertAlmostEqual(result[1].distance_m, 111195, delta=1)
        self.assertIn("query=Cafe%20near,%200,0", result[0].google_maps_url)
        self.assertIsNone(result[-1].distance_m)
        enricher.reset_mock()
        search.execute(SearchRequest("0,0", "cafe", 1, enrich_website=False))
        enricher.enrich.assert_not_called()

    def test_csv_quotes_unicode_newlines_and_formula_text(self):
        result = results_csv([{"name": 'Coffee, "Café"\nBar', "email": "=formula"}])
        rows = list(csv.DictReader(io.StringIO(result)))
        self.assertEqual(rows[0]["name"], 'Coffee, "Café"\nBar')
        self.assertEqual(rows[0]["email"], "'=formula")
        self.assertEqual(len(list(csv.reader(io.StringIO(results_csv([]))))), 1)

    def test_cli_csv_and_options(self):
        output = io.StringIO()
        with patch("my_package.main.ScrapHandler") as handler, redirect_stdout(output):
            handler.return_value.search.return_value = json.dumps([{"name": "Cafe"}])
            self.assertEqual(
                main(
                    [
                        "--center",
                        "0,0",
                        "--category",
                        "cafe",
                        "--radius",
                        "100",
                        "--has-contact",
                        "email",
                        "--has-contact",
                        "instagram",
                        "--format",
                        "csv",
                        "--no-enrich-website",
                    ]
                ),
                0,
            )
        self.assertEqual(
            list(csv.DictReader(io.StringIO(output.getvalue())))[0]["name"], "Cafe"
        )
        self.assertEqual(
            handler.return_value.search.call_args.kwargs["contacts"],
            ("email", "instagram"),
        )

    def test_invalid_contacts_fail_before_search(self):
        for contacts in (("fax",), "email"):
            with self.assertRaises(ValueError):
                SearchRequest("0,0", "cafe", 1, contacts=contacts)
