"""Search orchestration without knowledge of HTTP, geopy, or serialization."""

from dataclasses import replace
from math import asin, cos, radians, sin, sqrt
from time import monotonic

from my_package.application.ports import ContactEnricher, Geocoder, PlaceSource
from my_package.domain.links import (
    CONTACT_FIELDS,
    business_maps_url,
    normalize_contacts,
)
from my_package.domain.models import Coordinates, Place, SearchRequest


class SearchPlaces:
    def __init__(
        self,
        geocoder: Geocoder,
        place_source: PlaceSource,
        contact_enricher: ContactEnricher | None = None,
    ) -> None:
        self.geocoder = geocoder
        self.place_source = place_source
        self.contact_enricher = contact_enricher

    def execute(self, request: SearchRequest) -> list[Place]:
        center = request.origin
        if not isinstance(center, Coordinates):
            center = self.geocoder.geocode(center)
        places = self.place_source.search(request, center)
        name_filter = (
            request.name.strip().casefold() if request.name is not None else ""
        )
        places = [
            place
            for place in places
            if not name_filter or name_filter in (place.name or "").casefold()
        ]
        results = []
        enrichment_deadline = monotonic() + 30
        enriched_websites = {}
        for place in places:
            place = replace(
                place,
                **normalize_contacts(
                    (key, getattr(place, key)) for key in CONTACT_FIELDS
                ),
            )
            if request.enrich_website and self.contact_enricher is not None:
                # Cache by original contacts as well: different OSM values can alter
                # which pages need fetching. Never transfer one venue's OSM tags.
                cache_key = (
                    place.website,
                    place.email,
                    place.instagram,
                    place.facebook,
                )
                if place.website and cache_key in enriched_websites:
                    cached = enriched_websites[cache_key]
                    place = replace(place, **cached)
                elif monotonic() < enrichment_deadline:
                    enriched = self.contact_enricher.enrich(place)
                    enriched_websites[cache_key] = (
                        {
                            key: getattr(enriched, key)
                            for key in ("email", "instagram", "facebook")
                        }
                        if place.website
                        else {}
                    )
                    place = enriched
            place = replace(
                place,
                **normalize_contacts(
                    (key, getattr(place, key)) for key in CONTACT_FIELDS
                ),
            )
            place = replace(
                place,
                google_maps_url=business_maps_url(
                    place.name,
                    place.latitude,
                    place.longitude,
                    place.address,
                    existing=place.google_maps_url,
                ),
            )
            if request.contacts and not any(
                (getattr(place, field) or "").strip() for field in request.contacts
            ):
                continue
            if place.latitude is not None and place.longitude is not None:
                lat, lon = radians(place.latitude), radians(place.longitude)
                origin_lat, origin_lon = (
                    radians(center.latitude),
                    radians(center.longitude),
                )
                a = (
                    sin((lat - origin_lat) / 2) ** 2
                    + cos(lat) * cos(origin_lat) * sin((lon - origin_lon) / 2) ** 2
                )
                place = replace(
                    place,
                    distance_m=round(6371008.8 * 2 * asin(sqrt(min(1, a))), 2),
                )
            results.append(place)
        if request.sort_by_distance:
            results.sort(
                key=lambda place: (
                    place.distance_m if place.distance_m is not None else float("inf")
                )
            )
        return results
