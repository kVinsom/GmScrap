"""Dependencies required by the search use case."""

from typing import Protocol

from my_package.domain.models import Coordinates, Place, SearchRequest


class Geocoder(Protocol):
    def geocode(self, city: str) -> Coordinates: ...


class PlaceSource(Protocol):
    def search(self, request: SearchRequest, center: Coordinates) -> list[Place]: ...


class ContactEnricher(Protocol):
    def enrich(self, place: Place) -> Place: ...
