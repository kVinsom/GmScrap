"""Contact routing and business Maps links across search and PDF exports."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from my_package.application.search import SearchPlaces
from my_package.domain.links import business_maps_url, normalize_contacts
from my_package.domain.models import Place, SearchRequest
from my_package.handlers.pdf.pdf import PdfHandler
from my_package.infrastructure.osm import parse_element
from my_package.infrastructure.website import WebsiteContactEnricher
from my_package.services.pdf import PdfService


class ContactRoutingTests(unittest.TestCase):
    def test_unusable_contacts_do_not_survive_business_filtering(self):
        from my_package.domain.businesses import has_business_contact

        for field, value in (
            ("phone", "123.456"),
            ("phone", "tel:bad.example"),
            ("instagram", "."),
            ("facebook", "-"),
            ("instagram", "___"),
            ("website", "123.456"),
        ):
            with self.subTest(field=field, value=value):
                self.assertFalse(has_business_contact({field: value}))
        self.assertEqual(
            normalize_contacts([("phone", "https://cafe.example")])["website"],
            "https://cafe.example",
        )
        self.assertEqual(
            normalize_contacts([("website", "https://93.184.216.34")])["website"],
            "https://93.184.216.34",
        )

    def test_every_mislabelled_url_moves_to_its_actual_field(self):
        values = {
            "website": "https://cafe.example/menu",
            "facebook": "https://m.facebook.com/cafe",
            "instagram": "https://www.instagram.com/cafe/",
            "email": "mailto:hello%40cafe.example?subject=Hello",
            "phone": "tel:+380321234567",
            "google_maps_url": "https://www.google.com/maps?cid=123",
        }
        for source in values:
            for target, value in values.items():
                with self.subTest(source=source, target=target):
                    result = normalize_contacts([(source, value)])
                    self.assertEqual(
                        result[target],
                        {"email": "hello@cafe.example", "phone": "+380321234567"}.get(
                            target, value
                        ),
                    )
                    self.assertTrue(
                        all(v is None for k, v in result.items() if k != target)
                    )

    def test_dedicated_profile_wins_over_mislabelled_profile(self):
        for candidates in (
            [
                ("website", "https://facebook.com/wrong"),
                ("facebook", "https://facebook.com/right"),
            ],
            [
                ("facebook", "https://facebook.com/right"),
                ("website", "https://facebook.com/wrong"),
            ],
        ):
            self.assertEqual(
                normalize_contacts(candidates)["facebook"], "https://facebook.com/right"
            )

    def test_osm_invalid_primary_does_not_hide_valid_fallback(self):
        place = parse_element(
            {
                "type": "node",
                "id": 1,
                "tags": {
                    "contact:website": "https://facebook.com/cafe",
                    "website": "https://cafe.example",
                    "contact:email": "not an email",
                    "email": "hello@cafe.example",
                },
            }
        )
        self.assertEqual(place.website, "https://cafe.example")
        self.assertEqual(place.facebook, "https://facebook.com/cafe")
        self.assertEqual(place.email, "hello@cafe.example")

    def test_invalid_links_and_social_actions_are_not_contacts(self):
        for value in (
            "javascript:alert(1)",
            "file:///local",
            "https://[broken",
            "https://user@facebook.com/cafe",
            "https://facebook.com/sharer.php?u=x",
            "https://instagram.com/p/123",
            "https://instagram.com/reels/123",
            "https://facebook.com/",
            "https://tiktok.com/@cafe",
            "https://x.com/cafe",
        ):
            with self.subTest(value=value):
                self.assertFalse(any(normalize_contacts([("website", value)]).values()))
        self.assertIsNone(
            normalize_contacts(
                [("facebook", "https://facebook.com.evil.example/cafe")]
            )["facebook"]
        )

    def test_schemeless_aliases_and_multiple_links(self):
        result = normalize_contacts(
            [
                ("website", "fb.me/cafe; https://instagram.com/cafe"),
                ("email", "https://cafe.example"),
            ]
        )
        self.assertEqual(result["facebook"], "fb.me/cafe")
        self.assertEqual(result["instagram"], "https://instagram.com/cafe")
        self.assertEqual(result["website"], "https://cafe.example")

    def test_social_website_is_not_fetched(self):
        with patch.object(WebsiteContactEnricher, "_fetch") as fetch:
            place = WebsiteContactEnricher().enrich(
                Place("node/1", "Cafe", 0, 0, website="https://facebook.com/cafe")
            )
        fetch.assert_not_called()
        self.assertIsNone(place.website)
        self.assertEqual(place.facebook, "https://facebook.com/cafe")

    def test_contact_filter_uses_corrected_fields_without_enrichment(self):
        source = Mock()
        source.search.return_value = [
            Place("node/1", "Cafe", 0, 0, website="https://facebook.com/cafe")
        ]
        search = SearchPlaces(Mock(), source)
        self.assertEqual(
            search.execute(
                SearchRequest(
                    "0,0", "cafe", 1, contacts=("website",), enrich_website=False
                )
            ),
            [],
        )
        result = search.execute(
            SearchRequest(
                "0,0", "cafe", 1, contacts=("facebook",), enrich_website=False
            )
        )
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].website)

    def test_injected_enrichment_cannot_put_social_links_in_wrong_fields(self):
        source, enricher = Mock(), Mock()
        source.search.return_value = [Place("node/1", "Cafe", 0, 0)]
        enricher.enrich.return_value = Place(
            "node/1", "Cafe", 0, 0, email="https://instagram.com/cafe"
        )
        result = SearchPlaces(Mock(), source, enricher).execute(
            SearchRequest("0,0", "cafe", 1)
        )[0]
        self.assertIsNone(result.email)
        self.assertEqual(result.instagram, "https://instagram.com/cafe")


class BusinessMapsTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("reportlab") and importlib.util.find_spec("pypdf"),
        "PDF dependencies are optional",
    )
    def test_protocol_relative_contacts_have_clickable_https_links(self):
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "links.pdf"
            PdfHandler(PdfService()).generate(
                json.dumps(
                    [
                        {
                            "name": "Cafe",
                            "website": "//example.org",
                            "facebook": "//facebook.com/cafe",
                            "instagram": "//instagram.com/cafe",
                        }
                    ]
                ),
                output,
            )
            links = [
                a.get_object()["/A"]["/URI"]
                for page in PdfReader(output).pages
                for a in page.get("/Annots", [])
            ]
            for target in (
                "https://example.org",
                "https://facebook.com/cafe",
                "https://instagram.com/cafe",
            ):
                self.assertIn(target, links)

    @unittest.skipUnless(
        importlib.util.find_spec("reportlab") and importlib.util.find_spec("pypdf"),
        "PDF dependencies are optional",
    )
    def test_pdf_uses_exact_identifiers_even_without_coordinates(self):
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "places.pdf"
            PdfHandler(PdfService()).generate(
                json.dumps(
                    [
                        {"name": "First", "google_place_id": "ChIJ-test"},
                        {
                            "name": "Second",
                            "google_maps_url": "https://www.google.com/maps?cid=123",
                        },
                    ]
                ),
                output,
            )
            links = [
                a.get_object()["/A"]["/URI"]
                for page in PdfReader(output).pages
                for a in page.get("/Annots", [])
            ]
            self.assertEqual(len(links), 2)
            self.assertEqual(
                parse_qs(urlsplit(links[0]).query)["query_place_id"], ["ChIJ-test"]
            )
            self.assertEqual(links[1], "https://www.google.com/maps?cid=123")

    def test_named_search_encodes_business_address_and_coordinates(self):
        url = business_maps_url("Café A & B", 49.8415, 24.0315, "Main Street 1, Lviv")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(
            query,
            {
                "api": ["1"],
                "query": ["Café A & B, Main Street 1, Lviv, 49.8415,24.0315"],
            },
        )

    def test_place_id_and_existing_business_url_are_preserved(self):
        url = business_maps_url("Cafe", 0, 0, place_id="ChIJ-test")
        self.assertEqual(parse_qs(urlsplit(url).query)["query_place_id"], ["ChIJ-test"])
        self.assertEqual(
            parse_qs(
                urlsplit(
                    business_maps_url(None, None, None, place_id="ChIJ-test")
                ).query
            )["query_place_id"],
            ["ChIJ-test"],
        )
        direct = "https://www.google.com/maps?cid=123"
        self.assertEqual(business_maps_url("Cafe", 0, 0, existing=direct), direct)
        self.assertIn(
            "query=Cafe",
            business_maps_url(
                "Cafe", 0, 0, existing="https://evil.example/maps?cid=123"
            ),
        )

    def test_coordinate_link_is_upgraded_and_missing_names_still_work(self):
        old = "https://www.google.com/maps/search/?api=1&query=0,0"
        self.assertIn(
            "query=Cafe,%200,0", business_maps_url("Cafe", 0, 0, existing=old)
        )
        self.assertEqual(business_maps_url(None, 0, 0), old)
        self.assertIsNone(business_maps_url(None, None, None))
        self.assertIn(
            "query=Cafe,%20Lviv", business_maps_url("Cafe", None, None, "Lviv")
        )

    @unittest.skipUnless(
        importlib.util.find_spec("reportlab") and importlib.util.find_spec("pypdf"),
        "PDF dependencies are optional",
    )
    def test_pdf_filters_contacts_and_embeds_business_maps_target(self):
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "places.pdf"
            PdfHandler(PdfService()).generate(
                json.dumps(
                    [
                        {
                            "name": "Cafe A & B",
                            "latitude": 49.8415,
                            "longitude": 24.0315,
                            "address": "Main Street 1, Lviv",
                            "website": "https://facebook.com/cafe",
                            "instagram": "mailto:hello@cafe.example",
                            "facebook": "https://instagram.com/cafe",
                        }
                    ]
                ),
                output,
            )
            page = PdfReader(output).pages[0]
            text = page.extract_text()
            self.assertIn("Website\nNot provided", text)
            self.assertIn("Facebook\nhttps://facebook.com/cafe", text)
            self.assertIn("Instagram\nhttps://instagram.com/cafe", text)
            self.assertIn("Email\nhello@cafe.example", text)
            links = [a.get_object()["/A"]["/URI"] for a in page["/Annots"]]
            maps = next(link for link in links if "google.com/maps" in link)
            self.assertEqual(
                parse_qs(urlsplit(maps).query)["query"],
                ["Cafe A & B, Main Street 1, Lviv, 49.8415,24.0315"],
            )
