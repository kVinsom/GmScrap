"""Exercise the actual fetch loop with a controlled transport and clock."""

import socket
import ssl
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter, sleep
from unittest.mock import Mock, patch

import urllib3

from my_package.domain.models import Place
from my_package.infrastructure.website import (
    EMAIL,
    WebsiteContactEnricher,
    decode_html,
    normalize_url,
)

TLS_FIXTURES = Path(__file__).parent / "fixtures" / "tls"


IDNA_HOST = b"xn--80aaf4a.example".decode("idna")


class WebsiteSocketTests(unittest.TestCase):
    """Real sockets, with no global DNS mock and no access beyond loopback."""

    @contextmanager
    def server(self, mode="normal", *, tls=False):
        received = threading.Event()
        stop = threading.Event()
        requests = []
        server_names = []

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except ConnectionResetError, ssl.SSLEOFError:
                    # Hostname rejection and deadline shutdown can close TLS
                    # before a request is read, especially on Windows.
                    pass

            def do_GET(self):
                received.set()
                requests.append((self.headers.get("Host"), self.path))
                try:
                    if mode == "headers":
                        self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    elif mode == "chunked":
                        self.connection.sendall(
                            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n\r\n1;"
                        )
                    else:
                        body = b"<p>hello@example.org</p>"
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    # A finite safety limit prevents a broken deadline hanging CI.
                    for _ in range(50):
                        if stop.wait(0.02):
                            return
                        self.connection.sendall(b"a")
                    if mode == "chunked":
                        self.connection.sendall(b"\r\nx\r\n0\r\n\r\n")
                    else:
                        self.connection.sendall(b"\r\nContent-Length: 0\r\n\r\n")
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(
                TLS_FIXTURES / "server.pem", TLS_FIXTURES / "key.pem"
            )
            context.set_servername_callback(
                lambda sock, name, ctx: server_names.append(name)
            )
            server.socket = context.wrap_socket(server.socket, server_side=True)
        server.server_names = server_names
        self.server_names = server_names
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connect = socket.socket.connect

        def loopback_only(sock, address):
            if address[0] != "127.0.0.1":
                raise AssertionError(f"Unexpected non-loopback connection: {address}")
            return connect(sock, address)

        try:
            with patch.object(socket.socket, "connect", loopback_only):
                yield server.server_port, received, requests
        finally:
            stop.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def assert_deadline(self, mode, *, tls=False):
        with (
            self.server(mode, tls=tls) as (port, received, requests),
            patch(
                "my_package.infrastructure.website.requests.certs.where",
                return_value=str(TLS_FIXTURES / "server.pem"),
            ),
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["127.0.0.1"],
            ),
            patch("my_package.infrastructure.website.PAGE_BUDGET_SECONDS", 0.15),
        ):
            start = perf_counter()
            scheme = "https" if tls else "http"
            place = Place(
                "node/1", None, None, None, website=f"{scheme}://cafe.example:{port}"
            )
            self.assertEqual(WebsiteContactEnricher().enrich(place), place)
            elapsed = perf_counter() - start
            self.assertTrue(
                received.is_set(), "The request never reached the local server"
            )
            self.assertEqual(len(requests), 1)
            self.assertLess(
                elapsed, 0.65, "The deadline did not interrupt active socket I/O"
            )

    def test_socket_deadline_interrupts_slow_headers(self):
        self.assert_deadline("headers")

    def test_socket_deadline_survives_connection_close_during_chunked_body(self):
        self.assert_deadline("chunked")

    def test_https_deadline_interrupts_slow_headers(self):
        self.assert_deadline("headers", tls=True)

    def test_https_deadline_interrupts_slow_chunked_body(self):
        self.assert_deadline("chunked", tls=True)

    def test_tls_handshake_uses_budget_remaining_after_tcp_setup(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(8)
        port = listener.getsockname()[1]
        client_hello = threading.Event()
        stop = threading.Event()
        server_errors = []

        def stall_handshake():
            try:
                peer, _ = listener.accept()
                with peer:
                    peer.settimeout(8)
                    if peer.recv(4096).startswith(b"\x16\x03"):
                        client_hello.set()
                    stop.wait(8)
            except OSError as error:
                server_errors.append(error)

        thread = threading.Thread(target=stall_handshake, daemon=True)
        thread.start()
        connect = socket.socket.connect

        def delayed_tcp(sock, address):
            self.assertEqual(address[0], "127.0.0.1")
            sleep(1.5)  # Controlled TCP latency, followed by a real TLS ClientHello.
            return connect(sock, address)

        try:
            with (
                patch(
                    "my_package.infrastructure.website.public_addresses",
                    return_value=["127.0.0.1"],
                ),
                patch(
                    "my_package.infrastructure.website.requests.certs.where",
                    return_value=str(TLS_FIXTURES / "server.pem"),
                ),
                # Leave 1.5s for CA loading and TLS startup on slower runners.
                # Without the fix, TCP + the stale 3s TLS timeout take at least
                # 4.5s, leaving a full second of tolerance for the correct path.
                patch("my_package.infrastructure.website.PAGE_BUDGET_SECONDS", 3),
                patch.object(socket.socket, "connect", delayed_tcp),
            ):
                start = perf_counter()
                place = Place(
                    "node/1", None, None, None, website=f"https://cafe.example:{port}"
                )
                self.assertEqual(WebsiteContactEnricher().enrich(place), place)
                elapsed = perf_counter() - start
                self.assertTrue(
                    client_hello.is_set(), "TLS handshake was never attempted"
                )
                self.assertLess(elapsed, 4, "TCP and TLS each consumed the page budget")
        finally:
            stop.set()
            listener.close()
            thread.join(timeout=9)
        self.assertFalse(thread.is_alive())
        self.assertEqual(server_errors, [])

    def test_failed_first_address_falls_back_to_reachable_address(self):
        with self.server() as (port, received, requests):
            connect = socket.socket.connect
            attempts = []

            def fail_first(sock, address):
                attempts.append(address[0])
                if address[0] == "127.0.0.2":
                    raise OSError("First address unavailable")
                return connect(sock, address)

            with (
                patch(
                    "my_package.infrastructure.website.public_addresses",
                    return_value=["127.0.0.2", "127.0.0.1"],
                ),
                patch.object(socket.socket, "connect", fail_first),
            ):
                result = WebsiteContactEnricher()._fetch(f"http://cafe.example:{port}")
            self.assertIsNotNone(result)
            self.assertIn("hello@example.org", result[1])
            self.assertTrue(received.is_set())
            self.assertEqual(attempts, ["127.0.0.2", "127.0.0.1"])
            self.assertEqual(len(requests), 1)

    def test_ipv6_socket_unavailable_falls_back_to_ipv4(self):
        initialize = socket.socket.__init__
        rejected = []

        def no_ipv6(sock, family=socket.AF_INET, *args, **kwargs):
            if family == socket.AF_INET6:
                rejected.append(family)
                raise OSError("IPv6 sockets unsupported")
            initialize(sock, family, *args, **kwargs)

        enricher = WebsiteContactEnricher()
        with (
            self.server() as (port, received, requests),
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["2001:db8::1", "127.0.0.1"],
            ),
            patch(
                "urllib3.util.connection.allowed_gai_family",
                return_value=socket.AF_UNSPEC,
            ),
            patch.object(socket.socket, "__init__", no_ipv6),
            patch.object(
                enricher, "_fetch_address", wraps=enricher._fetch_address
            ) as fetch,
        ):
            result = enricher._fetch(f"http://cafe.example:{port}")
            self.assertIsNotNone(result)
            self.assertIn("hello@example.org", result[1])
            self.assertTrue(received.is_set())
            self.assertEqual(
                [call.args[1] for call in fetch.call_args_list],
                ["2001:db8::1", "127.0.0.1"],
            )
            self.assertEqual(rejected, [socket.AF_INET6])
            self.assertEqual(len(requests), 1)

    def test_real_https_verifies_certificate_hostname_and_sends_idna_host(self):
        with (
            self.server(tls=True) as (port, received, requests),
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["127.0.0.1"],
            ),
            patch(
                "my_package.infrastructure.website.requests.certs.where",
                return_value=str(TLS_FIXTURES / "server.pem"),
            ),
        ):
            result = WebsiteContactEnricher()._fetch(f"https://{IDNA_HOST}:{port}/menu")
            self.assertIsNotNone(result)
            self.assertIn("hello@example.org", result[1])
            self.assertTrue(received.is_set())
            self.assertEqual(requests, [(f"xn--80aaf4a.example:{port}", "/menu")])
            self.assertEqual(self.server_names, ["xn--80aaf4a.example"])

    def test_real_https_rejects_wrong_hostname(self):
        with (
            self.server(tls=True) as (port, received, requests),
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["127.0.0.1"],
            ),
            patch(
                "my_package.infrastructure.website.requests.certs.where",
                return_value=str(TLS_FIXTURES / "server.pem"),
            ),
        ):
            with self.assertRaises(urllib3.exceptions.SSLError) as error:
                WebsiteContactEnricher()._fetch(f"https://wrong.example:{port}/")
            self.assertRegex(str(error.exception), "hostname|not valid|doesn't match")
            self.assertFalse(received.is_set())
            self.assertEqual(requests, [])

    def test_real_https_rejects_untrusted_certificate(self):
        with (
            self.server(tls=True) as (port, received, requests),
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["127.0.0.1"],
            ),
        ):
            with self.assertRaises(urllib3.exceptions.SSLError) as error:
                WebsiteContactEnricher()._fetch(f"https://cafe.example:{port}/")
            self.assertIn("CERTIFICATE_VERIFY_FAILED", str(error.exception))
            self.assertFalse(received.is_set())
            self.assertEqual(requests, [])

    def test_unicode_hostname_reaches_server_with_idna_host_header(self):
        with (
            self.server() as (port, received, requests),
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["127.0.0.1"],
            ) as resolve,
        ):
            result = WebsiteContactEnricher()._fetch(
                f"http://{IDNA_HOST}:{port}/menu?q=1"
            )
            self.assertIsNotNone(result)
            self.assertIn("hello@example.org", result[1])
            self.assertTrue(received.is_set())
            host = IDNA_HOST.encode("idna").decode("ascii")
            self.assertEqual(requests, [(f"{host}:{port}", "/menu?q=1")])
            self.assertEqual(
                resolve.call_args.args, (f"http://{host}:{port}/menu?q=1",)
            )


