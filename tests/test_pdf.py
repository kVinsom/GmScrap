"""Offline coverage of the optional JSON-to-PDF boundary and rendered output."""

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from my_package.handlers.pdf.pdf import PdfHandler
from my_package.pdf_main import main
from my_package.services.pdf import PdfService

PLACE = {
    "osm_id": "node/1",
    "name": "Example Café",
    "latitude": 49.8419,
    "longitude": 24.0315,
    "location": "Lviv, Ukraine",
    "email": "hello@example.com",
    "website": "example.com",
    "facebook": "facebook.com/example.cafe",
    "instagram": "@example.cafe",
}


class PdfHandlerTests(unittest.TestCase):
    def test_handler_delegates_validated_json(self):
        service = Mock()
        handler = PdfHandler(service)
        handler.generate(json.dumps([PLACE]), "places.pdf", location="Lviv")
        service.generate.assert_called_once_with(
            [PLACE], Path("places.pdf"), location="Lviv"
        )

    def test_rejects_invalid_input_before_writing(self):
        service = Mock()
        for payload in (
            "not json",
            "null",
            "{}",
            "[1]",
            '[{"name": 2}]',
            '[{"phone": 2}]',
            '[{"google_place_id": 2}]',
            '[{"google_maps_url": 2}]',
            '[{"latitude": true}]',
            '[{"latitude": 91}]',
            '[{"longitude": NaN}]',
            '[{"longitude": Infinity}]',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                PdfHandler(service).generate(payload, "places.pdf")
        service.generate.assert_not_called()

    def test_scraper_and_optional_renderer_are_not_loaded_on_import(self):
        check = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import my_package.pdf_main; "
                    "assert 'reportlab' not in sys.modules; "
                    "assert 'my_package.services.scrap' not in sys.modules; "
                    "assert 'requests' not in sys.modules"
                ),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_cli_invalid_input_returns_json_error(self):
        stderr = io.StringIO()
        with patch("sys.stdin", io.StringIO("{}")), redirect_stderr(stderr):
            self.assertEqual(main(["-", "places.pdf"]), 1)
        self.assertIn("array", json.loads(stderr.getvalue())["error"])


@unittest.skipUnless(
    importlib.util.find_spec("reportlab") and importlib.util.find_spec("pypdf"),
    'PDF integration tests require pip install ".[pdf]" pypdf',
)
class PdfIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.output = Path(self.directory) / "places.pdf"
        self.handler = PdfHandler(PdfService())

    def read(self):
        from pypdf import PdfReader

        return PdfReader(self.output)

    def test_english_labels_unicode_names_and_clickable_links(self):
        self.handler.generate(json.dumps([PLACE, PLACE]), self.output)
        reader = self.read()
        text = "".join(page.extract_text() for page in reader.pages)
        self.assertEqual(text.count(PLACE["name"]), 2)
        for expected in (
            "Location",
            "Contacts",
            "Lviv, Ukraine",
            "49.8419",
            "hello@example.com",
        ):
            self.assertIn(expected, text)
        links = [
            annotation.get_object()["/A"]["/URI"]
            for page in reader.pages
            for annotation in page.get("/Annots", [])
        ]
        for expected in (
            "https://www.google.com/maps/search/?api=1&query=Example%20Caf%C3%A9,%20Lviv,%20Ukraine,%2049.8419,24.0315",
            "mailto:hello@example.com",
            "https://example.com",
            "https://facebook.com/example.cafe",
            "https://instagram.com/example.cafe",
        ):
            self.assertIn(expected, links)

    def test_missing_fields_empty_results_and_markup(self):
        self.handler.generate("[]", self.output)
        self.assertIn("No places found", self.read().pages[0].extract_text())
        self.handler.generate(
            json.dumps([{"name": "<b>Coffee & tea</b>"}]), self.output
        )
        text = self.read().pages[0].extract_text()
        self.assertIn("<b>Coffee & tea</b>", text)
        self.assertIn("Not provided", text)

    def test_many_places_and_long_values_paginate(self):
        places = [dict(PLACE, name=f"Place {index}") for index in range(20)]
        places.append(
            dict(
                PLACE,
                name="Long name " * 100,
                website="https://example.com/" + "a" * 5000,
            )
        )
        self.handler.generate(json.dumps(places), self.output)
        reader = self.read()
        self.assertGreater(len(reader.pages), 1)
        text = "".join(page.extract_text() for page in reader.pages)
        for index in range(20):
            self.assertIn(f"Place {index}\n", text)

    def test_bad_font_preserves_existing_file(self):
        self.output.write_bytes(b"existing PDF")
        with self.assertRaises(ValueError):
            PdfHandler(
                PdfService(font_path=Path(self.directory) / "missing.ttf")
            ).generate("[]", self.output)
        self.assertEqual(self.output.read_bytes(), b"existing PDF")

    def test_unsafe_and_malformed_contacts_are_filtered(self):
        self.handler.generate(
            json.dumps(
                [{"website": "javascript:alert(1)", "facebook": "https://[broken"}]
            ),
            self.output,
        )
        reader = self.read()
        text = reader.pages[0].extract_text()
        self.assertNotIn("javascript:alert(1)", text)
        self.assertNotIn("https://[broken", text)
        self.assertFalse(reader.pages[0].get("/Annots"))

    def test_cli_reads_utf8_bom_file_and_stdin(self):
        source = Path(self.directory) / "places.json"
        source.write_text(json.dumps([PLACE]), encoding="utf-8-sig")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(source), str(self.output)]), 0)
            with patch("sys.stdin", io.StringIO("[]")):
                self.assertEqual(main(["-", str(self.output)]), 0)
        self.assertIn("No places found", self.read().pages[0].extract_text())
