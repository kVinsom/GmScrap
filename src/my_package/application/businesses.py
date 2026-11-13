"""Select named cafe businesses with usable contacts and source evidence."""

from my_package.domain.businesses import (
    BUSINESS_CONTACTS,
    cafe_exclusion_reason,
    has_business_contact,
)
from my_package.domain.links import normalize_contacts


def select_contactable_cafes(
    places: list[dict],
    source_elements: list[dict],
    *,
    rejected_contacts: dict[str, dict[str, str]] | None = None,
) -> tuple[list[dict], list[dict]]:
    sources = {
        f"{element['type']}/{element['id']}": element for element in source_elements
    }
    included, excluded = [], []
    for original in places:
        place = dict(original)
        contact_rejected = False
        source = sources.get(place.get("osm_id"))
        reason = (
            "source_evidence_missing"
            if source is None
            else cafe_exclusion_reason(source.get("tags", {}))
        )
        if source is not None:
            tags = source.get("tags", {})
            candidates = [(key, place.get(key)) for key in BUSINESS_CONTACTS]
            candidates += [
                (field, tags.get(key))
                for field in BUSINESS_CONTACTS
                for key in ("contact:" + field, field)
            ]
            candidates += [
                ("phone", tags.get(key)) for key in ("contact:mobile", "mobile")
            ]
            place.update(normalize_contacts(candidates))
            # Maps links are not a contact method and are preserved separately.
            place["google_maps_url"] = original.get("google_maps_url")
            for field, value in (
                (rejected_contacts or {}).get(place.get("osm_id"), {}).items()
            ):
                if field in BUSINESS_CONTACTS and place.get(field) == value:
                    place[field] = None
                    contact_rejected = True
        if reason is None and not (place.get("name") or "").strip():
            reason = "business_identity_missing"
        if reason is None and not has_business_contact(place):
            reason = (
                "contact_ownership_uncertain"
                if contact_rejected
                else "no_valid_business_contacts"
            )
        if reason is not None:
            excluded.append(
                {
                    "osm_id": place.get("osm_id"),
                    "name": place.get("name"),
                    "reason": reason,
                }
            )
        else:
            included.append(place)
    return included, excluded
