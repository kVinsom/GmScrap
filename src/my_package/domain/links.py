"""Classify contacts and construct business-oriented Google Maps links."""

import ipaddress
import re
from collections.abc import Iterable
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

EMAIL = re.compile(
    r"(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Z0-9-]{1,63}(?:\.[A-Z0-9-]{1,63})+",
    re.I,
)
CONTACT_FIELDS = (
    "website",
    "email",
    "facebook",
    "instagram",
    "google_maps_url",
    "phone",
)
SOCIAL_DOMAINS = {
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "instagram": ("instagram.com", "instagr.am"),
}
OTHER_SOCIAL = (
    "tiktok.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "t.me",
    "wa.me",
)
NON_PROFILE = {
    "share",
    "sharer",
    "sharer.php",
    "dialog",
    "p",
    "reel",
    "reels",
    "stories",
    "accounts",
    "login",
    "login.php",
    "intent",
    "l.php",
    "plugins",
    "explore",
    "direct",
}


def _domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def classify_contact(value: str, field: str) -> tuple[str, str] | None:
    value = value.strip()
    if not value:
        return None
    if field == "phone" or value.lower().startswith("tel:"):
        phone = (
            unquote(value[4:] if value.lower().startswith("tel:") else value)
            .split(";", 1)[0]
            .strip()
        )
        digits = re.sub(r"[^0-9]", "", phone)
        if re.fullmatch(r"\+?[0-9 ()\-.]+", phone) and 7 <= len(digits) <= 15:
            return "phone", ("+" if phone.startswith("+") else "") + digits
        if value.lower().startswith("tel:") or re.fullmatch(r"[+0-9 ()\-.;]+", value):
            return None
        # A URL mislabelled as a phone still needs routing to its actual field.
        if not any(marker in value.lower() for marker in ("http", ".", "mailto:")):
            return None
    email = (
        unquote(value[7:].split("?", 1)[0])
        if value.lower().startswith("mailto:")
        else value
    )
    if EMAIL.fullmatch(email):
        return "email", email
    # A bare username has meaning only in an explicitly labelled social field.
    if (
        field in SOCIAL_DOMAINS
        and re.fullmatch(r"@?[\w.-]+", value)
        and any(char.isalnum() for char in value)
        and ".com" not in value.lower()
    ):
        return field, value
    if any(char.isspace() or ord(char) < 32 for char in value):
        return None
    candidate = (
        value
        if "://" in value
        else "https:" + value
        if value.startswith("//")
        else "https://" + value
    )
    try:
        parts = urlsplit(candidate)
        host = (
            unquote(parts.hostname or "")
            .rstrip(".")
            .encode("idna")
            .decode("ascii")
            .lower()
        )
        if (
            parts.scheme.lower() not in {"http", "https"}
            or not host
            or "." not in host
            or parts.username is not None
            or parts.password is not None
        ):
            return None
        if parts.port == 0:
            return None
        if re.fullmatch(r"[0-9.]+", host):
            ipaddress.ip_address(host)
    except ValueError, UnicodeError:
        return None
    for kind, domains in SOCIAL_DOMAINS.items():
        if any(_domain(host, domain) for domain in domains):
            path = unquote(parts.path).strip("/")
            if not path or path.split("/")[0].lower() in NON_PROFILE:
                return None
            if path.lower() == "profile.php" and not parse_qs(parts.query).get("id"):
                return None
            return kind, value
    if (
        (
            host in {"google.com", "www.google.com", "maps.google.com"}
            and (host == "maps.google.com" or parts.path.startswith("/maps"))
        )
        or host == "maps.app.goo.gl"
        or (host == "goo.gl" and parts.path.startswith("/maps/"))
    ):
        return "google_maps_url", candidate
    if any(_domain(host, domain) for domain in OTHER_SOCIAL):
        return None
    return "website", value


def normalize_contacts(
    candidates: Iterable[tuple[str, str | None]],
) -> dict[str, str | None]:
    """Prefer valid dedicated fields, then relocate mislabelled contacts."""
    result = dict.fromkeys(CONTACT_FIELDS)
    relocated = []
    for field, value in candidates:
        if not isinstance(value, str):
            continue
        for entry in re.split(r"[\r\n]+|;\s*(?=https?://|mailto:)", value, flags=re.I):
            classified = classify_contact(entry, field)
            if classified is None:
                continue
            kind, contact = classified
            if kind == field:
                result[kind] = result[kind] or contact
            else:
                relocated.append((kind, contact))
    for kind, contact in relocated:
        result[kind] = result[kind] or contact
    return result


def business_maps_url(
    name: str | None,
    latitude: float | None,
    longitude: float | None,
    address: str | None = None,
    *,
    existing: str | None = None,
    place_id: str | None = None,
) -> str | None:
    """Use exact business identifiers when supplied, otherwise a named search."""
    if existing:
        classified = classify_contact(existing, "google_maps_url")
        if classified and classified[0] == "google_maps_url":
            parts = urlsplit(classified[1])
            query = parse_qs(parts.query)
            if (
                query.get("query_place_id")
                or query.get("cid")
                or (parts.path.startswith("/maps/place/") and "/data=" in parts.path)
                or parts.hostname in {"maps.app.goo.gl", "goo.gl"}
            ):
                return classified[1]
    terms = [value.strip() for value in (name, address) if value and value.strip()]
    if latitude is not None and longitude is not None:
        terms.append(f"{latitude},{longitude}")
    if not terms and place_id and place_id.strip():
        terms.append(place_id.strip())
    if not terms:
        return None
    parameters = {"api": "1", "query": ", ".join(terms)}
    if place_id and place_id.strip():
        parameters["query_place_id"] = place_id.strip()
    return "https://www.google.com/maps/search/?" + urlencode(
        parameters, quote_via=quote, safe=","
    )
