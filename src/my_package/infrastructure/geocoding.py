"""Nominatim adapter with lazy initialization and request throttling."""

from threading import Lock

from geopy.exc import GeopyError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from my_package.domain.errors import GeocodingError
from my_package.domain.models import Coordinates


class NominatimGeocoder:
    def __init__(self, user_agent: str = "GmScrap/0.1") -> None:
        self.user_agent = user_agent
        self._geocode: RateLimiter | None = None
        self._initialization_lock = Lock()

    def geocode(self, city: str) -> Coordinates:
        # The shared API adapter may be initialized by concurrent worker threads.
        with self._initialization_lock:
            return self._geocode_city(city)

    def _geocode_city(self, city: str) -> Coordinates:
        try:
            geocode = self._geocode
            if geocode is None:
                geocoder = Nominatim(user_agent=self.user_agent, timeout=10)
                geocode = RateLimiter(
                    geocoder.geocode,
                    min_delay_seconds=1,
                    max_retries=0,
                    swallow_exceptions=False,
                )
                self._geocode = geocode
            location = geocode(city, exactly_one=True)
        except GeopyError as error:
            raise GeocodingError(f"Geocoding request failed: {error}") from error
        if location is None:
            raise GeocodingError(f"City not found: {city}")
        try:
            return Coordinates(location.latitude, location.longitude)
        except ValueError as error:
            raise GeocodingError("Geocoder returned invalid coordinates.") from error
