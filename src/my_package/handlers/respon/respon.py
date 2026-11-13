class ErrorResponse:
    """Create validation errors for the scraping handler."""

    def geo_type_error(self) -> TypeError:
        return TypeError('geo must be a string in the format "latitude, longitude".')

    def geo_format_error(self) -> ValueError:
        return ValueError('geo must use the format "latitude, longitude".')

    def geo_coordinates_error(self) -> ValueError:
        return ValueError("geo coordinates must be numbers.")

    def geo_range_error(self) -> ValueError:
        return ValueError(
            "Latitude must be between -90 and 90, "
            "and longitude must be between -180 and 180."
        )

    def key_word_type_error(self) -> TypeError:
        return TypeError("key_word must be a string of comma-separated search terms.")

    def key_word_empty_error(self) -> ValueError:
        return ValueError("Comma-separated search terms must not be empty.")

    def radius_type_error(self) -> TypeError:
        return TypeError("radius_in_km must be an integer.")

    def radius_value_error(self) -> ValueError:
        return ValueError("The search radius must be greater than 0 km.")
