"""Validate the existing application's JSON at the PDF boundary."""

import json
from pathlib import Path

from my_package.domain.models import Coordinates
from my_package.services.interface_pdf import IPdfService

TEXT_FIELDS = (
    "name",
    "website",
    "email",
    "phone",
    "facebook",
    "instagram",
    "address",
    "location",
    "google_maps_url",
    "google_place_id",
)


class PdfHandler:
    def __init__(self, service: IPdfService) -> None:
        self.service = service

    def generate(
        self, payload: str, output: str | Path, *, location: str | None = None
    ) -> Path:
        if not isinstance(payload, str):
            raise TypeError("PDF input must be a JSON string.")
        places = json.loads(payload)
        if not isinstance(places, list):
            raise ValueError("PDF input must be a JSON array of places.")
        if location is not None and not isinstance(location, str):
            raise TypeError("location must be a string or None.")
        for index, place in enumerate(places):
            if not isinstance(place, dict):
                raise ValueError(f"Place {index + 1} must be an object.")
            for key in TEXT_FIELDS:
                if place.get(key) is not None and not isinstance(place[key], str):
                    raise ValueError(f"Place {index + 1}: {key} must be text or null.")
            # Validate even a single provided coordinate; null pairs remain valid.
            Coordinates(
                0 if place.get("latitude") is None else place["latitude"],
                0 if place.get("longitude") is None else place["longitude"],
            )
        output = Path(output)
        if output.suffix.lower() != ".pdf":
            raise ValueError("Output filename must end in .pdf.")
        return self.service.generate(places, output, location=location)
