"""Filter saved cafe results using original Overpass tags and valid contacts."""

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))

from my_package.application.businesses import select_contactable_cafes  # noqa: E402
from my_package.domain.businesses import BUSINESS_CONTACTS  # noqa: E402
from my_package.domain.errors import OverpassError  # noqa: E402
from my_package.domain.links import classify_contact  # noqa: E402
from my_package.domain.models import Coordinates  # noqa: E402
from my_package.infrastructure.osm import parse_response  # noqa: E402


def validate_places(places: object) -> list[dict]:
    if not isinstance(places, list):
        raise ValueError("Results must be a JSON array of places.")
    seen = set()
    for index, place in enumerate(places, 1):
        if not isinstance(place, dict):
            raise ValueError(f"Place {index} must be an object.")
        identity = place.get("osm_id")
        if not isinstance(identity, str) or not re.fullmatch(
            r"(?:node|way|relation)/[1-9][0-9]*", identity
        ):
            raise ValueError(f"Place {index} must have a valid osm_id.")
        if identity in seen:
            raise ValueError(f"Duplicate osm_id: {identity}")
        seen.add(identity)
        for field in (
            *BUSINESS_CONTACTS,
            "name",
            "address",
            "location",
            "google_maps_url",
        ):
            if place.get(field) is not None and not isinstance(place[field], str):
                raise ValueError(f"Place {index}: {field} must be text or null.")
        Coordinates(
            0 if place.get("latitude") is None else place["latitude"],
            0 if place.get("longitude") is None else place["longitude"],
        )
    return places


def validate_reviews(reviews: object) -> dict[str, dict[str, str]]:
    if not isinstance(reviews, dict) or not isinstance(
        reviews.get("rejected_contacts", []), list
    ):
        raise ValueError("Reviews must be an object with a rejected_contacts array.")
    rejected = {}
    for entry in reviews.get("rejected_contacts", []):
        if not isinstance(entry, dict):
            raise ValueError("Each rejected contact must be an object.")
        identity, field, value = (
            entry.get(key) for key in ("osm_id", "field", "value")
        )
        if not isinstance(identity, str) or not re.fullmatch(
            r"(?:node|way|relation)/[1-9][0-9]*", identity
        ):
            raise ValueError("Each rejected contact needs a valid osm_id.")
        if (
            not isinstance(field, str)
            or field not in BUSINESS_CONTACTS
            or not isinstance(value, str)
        ):
            raise ValueError(
                "Each rejected contact needs a supported field and text value."
            )
        contact = classify_contact(value, field)
        if contact is None or contact[0] != field:
            raise ValueError(
                f"Rejected contact value does not match its field: {field}"
            )
        previous = rejected.setdefault(identity, {}).get(field)
        if previous is not None and previous != contact[1]:
            raise ValueError(f"Conflicting contact reviews for {identity}: {field}")
        rejected[identity][field] = contact[1]
    return rejected


def write_outputs(contents: dict[Path, str]) -> None:
    """Stage both files before replacing either; restore commits on write failure."""
    staged, originals, committed = {}, {}, []
    try:
        for path, text in contents.items():
            originals[path] = path.read_bytes() if path.exists() else None
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".gmscrap-", delete=False
            ) as stream:
                staged[path] = Path(stream.name)
                stream.write(text.encode("utf-8"))
        for path, temporary in staged.items():
            temporary.replace(path)
            committed.append(path)
    except OSError:
        for path in reversed(committed):
            previous = originals[path]
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                with tempfile.NamedTemporaryFile(
                    dir=path.parent, prefix=".gmscrap-", delete=False
                ) as stream:
                    restore = Path(stream.name)
                    stream.write(previous)
                try:
                    restore.replace(path)
                finally:
                    restore.unlink(missing_ok=True)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Previously saved cafe results")
    parser.add_argument(
        "source", type=Path, help="Original Overpass response with tags"
    )
    parser.add_argument("output", type=Path, help="Filtered English JSON results")
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument(
        "--reviews",
        type=Path,
        help="Contact review evidence with rejected_contacts entries",
    )
    args = parser.parse_args(argv)
    try:
        protected = {
            path.resolve()
            for path in (args.input, args.source, args.reviews)
            if path is not None
        }
        if args.output.resolve() == args.audit.resolve() or any(
            path.resolve() in protected for path in (args.output, args.audit)
        ):
            raise ValueError(
                "Output and audit must be distinct paths and must not replace input files."
            )
        places = validate_places(json.loads(args.input.read_text(encoding="utf-8-sig")))
        source = json.loads(args.source.read_text(encoding="utf-8-sig"))
        parse_response(source)
        metadata = source.get("osm3s", {})
        if not isinstance(metadata, dict):
            raise ValueError("Source osm3s metadata must be an object.")
        reviews = (
            json.loads(args.reviews.read_text(encoding="utf-8-sig"))
            if args.reviews
            else {}
        )
        rejected_contacts = validate_reviews(reviews)
        included, excluded = select_contactable_cafes(
            places, source["elements"], rejected_contacts=rejected_contacts
        )
        audit = {
            "input_count": len(places),
            "included_count": len(included),
            "excluded_count": len(excluded),
            "source_timestamp": metadata.get("timestamp_osm_base"),
            "exclusion_reasons": dict(Counter(item["reason"] for item in excluded)),
            "excluded": excluded,
            "contact_reviews": reviews,
            "method": "Conservative source-tag screening, not independent confirmation of trading status. Named active cafe tags and at least one valid website, email, phone or social profile are required. Ambiguous landmark objects are excluded. Maps links and addresses do not count as contacts.",
        }
        write_outputs(
            {
                args.output: json.dumps(included, ensure_ascii=False, indent=2),
                args.audit: json.dumps(audit, ensure_ascii=False, indent=2),
            }
        )
    except (OSError, ValueError, TypeError, OverpassError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps({key: value for key, value in audit.items() if key != "excluded"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
