"""Filtering invalid input must preserve both saved results and their audit."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "filter_businesses",
    Path(__file__).resolve().parents[1] / "scripts/filter_businesses.py",
)
filter_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(filter_cli)


class FilterCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.input = self.root / "places.json"
        self.source = self.root / "source.json"
        self.output = self.root / "filtered.json"
        self.audit = self.root / "audit.json"
        self.reviews = self.root / "reviews.json"
        self.input.write_text(
            json.dumps([{"osm_id": "node/1", "name": "Cafe", "phone": "+380321234567"}])
        )
        self.source.write_text(
            json.dumps(
                {
                    "elements": [
                        {
                            "type": "node",
                            "id": 1,
                            "tags": {
                                "name": "Cafe",
                                "amenity": "cafe",
                                "phone": "+380321234567",
                            },
                        }
                    ]
                }
            )
        )
        self.output.write_text("original results")
        self.audit.write_text("original audit")

    def run_command(self, extra=(), output=None, audit=None):
        error = io.StringIO()
        with redirect_stderr(error), redirect_stdout(io.StringIO()):
            code = filter_cli.main(
                [
                    str(self.input),
                    str(self.source),
                    str(output or self.output),
                    "--audit",
                    str(audit or self.audit),
                    *extra,
                ]
            )
        if code:
            self.assertIn("error", json.loads(error.getvalue()))
            self.assertNotIn("Traceback", error.getvalue())
        return code

    def assert_originals(self):
        self.assertEqual(self.output.read_text(), "original results")
        self.assertEqual(self.audit.read_text(), "original audit")
        self.assertEqual(list(self.root.glob(".gmscrap-*")), [])

    def test_malformed_results_do_not_overwrite_saved_files(self):
        for invalid in (
            {},
            [1],
            [{"osm_id": "bad"}],
            [{"osm_id": "node/1", "phone": 123}],
            [{"osm_id": "node/1", "latitude": 91}],
        ):
            with self.subTest(invalid=invalid):
                self.input.write_text(json.dumps(invalid))
                self.assertEqual(self.run_command(), 1)
                self.assert_originals()

    def test_invalid_source_and_reviews_are_reported_without_tracebacks(self):
        original = self.source.read_text()
        self.source.write_text('{"elements":null}')
        self.assertEqual(self.run_command(), 1)
        self.assert_originals()
        self.source.write_text('{"elements":[],"osm3s":null}')
        self.assertEqual(self.run_command(), 1)
        self.assert_originals()
        self.source.write_text(original)
        for review in (
            [],
            {"rejected_contacts": [1]},
            {"rejected_contacts": [{"osm_id": "node/1", "field": "fax", "value": "x"}]},
            {
                "rejected_contacts": [
                    {"osm_id": "node/1", "field": "phone", "value": "bad"}
                ]
            },
        ):
            self.reviews.write_text(json.dumps(review))
            self.assertEqual(self.run_command(("--reviews", str(self.reviews))), 1)
            self.assert_originals()

    def test_output_paths_cannot_alias_each_other_or_inputs(self):
        self.assertEqual(self.run_command(audit=self.output), 1)
        previous = self.input.read_bytes()
        self.assertEqual(self.run_command(output=self.input), 1)
        self.assertEqual(self.input.read_bytes(), previous)
        self.assert_originals()

    def test_audit_staging_failure_preserves_existing_results(self):
        self.assertEqual(self.run_command(audit=self.root / "missing/audit.json"), 1)
        self.assert_originals()

    def test_second_replace_failure_rolls_back_first_file(self):
        original_replace = Path.replace

        def replace(path, destination):
            if destination == self.audit:
                raise PermissionError("Audit target unavailable")
            return original_replace(path, destination)

        with patch.object(Path, "replace", replace):
            self.assertEqual(self.run_command(), 1)
        self.assert_originals()

    def test_success_and_formatted_contact_review(self):
        self.assertEqual(self.run_command(), 0)
        self.assertEqual(len(json.loads(self.output.read_text())), 1)
        self.assertEqual(json.loads(self.audit.read_text())["included_count"], 1)
        self.reviews.write_text(
            json.dumps(
                {
                    "rejected_contacts": [
                        {
                            "osm_id": "node/1",
                            "field": "phone",
                            "value": "+380 (32) 123-45-67",
                        }
                    ]
                }
            )
        )
        self.assertEqual(self.run_command(("--reviews", str(self.reviews))), 0)
        self.assertEqual(json.loads(self.output.read_text()), [])
        self.assertEqual(
            json.loads(self.audit.read_text())["exclusion_reasons"],
            {"contact_ownership_uncertain": 1},
        )
