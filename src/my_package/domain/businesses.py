"""Conservative source-tag checks for a cafe business contact list."""

from collections.abc import Mapping

from my_package.domain.links import normalize_contacts

BUSINESS_CONTACTS = ("website", "email", "facebook", "instagram", "phone")
INACTIVE = (
    "disused",
    "abandoned",
    "demolished",
    "removed",
    "razed",
    "proposed",
    "planned",
    "construction",
    "was",
)


def cafe_exclusion_reason(tags: Mapping[str, str]) -> str | None:
    """An architectural outline alone is not a cafe; a cafe can occupy a building."""
    if tags.get("amenity", "").strip().lower() != "cafe":
        return "not_tagged_as_cafe_business"
    if any(
        tags.get(key, "").strip().lower() not in {"", "no", "false", "0"}
        for key in ("highway", "place", "boundary", "waterway")
    ):
        return "street_or_geographical_feature"
    if any(
        tags.get(prefix, "").strip().lower() not in {"", "no", "false", "0"}
        or tags.get(prefix + ":amenity") == "cafe"
        for prefix in INACTIVE
    ):
        return "inactive_or_planned_business"
    if tags.get("opening_hours", "").strip().lower() == "closed":
        return "inactive_or_planned_business"
    # Ambiguous combined landmark/cafe objects need individual verification.
    if (
        tags.get("historic", "").lower() not in {"", "no"}
        or tags.get("tourism", "").lower()
        in {"attraction", "artwork", "museum", "viewpoint", "gallery"}
        or tags.get("man_made", "").lower()
        in {"tower", "monument", "obelisk", "statue"}
    ):
        return "landmark_or_ambiguous_structure"
    if not any(
        tags.get(key, "").strip() for key in ("name", "name:en", "brand", "operator")
    ):
        return "business_identity_missing"
    return None


def has_business_contact(record: Mapping[str, object]) -> bool:
    contacts = normalize_contacts((key, record.get(key)) for key in BUSINESS_CONTACTS)
    return any(contacts[key] for key in BUSINESS_CONTACTS)
