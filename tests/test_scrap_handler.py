import unittest
from unittest.mock import Mock

from my_package.handlers.respon.interface_respon import IErrorResponse
from my_package.handlers.scrap.scrap import ScrapHandler
from my_package.services.interface_scrap import IScrapService


class ScrapHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock(spec=IScrapService)
        self.handler = ScrapHandler(self.service)

    def test_valid_parameters_reach_service(self) -> None:
        for geo, keywords, radius in (
            ("50.4501, 30.5234", "cafe, restaurant", 5),
            ("-90, -180", "cafe", 1),
            ("90, 180", "coffee shop, restaurant", 10),
        ):
            with self.subTest(geo=geo, keywords=keywords, radius=radius):
                result = self.handler.scrape(geo, keywords, radius)
                self.assertIs(result, self.service.scrape.return_value)
                self.service.scrape.assert_called_with(geo, keywords, radius)

    def test_invalid_parameters_never_reach_service(self) -> None:
        invalid_parameters = (
            ("geo", "", ValueError),
            ("geo", "Kyiv", ValueError),
            ("geo", "50,30,10", ValueError),
            ("geo", "50,", ValueError),
            ("geo", "91,30", ValueError),
            ("geo", "-91,30", ValueError),
            ("geo", "50,181", ValueError),
            ("geo", "50,-181", ValueError),
            ("geo", "nan,30", ValueError),
            ("geo", "50,inf", ValueError),
            ("geo", None, TypeError),
            ("key_word", "", ValueError),
            ("key_word", "   ", ValueError),
            ("key_word", ",cafe", ValueError),
            ("key_word", "cafe,", ValueError),
            ("key_word", "cafe, ,restaurant", ValueError),
            ("key_word", ["cafe"], TypeError),
            ("radius_in_km", 0, ValueError),
            ("radius_in_km", -1, ValueError),
            ("radius_in_km", 1.5, TypeError),
            ("radius_in_km", "5", TypeError),
            ("radius_in_km", True, TypeError),
            ("radius_in_km", None, TypeError),
        )
        for parameter, value, error in invalid_parameters:
            with self.subTest(parameter=parameter, value=value):
                arguments = dict(
                    geo="50.4501, 30.5234", key_word="cafe", radius_in_km=5
                )
                arguments[parameter] = value
                with self.assertRaises(error):
                    self.handler.scrape(**arguments)
                self.service.scrape.assert_not_called()

    def test_handler_uses_injected_error_responses(self) -> None:
        cases = (
            ("geo", None, "geo_type_error", TypeError),
            ("geo", "50", "geo_format_error", ValueError),
            ("geo", "abc,30", "geo_coordinates_error", ValueError),
            ("geo", "91,30", "geo_range_error", ValueError),
            ("key_word", None, "key_word_type_error", TypeError),
            ("key_word", "cafe,", "key_word_empty_error", ValueError),
            ("radius_in_km", True, "radius_type_error", TypeError),
            ("radius_in_km", 0, "radius_value_error", ValueError),
        )
        for parameter, value, method_name, error_type in cases:
            with self.subTest(method=method_name):
                responses = Mock(spec=IErrorResponse)
                response_method = getattr(responses, method_name)
                expected_error = error_type("custom validation message")
                response_method.return_value = expected_error
                handler = ScrapHandler(self.service, responses)
                arguments = dict(geo="50,30", key_word="cafe", radius_in_km=5)
                arguments[parameter] = value

                with self.assertRaises(error_type) as raised:
                    handler.scrape(**arguments)

                self.assertIs(raised.exception, expected_error)
                response_method.assert_called_once_with()
                self.service.scrape.assert_not_called()
                if method_name == "geo_coordinates_error":
                    self.assertIsInstance(raised.exception.__cause__, ValueError)


if __name__ == "__main__":
    unittest.main()
