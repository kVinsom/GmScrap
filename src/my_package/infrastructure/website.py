"""Best-effort extraction from a venue homepage and one linked contact page."""

import ipaddress
import re
import socket
import ssl
from dataclasses import replace
from email.message import Message
from html.parser import HTMLParser
from threading import Timer
from time import monotonic
from urllib.parse import unquote, urljoin, urlsplit

import idna
import requests
import urllib3
from urllib3.util import Timeout

from my_package.domain.links import (
    CONTACT_FIELDS,
    EMAIL,
    classify_contact,
    normalize_contacts,
)
from my_package.domain.models import Place

CONTACT = re.compile(r"contact", re.I)
MAX_BYTES = 1_000_000
PAGE_BUDGET_SECONDS = 10


class DeadlineSSLContext(ssl.SSLContext):
    """Give the TLS handshake only the time left after TCP and CA setup."""

    def __new__(cls, deadline: float):
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self, deadline: float):
        self.deadline = deadline

    def wrap_socket(self, *args, **kwargs):
        kwargs["do_handshake_on_connect"] = False
        wrapped = super().wrap_socket(*args, **kwargs)
        try:
            remaining = self.deadline - monotonic()
            if remaining <= 0:
                raise socket.timeout(
                    "Website page deadline exceeded before TLS handshake."
                )
            timeout = wrapped.gettimeout()
            wrapped.settimeout(
                remaining if timeout is None else min(timeout, remaining)
            )
            # SSLSocket.do_handshake uses a total timeout, including activity
            # during the handshake, rather than an inactivity timeout.
            wrapped.do_handshake()
            return wrapped
        except BaseException:
            wrapped.close()
            raise


class DeadlineConnection:
    """Interrupt socket I/O at the deadline, including slowly delivered headers."""

    def __init__(self, *args, deadline: float, deadline_timers: list[Timer], **kwargs):
        self.deadline = deadline
        self.deadline_timers = deadline_timers
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise urllib3.exceptions.ConnectTimeoutError(
                "Website page deadline exceeded before TCP connection."
            )
        self.timeout = (
            remaining if self.timeout is None else min(self.timeout, remaining)
        )
        return super()._new_conn()

    def connect(self):
        super().connect()
        if monotonic() >= self.deadline:
            self.close()
            raise socket.timeout(
                "Website page deadline exceeded during connection setup."
            )
        connected_socket = self.sock

        def interrupt():
            try:
                connected_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = Timer(max(0, self.deadline - monotonic()), interrupt)
        timer.daemon = True
        # The fetch owns cancellation. Connection.close() may run while the
        # response still reads this socket (notably with Connection: close).
        self.deadline_timers.append(timer)
        timer.start()


class DeadlineHTTPConnection(DeadlineConnection, urllib3.connection.HTTPConnection):
    pass


class DeadlineHTTPSConnection(DeadlineConnection, urllib3.connection.HTTPSConnection):
    pass


class ContactPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self.href: str | None = None
        self.label: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.label)))
            self.href = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.href is not None:
                self.label.append(data)


