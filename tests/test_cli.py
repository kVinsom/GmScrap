import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import requests

from my_package import __version__
from my_package.main import main


class CliIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.arguments = [
            "--center",
            "49.8419,24.0315",
            "--category",
            "coffee shop",
            "--radius",
            "2000",
        ]
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        for redirect in (redirect_stdout(self.stdout), redirect_stderr(self.stderr)):
            self.enterContext(redirect)
        self.post = self.enterContext(
            patch("my_package.infrastructure.overpass.requests.post")
        )
        self.geocoder = self.enterContext(
            patch("my_package.infrastructure.geocoding.Nominatim")
        )
        self.post.return_value.json.return_value = {"elements": []}

    def test_full_coordinate_search_outputs_json(self) -> None:
        self.post.return_value.json.return_value = {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 49,
                    "lon": 24,
                    "tags": {"name": "Lviv coffee"},
                }
            ]
        }
        self.assertEqual(main(self.arguments + ["--name", "lviv"]), 0)
        result = json.loads(self.stdout.getvalue())
        self.assertEqual(result[0]["name"], "Lviv coffee")
        self.assertIsNone(result[0]["website"])
        self.assertEqual(self.stderr.getvalue(), "")
        self.geocoder.assert_not_called()

    def test_full_city_search_outputs_empty_success(self) -> None:
        self.arguments[1] = "Lviv, Ukraine"
        self.geocoder.return_value.geocode.return_value = Mock(
            latitude=49, longitude=24
        )
        self.assertEqual(main(self.arguments), 0)
        self.assertEqual(json.loads(self.stdout.getvalue()), [])
        self.assertEqual(self.stderr.getvalue(), "")
        self.geocoder.return_value.geocode.assert_called_once_with(
            "Lviv, Ukraine", exactly_one=True
        )

    def test_http_failure_is_json_error_and_nonzero_exit(self) -> None:
        self.post.return_value.raise_for_status.side_effect = requests.HTTPError("502")
        self.assertEqual(main(self.arguments), 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertIn("502", json.loads(self.stderr.getvalue())["error"])

    def test_city_not_found_is_json_error(self) -> None:
        self.arguments[1] = "Missing city"
        self.geocoder.return_value.geocode.return_value = None
        self.assertEqual(main(self.arguments), 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertIn("City not found", json.loads(self.stderr.getvalue())["error"])
        self.post.assert_not_called()

    def test_search_validation_errors_exit_one(self) -> None:
        for index, value in ((1, "91,24"), (3, "unknown"), (5, "0"), (5, "-1")):
            with self.subTest(index=index, value=value):
                arguments = self.arguments.copy()
                arguments[index] = value
                self.stderr.seek(0)
                self.stderr.truncate()
                self.assertEqual(main(arguments), 1)
                self.assertIn("error", json.loads(self.stderr.getvalue()))
        self.assertEqual(self.stdout.getvalue(), "")
        self.post.assert_not_called()
        self.geocoder.assert_not_called()

    def test_argument_syntax_errors_exit_two_without_network(self) -> None:
        for arguments in (
            [],
            self.arguments[:2],
            self.arguments[:-2],
            self.arguments[:-1] + ["abc"],
            self.arguments[:-1] + ["1.5"],
            self.arguments + ["--unknown"],
            self.arguments + ["--name"],
        ):
            with self.subTest(arguments=arguments):
                self.stderr.seek(0)
                self.stderr.truncate()
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("usage:", self.stderr.getvalue())
        self.assertEqual(self.stdout.getvalue(), "")
        self.post.assert_not_called()
        self.geocoder.assert_not_called()

    def test_help_exits_zero_without_network(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        for option in ("--center", "--category", "--radius", "--name"):
            self.assertIn(option, self.stdout.getvalue())
        self.assertEqual(self.stderr.getvalue(), "")
        self.post.assert_not_called()
        self.geocoder.assert_not_called()

    def test_version_exits_zero_without_network(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(self.stdout.getvalue().strip(), f"gmscrap {__version__}")
        self.assertEqual(self.stderr.getvalue(), "")
        self.post.assert_not_called()
        self.geocoder.assert_not_called()

    def test_interrupt_returns_130_and_json_error(self) -> None:
        self.post.side_effect = KeyboardInterrupt
        self.assertEqual(main(self.arguments), 130)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(
            json.loads(self.stderr.getvalue()), {"error": "Search interrupted."}
        )
