"""Validated inputs and place data, independent of network clients and JSON."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

CATEGORIES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "coffee shop": ("amenity", "cafe"),
        "cafe": ("amenity", "cafe"),
        "restaurant": ("amenity", "restaurant"),
        "bar": ("amenity", "bar"),
        "pharmacy": ("amenity", "pharmacy"),
        "supermarket": ("shop", "supermarket"),
    }
)


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        for value, limit in ((self.latitude, 90), (self.longitude, 180)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not -limit <= value <= limit
            ):
                raise ValueError(
                    "Coordinates are outside the valid latitude/longitude range."
                )


def parse_center(center: str) -> Coordinates | str:
    """Return validated coordinates or a trimmed city query."""
    if not isinstance(center, str):
        raise TypeError("center must be coordinates or a city name.")
    center = center.strip()
    if not center:
        raise ValueError("center must not be empty.")
    parts = center.split(",")
    try:
        float(parts[0])
    except ValueError:
        return center
    if len(parts) != 2:
        raise ValueError('Coordinates must use "latitude, longitude".')
    try:
        latitude, longitude = (float(part.strip()) for part in parts)
    except ValueError as error:
        raise ValueError("Coordinates must be numbers.") from error
    return Coordinates(latitude, longitude)


@dataclass(frozen=True)
class SearchRequest:
    center: str
    category: str
    radius_m: int
    name: str | None = None
    contacts: tuple[str, ...] = ()
    sort_by_distance: bool = True
    enrich_website: bool = True
    origin: Coordinates | str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.category, str):
            raise TypeError("category must be a string.")
        if any(value not in CATEGORIES for value in self.categories):
            raise ValueError(f"Supported categories: {', '.join(CATEGORIES)}")
        if isinstance(self.radius_m, bool) or not isinstance(self.radius_m, int):
            raise TypeError("radius_m must be an integer number of meters.")
        if self.radius_m <= 0:
            raise ValueError("radius_m must be greater than zero.")
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("name must be a string or None.")
        if not isinstance(self.contacts, tuple) or any(
            value not in ("email", "instagram", "facebook", "website", "phone")
            for value in self.contacts
        ):
            raise ValueError(
                "contacts must be a tuple of email, instagram, facebook, website, phone."
            )
        if not isinstance(self.sort_by_distance, bool) or not isinstance(
            self.enrich_website, bool
        ):
            raise TypeError("sort_by_distance and enrich_website must be booleans.")
        object.__setattr__(self, "origin", parse_center(self.center))

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(value.strip().casefold() for value in self.category.split(","))

    @property
    def tags(self) -> tuple[tuple[str, str], ...]:
        return tuple(dict.fromkeys(CATEGORIES[value] for value in self.categories))


@dataclass(frozen=True)
class Place:
    osm_id: str
    name: str | None
    latitude: float | None
    longitude: float | None
    website: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    email: str | None = None
    address: str | None = None
    google_maps_url: str | None = None
    distance_m: float | None = None
    phone: str | None = None