def public_addresses(url: str) -> list[str]:
    """Reject credentials, non-HTTP URLs and local/private network destinations."""
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            return []
        if parts.port not in (None, 80, 443):
            return []
        addresses = socket.getaddrinfo(
            parts.hostname,
            parts.port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        ips = list(dict.fromkeys(item[4][0] for item in addresses))
        return (
            ips if ips and all(ipaddress.ip_address(ip).is_global for ip in ips) else []
        )
    except ValueError, OSError:
        return []


def public_url(url: str) -> bool:
    return bool(public_addresses(url))


def normalize_url(url: str) -> str:
    """Use the same ASCII hostname for DNS, HTTP routing, and TLS verification."""
    parts = urlsplit(url)
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("Website URLs must have a hostname and no credentials.")
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        host = idna.encode(parts.hostname, uts46=True).decode("ascii")
    else:
        host = f"[{address}]" if address.version == 6 else str(address)
    default_port = {"http": 80, "https": 443}.get(parts.scheme)
    authority = host if parts.port in (None, default_port) else f"{host}:{parts.port}"
    return parts._replace(netloc=authority).geturl()


def decode_html(data: bytes, content_type: str) -> str:
    header = Message()
    header["content-type"] = content_type
    encoding = header.get_content_charset()
    if not encoding:
        meta = re.search(
            rb"<meta\b[^>]*charset\s*=\s*[\"']?\s*([\w-]+)", data[:8192], re.I
        )
        encoding = meta[1].decode("ascii") if meta else "utf-8-sig"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8-sig", errors="replace")


def page_link(base: str, href: str) -> str:
    try:
        link = urljoin(base, href)
        parts = urlsplit(link)
        if parts.scheme in ("http", "https") and parts.hostname:
            return normalize_url(link)
    except ValueError:
        pass
    return ""


class WebsiteContactEnricher:
    def __init__(self, user_agent: str = "GmScrap/0.1") -> None:
        self.user_agent = user_agent

    def _fetch(self, url: str) -> tuple[str, str] | None:
        deadline = monotonic() + PAGE_BUDGET_SECONDS
        for _ in range(4):
            url = normalize_url(url)
            addresses = public_addresses(url)
            for address in addresses:
                if monotonic() >= deadline:
                    return None
                try:
                    fetched = self._fetch_address(url, address, deadline)
                    break
                except (
                    urllib3.exceptions.NewConnectionError,
                    urllib3.exceptions.ConnectTimeoutError,
                ):
                    # Try other validated addresses, sharing the original budget.
                    continue
            else:
                return None
            if isinstance(fetched, str):
                url = fetched
                continue
            return fetched
        return None

    def _fetch_address(
        self, url: str, address: str, deadline: float
    ) -> tuple[str, str] | str | None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        timers: list[Timer] = []
        try:
            parts = urlsplit(url)
            # Connect to the validated numeric IP; retain the hostname for TLS and HTTP.
            pool_type = (
                urllib3.HTTPSConnectionPool
                if parts.scheme == "https"
                else urllib3.HTTPConnectionPool
            )
            tls = (
                dict(
                    server_hostname=parts.hostname,
                    assert_hostname=parts.hostname,
                    ca_certs=requests.certs.where(),
                    ssl_context=DeadlineSSLContext(deadline),
                )
                if parts.scheme == "https"
                else {}
            )
            with pool_type(
                address,
                port=parts.port,
                deadline=deadline,
                deadline_timers=timers,
                **tls,
            ) as pool:
                pool.ConnectionCls = (
                    DeadlineHTTPSConnection if tls else DeadlineHTTPConnection
                )
                response = pool.urlopen(
                    "GET",
                    parts.path or "/"
                    if not parts.query
                    else (parts.path or "/") + "?" + parts.query,
                    headers={"User-Agent": self.user_agent, "Host": parts.netloc},
                    timeout=Timeout(connect=min(3, remaining), read=min(5, remaining)),
                    preload_content=False,
                    redirect=False,
                    retries=False,
                )
                try:
                    if response.status in (301, 302, 303, 307, 308):
                        return urljoin(url, response.headers.get("Location", ""))
                    content_type = response.headers.get("Content-Type", "")
                    if response.status >= 400 or "html" not in content_type.lower():
                        return None
                    data = bytearray()
                    while monotonic() < deadline:
                        chunk = response.read1(16384, decode_content=True)
                        if not chunk:
                            return url, decode_html(data, content_type)
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            return None
                    return None
                finally:
                    response.close()
        finally:
            for timer in timers:
                timer.cancel()

    def enrich(self, place: Place) -> Place:
        place = replace(
            place,
            **normalize_contacts((key, getattr(place, key)) for key in CONTACT_FIELDS),
        )
        if not place.website or all((place.email, place.instagram, place.facebook)):
            return place
        website = place.website.strip()
        if "://" not in website:
            website = "https://" + website
        pending = website
        contacts = {
            field: getattr(place, field) for field in ("email", "instagram", "facebook")
        }
        for index in range(2):
            try:
                fetched = self._fetch(pending)
            except (
                requests.RequestException,
                urllib3.exceptions.HTTPError,
                ValueError,
                OSError,
            ):
                break
            if fetched is None:
                break
            url, html = fetched
            page = ContactPage()
            page.feed(html)
            for href, _ in page.links:
                if href.lower().startswith("mailto:") and not contacts["email"]:
                    match = EMAIL.search(unquote(href[7:].split("?", 1)[0]))
                    if match:
                        contacts["email"] = match.group()
                link = page_link(url, href)
                classified = classify_contact(link, "website") if link else None
                if classified and classified[0] in ("facebook", "instagram"):
                    field, value = classified
                    if not contacts[field]:
                        contacts[field] = value
            if not contacts["email"]:
                match = EMAIL.search(" ".join(page.text))
                if match:
                    contacts["email"] = match.group()
            if index or all(contacts.values()):
                break
            candidates = [
                page_link(url, href)
                for href, label in page.links
                if CONTACT.search(href + " " + label)
            ]
            pending = next(
                (
                    link
                    for link in candidates
                    if link
                    and urlsplit(link).netloc == urlsplit(url).netloc
                    and link.split("#")[0] != url.split("#")[0]
                ),
                "",
            )
            if not pending:
                break
        return replace(place, **contacts)
