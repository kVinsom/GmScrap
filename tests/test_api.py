"""Exercise HTTP boundaries with isolated SQLite and no external network."""

import base64
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

API_AVAILABLE = bool(
    importlib.util.find_spec("fastapi") and importlib.util.find_spec("httpx")
)
if API_AVAILABLE:
    from fastapi.testclient import TestClient

    from my_package.api import create_app, get_scrap_handler
    from my_package.domain.errors import OverpassError

PDF = b"%PDF-1.7\nexample\n%%EOF"


@unittest.skipUnless(API_AVAILABLE, 'Install ".[api]" and httpx for API tests')
class ApiTests(unittest.TestCase):
    def test_city_searches_share_one_geocoder_and_limiter(self):
        with (
            patch("my_package.infrastructure.geocoding.Nominatim") as factory,
            patch("my_package.infrastructure.geocoding.RateLimiter") as limiter,
            patch("my_package.infrastructure.overpass.requests.post") as post,
        ):
            limiter.return_value.return_value = Mock(latitude=49, longitude=24)
            post.return_value.json.return_value = {"elements": []}
            for city in ("Lviv", "Kyiv"):
                response = self.client.get(
                    "/search",
                    params={"center": city, "category": "cafe", "radius_m": 1},
                )
                self.assertEqual(response.status_code, 200)
        factory.assert_called_once()
        limiter.assert_called_once()
        self.assertEqual(limiter.return_value.call_count, 2)

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.database = Path(directory) / "pdfs.sqlite3"
        self.app = create_app(self.database)
        self.client = self.enterContext(TestClient(self.app))

    def upload(self, name="Café.pdf", content=PDF):
        return self.client.post(
            "/pdfs",
            params={"name": name},
            content=content,
            headers={"Content-Type": "application/pdf"},
        )

    def test_storage_round_trip_duplicates_and_deletion(self):
        self.assertEqual(self.client.get("/pdfs").json(), [])
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload(content=PDF + b"other").status_code, 409)
        response = self.client.get("/pdfs/Café.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PDF)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        self.assertEqual(
            self.client.get("/pdfs").json(),
            [
                {
                    "name": "Café.pdf",
                    "content_base64": base64.b64encode(PDF).decode("ascii"),
                }
            ],
        )
        self.assertEqual(self.client.delete("/pdfs/Café.pdf").status_code, 204)
        self.assertEqual(self.client.get("/pdfs/Café.pdf").status_code, 404)
        self.assertEqual(self.client.delete("/pdfs/Café.pdf").status_code, 404)

    def test_invalid_upload_and_names(self):
        self.assertEqual(self.upload(content=b"not PDF").status_code, 400)
        self.assertEqual(self.upload(name="   ").status_code, 400)
        self.assertEqual(self.upload(name="").status_code, 422)
        self.assertFalse(self.database.exists())

    def test_search_and_legacy_scrap_use_handlers(self):
        handler = Mock()
        handler.search.return_value = json.dumps([{"name": "Coffee"}])
        handler.scrape.return_value = "[]"
        self.app.dependency_overrides[get_scrap_handler] = lambda: handler
        response = self.client.get(
            "/search",
            params={
                "center": "49,24",
                "category": "cafe",
                "radius_m": 100,
                "name": "Coffee",
            },
        )
        self.assertEqual(response.json(), [{"name": "Coffee"}])
        handler.search.assert_called_once_with(
            "49,24",
            "cafe",
            100,
            "Coffee",
            contacts=(),
            sort_by_distance=True,
            enrich_website=True,
        )
        response = self.client.post(
            "/scrap", json={"geo": "49,24", "key_word": "cafe", "radius_in_km": 1}
        )
        self.assertEqual(response.json(), [])
        handler.scrape.assert_called_once_with("49,24", "cafe", 1)
        handler.search.side_effect = OverpassError("Provider failed")
        self.assertEqual(
            self.client.get(
                "/search",
                params={"center": "49,24", "category": "cafe", "radius_m": 100},
            ).status_code,
            502,
        )

    def test_request_validation_and_domain_validation(self):
        self.assertEqual(
            self.client.post(
                "/scrap",
                json={"geo": "49,24", "key_word": "cafe", "radius_in_km": True},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/search", params={"center": "49,24", "category": "cafe", "radius_m": 0}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/search",
                params={"center": "91,24", "category": "cafe", "radius_m": 100},
            ).status_code,
            400,
        )

    @unittest.skipUnless(importlib.util.find_spec("reportlab"), "Requires PDF extra")
    def test_generate_pdf_response(self):
        response = self.client.post(
            "/pdfs/generate",
            json={
                "places": [{"name": "Café", "latitude": 49, "longitude": 24}],
                "location": "Lviv, Ukraine",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertFalse(self.database.exists())
        self.assertEqual(
            self.client.post(
                "/pdfs/generate", json={"places": [{"latitude": 99}]}
            ).status_code,
            400,
        )

    def test_database_failure_has_safe_error_response(self):
        self.app.state.database = self.database.parent / "missing" / "db.sqlite3"
        response = self.client.get("/pdfs")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "PDF storage unavailable."})

    def test_openapi_documents_all_endpoints_and_pdf_media_type(self):
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(
            set(schema["paths"]),
            {"/search", "/scrap", "/pdfs", "/pdfs/generate", "/pdfs/{name}"},
        )
        content = schema["paths"]["/pdfs/{name}"]["get"]["responses"]["200"]["content"]
        self.assertIn("application/pdf", content)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_contact_filter_and_csv_search(self):
        handler = Mock()
        handler.search.return_value = json.dumps(
            [{"name": "Cafe", "email": "hi@example.org"}]
        )
        self.app.dependency_overrides[get_scrap_handler] = lambda: handler
        response = self.client.get(
            "/search",
            params=[
                ("center", "0,0"),
                ("category", "cafe"),
                ("radius_m", "100"),
                ("has_contact", "email"),
                ("has_contact", "instagram"),
                ("sort", "source"),
                ("enrich_website", "false"),
                ("format", "csv"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertEqual(
            list(csv.DictReader(io.StringIO(response.text)))[0]["email"],
            "hi@example.org",
        )
        handler.search.assert_called_once_with(
            "0,0",
            "cafe",
            100,
            None,
            contacts=("email", "instagram"),
            sort_by_distance=False,
            enrich_website=False,
        )
        response = self.client.get(
            "/search",
            params={
                "center": "0,0",
                "category": "cafe",
                "radius_m": 100,
                "has_contact": "fax",
            },
        )
        self.assertEqual(response.status_code, 422)
