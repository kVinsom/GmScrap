"""Compatibility facade: wire default adapters and serialize search results."""

import json
from dataclasses import asdict

from my_package.application.ports import ContactEnricher, Geocoder, PlaceSource
from my_package.application.search import SearchPlaces
from my_package.domain.errors import GeocodingError, OverpassError
from my_package.domain.models import SearchRequest
from my_package.infrastructure.geocoding import NominatimGeocoder
from my_package.infrastructure.overpass import OverpassPlaceSource
from my_package.infrastructure.website import WebsiteContactEnricher
from my_package.repositories.scrap import ScrapRepository

__all__ = ["GeocodingError", "OverpassError", "ScrapService"]


class ScrapService:
    def __init__(
        self,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        user_agent: str = "GmScrap/0.1",
        *,
        geocoder: Geocoder | None = None,
        place_source: PlaceSource | None = None,
        repository: ScrapRepository | None = None,
        contact_enricher: ContactEnricher | None = None,
    ) -> None:
        self.repository = ScrapRepository() if repository is None else repository
        self.search_places = SearchPlaces(
            contact_enricher=WebsiteContactEnricher(user_agent)
            if contact_enricher is None
            else contact_enricher,
            geocoder=NominatimGeocoder(user_agent) if geocoder is None else geocoder,
            place_source=(
                OverpassPlaceSource(endpoint, user_agent)
                if place_source is None
                else place_source
            ),
        )

    def search(
        self,
        center: str,
        category: str,
        radius_m: int,
        name: str | None = None,
        *,
        contacts: tuple[str, ...] = (),
        sort_by_distance: bool = True,
        enrich_website: bool = True,
    ) -> str:
        request = SearchRequest(
            center, category, radius_m, name, contacts, sort_by_distance, enrich_website
        )
        places = self.search_places.execute(request)
        return json.dumps(
            [asdict(place) for place in places],
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

    def scrape(self, geo: str, key_word: str, radius_in_km: int) -> str:
        """Preserve the original kilometer-based service API."""
        if isinstance(radius_in_km, bool) or not isinstance(radius_in_km, int):
            raise TypeError("radius_in_km must be an integer.")
        return self.search(geo, key_word, radius_in_km * 1000)

    @staticmethod
    def _validate_pdf_name(name: str) -> None:
        if not isinstance(name, str):
            raise TypeError("PDF name must be a string.")
        if not name.strip():
            raise ValueError("PDF name must not be empty.")

    def save_pdf(self, name: str, content: bytes) -> None:
        self._validate_pdf_name(name)
        if not isinstance(content, bytes):
            raise TypeError("PDF content must be bytes.")
        if not content.startswith(b"%PDF-"):
            raise ValueError("PDF content must start with a PDF header.")
        self.repository.save_pdf(name, content)

    def delete_pdf(self, name: str) -> bool:
        self._validate_pdf_name(name)
        return self.repository.delete_pdf(name)

    def get_pdf(self, name: str) -> bytes | None:
        self._validate_pdf_name(name)
        return self.repository.get_pdf(name)

    def get_all_pdfs(self) -> dict[str, bytes]:
        return self.repository.get_all_pdfs()