class WebsiteTransportTests(unittest.TestCase):
    def test_default_port_contact_links_are_followed(self):
        for scheme, port in (("http", 80), ("https", 443)):
            for base_port, link_port in (
                ("", f":{port}"),
                (f":{port}", ""),
                (f":{port}", f":{port}"),
            ):
                with (
                    self.subTest(
                        scheme=scheme, base_port=base_port, link_port=link_port
                    ),
                    patch(
                        "my_package.infrastructure.website.urllib3.HTTPConnectionPool",
                        self.pool,
                    ),
                ):
                    self.response.read1.side_effect = [
                        f'<a href="{scheme}://cafe.example{link_port}/contact">Contact</a>'.encode(),
                        b"",
                        b"<p>hello@example.org</p>",
                        b"",
                    ]
                    result = WebsiteContactEnricher().enrich(
                        Place(
                            "node/1",
                            None,
                            None,
                            None,
                            website=f"{scheme}://cafe.example{base_port}",
                        )
                    )
                    self.assertEqual(result.email, "hello@example.org")

    def test_normalization_preserves_nondefault_ports(self):
        for url in (
            "http://cafe.example:443/contact",
            "https://cafe.example:80/contact",
            "https://cafe.example:8443/contact",
        ):
            with self.subTest(url=url):
                self.assertEqual(normalize_url(url), url)

    def test_absolute_unicode_contact_link_is_same_site(self):
        for href in (
            f"https://{IDNA_HOST}/contact",
            "https://xn--80aaf4a.example/contact",
            "/contact",
        ):
            with (
                self.subTest(href=href),
                patch.object(
                    WebsiteContactEnricher,
                    "_fetch",
                    side_effect=[
                        (
                            "https://xn--80aaf4a.example",
                            '<a href="' + href + '">Contact</a>',
                        ),
                        (
                            "https://xn--80aaf4a.example/contact",
                            "<p>hello@example.org</p>",
                        ),
                    ],
                ) as fetch,
            ):
                result = WebsiteContactEnricher().enrich(
                    Place("node/1", None, None, None, website=f"https://{IDNA_HOST}")
                )
                self.assertEqual(result.email, "hello@example.org")
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(
                    fetch.call_args.args, ("https://xn--80aaf4a.example/contact",)
                )

    def setUp(self):
        self.response = Mock(status=200, headers={"Content-Type": "text/html"})
        self.response.read1.side_effect = [b"<p>hello@example.org</p>", b""]
        self.pool = self.enterContext(
            patch("my_package.infrastructure.website.urllib3.HTTPSConnectionPool")
        )
        self.pool.return_value.__enter__.return_value.urlopen.return_value = (
            self.response
        )
        self.dns = self.enterContext(
            patch(
                "my_package.infrastructure.website.socket.getaddrinfo",
                return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
                ],
            )
        )
        self.enricher = WebsiteContactEnricher()

    def test_pins_validated_ip_and_preserves_tls_hostname(self):
        self.assertIn(
            "hello@example.org",
            self.enricher._fetch("https://cafe.example/menu?q=1")[1],
        )
        self.assertEqual(self.pool.call_args.args, ("93.184.216.34",))
        self.assertEqual(self.pool.call_args.kwargs["server_hostname"], "cafe.example")
        self.assertEqual(self.pool.call_args.kwargs["assert_hostname"], "cafe.example")
        request = self.pool.return_value.__enter__.return_value.urlopen.call_args
        self.assertEqual(request.args, ("GET", "/menu?q=1"))
        self.assertEqual(request.kwargs["headers"]["Host"], "cafe.example")
        self.assertFalse(request.kwargs["redirect"])
        self.dns.assert_called_once()
        self.response.close.assert_called_once()

    def test_redirect_to_private_address_is_never_requested(self):
        self.response.status = 302
        self.response.headers = {"Location": "http://127.0.0.1/private"}
        self.dns.side_effect = [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
        ]
        with patch(
            "my_package.infrastructure.website.urllib3.HTTPConnectionPool"
        ) as http:
            self.assertIsNone(self.enricher._fetch("https://cafe.example"))
        http.assert_not_called()
        self.response.close.assert_called_once()

    def test_redirect_limit(self):
        self.response.status = 302
        self.response.headers = {"Location": "/loop"}
        self.assertIsNone(self.enricher._fetch("https://cafe.example"))
        self.assertEqual(self.response.close.call_count, 4)

    def test_byte_limit_and_content_type(self):
        self.response.read1.side_effect = [b"a" * 1_000_001]
        self.assertIsNone(self.enricher._fetch("https://cafe.example"))
        self.response.headers = {"Content-Type": "application/pdf"}
        self.assertIsNone(self.enricher._fetch("https://cafe.example"))

    def test_continuous_stream_stops_at_deadline(self):
        with patch(
            "my_package.infrastructure.website.monotonic", side_effect=[0, 0, 0, 1, 11]
        ):
            self.assertIsNone(self.enricher._fetch("https://cafe.example"))
        self.assertEqual(self.response.read1.call_count, 1)
        self.response.close.assert_called_once()

    def test_unicode_hostname_uses_idna_for_dns_and_tls(self):
        self.enricher._fetch(f"https://{IDNA_HOST}/")
        host = IDNA_HOST.encode("idna").decode("ascii")
        self.assertEqual(self.dns.call_args.args[0], host)
        self.assertEqual(self.pool.call_args.kwargs["server_hostname"], host)
        self.assertEqual(self.pool.call_args.kwargs["assert_hostname"], host)
        request = self.pool.return_value.__enter__.return_value.urlopen.call_args
        self.assertEqual(request.kwargs["headers"]["Host"], host)

    def test_fallback_does_not_reset_page_budget(self):
        with (
            patch(
                "my_package.infrastructure.website.public_addresses",
                return_value=["93.184.216.34", "93.184.216.35"],
            ),
            patch.object(
                self.enricher,
                "_fetch_address",
                side_effect=urllib3.exceptions.ConnectTimeoutError(),
            ) as fetch,
            patch(
                "my_package.infrastructure.website.monotonic", side_effect=[0, 1, 11]
            ),
        ):
            self.assertIsNone(self.enricher._fetch("https://cafe.example"))
        fetch.assert_called_once()

    def test_meta_charset_allows_contact_page(self):
        self.response.read1.side_effect = [
            '<meta charset="utf-8"><a href="/about">Contact Café</a>'.encode(),
            b"",
            b"<p>hello@example.org</p>",
            b"",
        ]
        result = self.enricher.enrich(
            Place("node/1", None, None, None, website="https://cafe.example")
        )
        self.assertEqual(result.email, "hello@example.org")
        self.assertEqual(self.response.close.call_count, 2)

    def test_http_charset_takes_precedence_and_unknown_charset_falls_back(self):
        self.assertEqual(
            decode_html("Café".encode("cp1252"), "text/html; charset=windows-1252"),
            "Café",
        )
        self.assertEqual(
            decode_html("Café".encode(), "text/html; charset=invalid-encoding"),
            "Café",
        )

    def test_large_non_email_text_has_bounded_runtime(self):
        start = perf_counter()
        self.assertIsNone(EMAIL.search("a" * 1_000_000))
        self.assertLess(perf_counter() - start, 2)
        self.assertEqual(
            EMAIL.search("Email: hello+tag@example.org").group(),
            "hello+tag@example.org",
        )
