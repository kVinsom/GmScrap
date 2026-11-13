"""Pure translation between Overpass data and domain models."""

from my_package.domain.errors import OverpassError
from my_package.domain.links import normalize_contacts
from my_package.domain.models import Coordinates, Place, SearchRequest


def build_query(request: SearchRequest, center: Coordinates) -> str:
    filters = [
        f'nwr["{key}"="{value}"]'
        f"(around:{request.radius_m},{center.latitude},{center.longitude});"
        for key, value in request.tags
    ]
    selection = filters[0] if len(filters) == 1 else "(" + "".join(filters) + ");"
    return "[out:json][timeout:25];\n" + selection + "\nout center;"


def parse_response(payload: object) -> list[Place]:
    if not isinstance(payload, dict):
        raise OverpassError("Overpass returned an invalid response.")
    if payload.get("remark"):
        raise OverpassError(f"Overpass query failed: {payload['remark']}")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("Overpass response is missing the elements list.")
    return [parse_element(element) for element in elements]


def parse_element(element: object) -> Place:
    if not isinstance(element, dict):
        raise OverpassError("Overpass returned an invalid element.")
    tags = element.get("tags", {})
    if not isinstance(tags, dict) or any(
        not isinstance(value, str) for value in tags.values()
    ):
        raise OverpassError("Overpass returned invalid tags.")
    element_type = element.get("type")
    element_id = element.get("id")
    if element_type not in ("node", "way", "relation") or (
        isinstance(element_id, bool)
        or not isinstance(element_id, int)
        or element_id <= 0
    ):
        raise OverpassError("Overpass returned an invalid element identity.")
    coordinates = element if element_type == "node" else element.get("center", {})
    if not isinstance(coordinates, dict):
        raise OverpassError("Overpass returned an invalid element center.")
    for key, limit in (("lat", 90), ("lon", 180)):
        value = coordinates.get(key)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not -limit <= value <= limit
        ):
            raise OverpassError("Overpass returned invalid coordinates.")
    contacts = normalize_contacts(
        (field, tags.get(key))
        for field in ("website", "instagram", "facebook", "email", "phone")
        for key in ("contact:" + field, field)
    )
    if not contacts["phone"]:
        contacts["phone"] = normalize_contacts(
            ("phone", tags.get(key)) for key in ("contact:mobile", "mobile")
        )["phone"]
    return Place(
        osm_id=f"{element_type}/{element_id}",
        name=tags.get("name"),
        latitude=coordinates.get("lat"),
        longitude=coordinates.get("lon"),
        **contacts,
        address=tags.get("addr:full")
        or ", ".join(
            value
            for value in (
                " ".join(
                    filter(
                        None,
                        (
                            tags.get("addr:street") or tags.get("addr:place"),
                            tags.get("addr:housenumber"),
                        ),
                    )
                ),
                tags.get("addr:city"),
                tags.get("addr:postcode"),
                tags.get("addr:country"),
            )
            if value
        )
        or None,
    )
