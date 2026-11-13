"""Business selection must reject streets and contactless records, not cafes in buildings."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from my_package.application.businesses import select_contactable_cafes
from my_package.application.search import SearchPlaces
from my_package.domain.businesses import cafe_exclusion_reason, has_business_contact
from my_package.domain.models import Place, SearchRequest
from my_package.handlers.pdf.pdf import PdfHandler
from my_package.infrastructure.osm import parse_element
from my_package.services.pdf import PdfService


class BusinessSelectionTests(unittest.TestCase):
    def test_rejected_contact_is_not_reintroduced_from_source(self):
        place = {"osm_id": "node/1", "name": "Cafe", "phone": "+380321234567"}
        source = {
            "type": "node",
            "id": 1,
            "tags": {"amenity": "cafe", "name": "Cafe", "phone": "+380321234567"},
        }
        included, excluded = select_contactable_cafes(
            [place], [source], rejected_contacts={"node/1": {"phone": "+380321234567"}}
        )
        self.assertEqual(included, [])
        self.assertEqual(excluded[0]["reason"], "contact_ownership_uncertain")
        source["tags"]["website"] = "https://cafe.example"
        included, _ = select_contactable_cafes(
            [place], [source], rejected_contacts={"node/1": {"phone": "+380321234567"}}
        )
        self.assertEqual(len(included), 1)
        self.assertIsNone(included[0]["phone"])
        self.assertEqual(included[0]["website"], "https://cafe.example")

    @unittest.skipUnless(
        importlib.util.find_spec("reportlab") and importlib.util.find_spec("pypdf"),
        "PDF dependencies are optional",
    )
    def test_phone_contact_filter_and_pdf_phone_link(self):
        from pypdf import PdfReader

        source = Mock()
        source.search.return_value = [
            Place("node/1", "Cafe", 49, 24, phone="+380 (32) 123-45-67"),
            Place("node/2", "Other", 49, 24),
        ]
        results = SearchPlaces(Mock(), source).execute(
            SearchRequest(
                "49,24", "cafe", 5000, contacts=("phone",), enrich_website=False
            )
        )
        self.assertEqual([p.osm_id for p in results], ["node/1"])
        self.assertEqual(results[0].phone, "+380321234567")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "phone.pdf"
            PdfHandler(PdfService()).generate(
                json.dumps([{"name": "Cafe", "phone": "+380 (32) 123-45-67"}]), output
            )
            page = PdfReader(output).pages[0]
            self.assertIn("Phone\n+380321234567", page.extract_text())
            self.assertIn(
                "tel:+380321234567",
                [a.get_object()["/A"]["/URI"] for a in page["/Annots"]],
            )

    def test_cafe_in_building_is_kept_but_building_alone_is_not(self):
        self.assertIsNone(
            cafe_exclusion_reason(
                {"amenity": "cafe", "building": "yes", "name": "Cafe"}
            )
        )
        self.assertEqual(
            cafe_exclusion_reason({"building": "yes", "name": "Cafe Street"}),
            "not_tagged_as_cafe_business",
        )

    def test_streets_landmarks_and_inactive_objects_are_excluded(self):
        for extra in (
            {"highway": "residential"},
            {"place": "square"},
            {"historic": "monument"},
            {"tourism": "attraction"},
            {"man_made": "tower"},
            {"disused": "yes"},
            {"disused:amenity": "cafe"},
            {"opening_hours": "closed"},
        ):
            with self.subTest(extra=extra):
                self.assertIsNotNone(
                    cafe_exclusion_reason(dict(amenity="cafe", name="Cafe", **extra))
                )

    def test_maps_addresses_and_invalid_contacts_do_not_count(self):
        self.assertFalse(
            has_business_contact(
                {
                    "address": "Main Street",
                    "google_maps_url": "https://www.google.com/maps?cid=123",
                }
            )
        )
        for record in (
            {"email": "unknown"},
            {"phone": "123"},
            {"website": "https://facebook.com/sharer.php?u=x"},
            {"website": "https://www.google.com/maps?cid=123"},
        ):
            with self.subTest(record=record):
                self.assertFalse(has_business_contact(record))

    def test_valid_phone_only_business_counts_and_mobile_fallback_is_exported(self):
        place = parse_element(
            {
                "type": "node",
                "id": 1,
                "tags": {"phone": "invalid", "contact:mobile": "+380 (32) 123-45-67"},
            }
        )
        self.assertEqual(place.phone, "+380321234567")
        self.assertTrue(has_business_contact({"phone": place.phone}))

    def test_filter_uses_source_evidence_and_contacts_and_preserves_order(self):
        places = [
            {
                "osm_id": f"node/{i}",
                "name": f"Cafe {i}",
                "google_maps_url": "https://www.google.com/maps?cid=123",
            }
            for i in range(1, 7)
        ]
        sources = [
            {"type": "node", "id": i, "tags": {"amenity": "cafe", "name": f"Cafe {i}"}}
            for i in range(1, 6)
        ]
        sources[0]["tags"].update({"phone": "+380321234567", "building": "yes"})
        sources[1]["tags"].update({"website": "https://facebook.com/cafe"})
        sources[3]["tags"].update(
            {"highway": "residential", "website": "https://cafe.example"}
        )
        sources[4]["tags"].update(
            {"historic": "monument", "website": "https://cafe.example"}
        )
        included, excluded = select_contactable_cafes(places, sources)
        self.assertEqual([p["osm_id"] for p in included], ["node/1", "node/2"])
        self.assertEqual(included[0]["phone"], "+380321234567")
        self.assertIsNone(included[1]["website"])
        self.assertEqual(included[1]["facebook"], "https://facebook.com/cafe")
        self.assertEqual(
            [p["reason"] for p in excluded],
            [
                "no_valid_business_contacts",
                "street_or_geographical_feature",
                "landmark_or_ambiguous_structure",
                "source_evidence_missing",
            ],
        )
        self.assertNotIn("phone", places[0])
