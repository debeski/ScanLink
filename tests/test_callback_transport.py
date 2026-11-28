"""Callbacks reach public https websites only, and cannot hold ScanLink up (R2-010, R2-055)."""

import socket
import socketserver
import ssl
import threading
import time
import unittest
from unittest.mock import patch

import callback_transport
from callback_transport import (
    CallbackFailed,
    CallbackRefused,
    check_callback_url,
    is_public_address,
    post_scan,
    resolve_public,
)

try:
    from tests.test_loopback_listener import localhost_tls
except ImportError:  # cryptography is not installed
    localhost_tls = None

PDF = b"%PDF-1.4\nscanned\n"


def resolving_to(*addresses):
    def resolver(host, port, type=0):
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]

    return resolver


class AddressClassificationTests(unittest.TestCase):
    def test_only_public_unicast_addresses_pass(self):
        for address in ("93.184.215.14", "8.8.8.8", "2606:4700:4700::1111"):
            with self.subTest(address=address):
                self.assertTrue(is_public_address(address))
        for address in (
            "127.0.0.1", "127.8.9.10", "0.0.0.0", "10.0.0.5", "172.16.3.4", "192.168.1.10",
            "100.64.0.1", "100.100.100.200", "169.254.169.254", "224.0.0.1", "255.255.255.255",
            "192.0.2.1", "198.18.0.1", "::1", "::", "fe80::1", "fd00:ec2::254", "fc00::1",
            "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::",
            "2001:0:4136:e378:8000:63bf:80ff:fffe", "::127.0.0.1", "ff02::1", "2001:db8::1",
            "not-an-address",
        ):
            with self.subTest(address=address):
                self.assertFalse(is_public_address(address))

    def test_callback_urls_must_be_https_to_a_public_looking_host(self):
        self.assertEqual(check_callback_url("https://crm.example/scans?x=1"), ("crm.example", 443, "/scans?x=1"))
        self.assertEqual(check_callback_url("https://crm.example:8443"), ("crm.example", 8443, "/"))
        for url, reason in (
            ("http://crm.example/scans", "https_required"),
            ("ftp://crm.example/scans", "https_required"),
            ("https://localhost/x", "blocked_address"),
            ("https://LOCALHOST./x", "blocked_address"),
            ("https://scanner.localhost/x", "blocked_address"),
            ("https://127.0.0.1:5443/shutdown", "blocked_address"),
            ("https://127.1/x", "blocked_address"),
            ("https://2130706433/x", "blocked_address"),
            ("https://0x7f000001/x", "blocked_address"),
            ("https://0177.0.0.1/x", "blocked_address"),
            ("https://[::1]/x", "blocked_address"),
            ("https://[::ffff:127.0.0.1]/x", "blocked_address"),
            ("https://10.1.2.3/x", "blocked_address"),
            ("https://169.254.169.254/latest/meta-data", "blocked_address"),
            ("https://user@crm.example/x", "invalid_url"),
            ("https://crm.example/a b", "invalid_url"),
            ("https://crm​.example/x", "invalid_url"),
            ("https://[/x", "invalid_url"),
            (None, "invalid_url"),
        ):
            with self.subTest(url=url):
                with self.assertRaises(CallbackRefused) as caught:
                    check_callback_url(url)
                self.assertEqual(caught.exception.reason, reason)

    def test_a_host_is_refused_if_any_address_it_resolves_to_is_not_public(self):
        no_own = lambda: set()
        self.assertEqual(len(resolve_public("crm.example", 443, resolving_to("93.184.215.14"), no_own)), 1)
        for addresses in (("127.0.0.1",), ("93.184.215.14", "10.0.0.5"), ("::ffff:192.168.0.1",)):
            with self.subTest(addresses=addresses):
                with self.assertRaises(CallbackRefused):
                    resolve_public("crm.example", 443, resolving_to(*addresses), no_own)

    def test_this_computers_own_addresses_are_refused(self):
        import ipaddress

        own = lambda: {ipaddress.ip_address("93.184.215.14")}
        with self.assertRaises(CallbackRefused):
            resolve_public("me.example", 443, resolving_to("93.184.215.14"), own)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        server.connections += 1
        data = b""
        self.request.settimeout(5)
        try:
            while b"\r\n\r\n" not in data:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                data += chunk
            head, _, body = data.partition(b"\r\n\r\n")
            length = int(next(
                line.split(b":", 1)[1] for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")
            ))
            while len(body) < length:
                body += self.request.recv(65536)
            server.requests.append((head.decode("latin-1"), body))
            mode = server.mode
            if mode == "huge":
                self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1073741824\r\nContent-Encoding: gzip\r\n\r\n")
                while not server.stop.is_set():
                    self.request.sendall(b"\0" * 65536)
            elif mode == "drip":
                for byte in b"HTTP/1.1 200 OK\r\n\r\n":
                    if server.stop.wait(0.4):
                        return
                    self.request.sendall(bytes([byte]))
            elif mode == "redirect":
                self.request.sendall(b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/\r\nContent-Length: 0\r\n\r\n")
            else:
                self.request.sendall(b"HTTP/1.1 201 Created\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            return


class _TLSServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, context, mode):
        self.context, self.mode = context, mode
        self.requests, self.connections, self.stop = [], 0, threading.Event()
        super().__init__(("127.0.0.1", 0), _Handler)

    def get_request(self):
        sock, address = super().get_request()
        return self.context.wrap_socket(sock, server_side=True), address


@unittest.skipIf(localhost_tls is None, "cryptography is not installed")
class PostScanTests(unittest.TestCase):
    def serve(self, mode):
        server_context, _client_context = localhost_tls()
        server = _TLSServer(server_context, mode)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.stop.set)
        return server

    @staticmethod
    def client_context():
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    def post(self, url, **kwargs):
        return post_scan(
            url,
            [("job_id", "job-1"), ("doc_id", "D-1")],
            [("pdf", ("scan_job-1.pdf", PDF, "application/pdf"))],
            delivery_id="job-1",
            resolver=resolving_to("127.0.0.1"),
            own_addresses=lambda: set(),
            context=self.client_context(),
            **kwargs,
        )

    def test_a_host_rebound_to_this_computer_is_never_connected(self):
        server = self.serve("ok")
        with patch("callback_transport.socket.getaddrinfo", resolving_to("127.0.0.1")):
            with self.assertRaises(CallbackRefused) as caught:
                post_scan(
                    f"https://rebound.example:{server.server_address[1]}/api/admin/reset?all=1",
                    [("job_id", "job-1")],
                    [("pdf", ("scan.pdf", PDF, "application/pdf"))],
                    delivery_id="job-1",
                    context=self.client_context(),
                )
        self.assertEqual(caught.exception.reason, "blocked_address")
        time.sleep(0.2)
        self.assertEqual(server.connections, 0)

    def _as_public(self):
        # Stand in for a public website: loopback is the only reachable test host.
        real = callback_transport.is_public_address
        patcher = patch(
            "callback_transport.is_public_address",
            side_effect=lambda value: str(value).split("%")[0] == "127.0.0.1" or real(value),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_delivery_sends_the_scan_without_browser_headers(self):
        self._as_public()
        server = self.serve("ok")
        status = self.post(f"https://callback.example:{server.server_address[1]}/in?x=1")
        self.assertEqual(status, 201)
        head, body = server.requests[0]
        self.assertTrue(head.startswith("POST /in?x=1 HTTP/1.1"))
        self.assertIn("Accept-Encoding: identity", head)
        self.assertIn("X-ScanLink-Delivery: job-1", head)
        self.assertIn(f"Host: callback.example:{server.server_address[1]}", head)
        self.assertNotIn("Origin:", head)
        self.assertIn(PDF, body)
        self.assertIn(b'name="doc_id"\r\n\r\nD-1', body)

    def test_a_huge_response_is_never_read(self):
        self._as_public()
        server = self.serve("huge")
        started = time.monotonic()
        status = self.post(f"https://callback.example:{server.server_address[1]}/huge")
        self.assertEqual(status, 200)
        self.assertLess(time.monotonic() - started, 5)

    def test_a_dripping_response_ends_at_the_deadline(self):
        self._as_public()
        server = self.serve("drip")
        started = time.monotonic()
        with self.assertRaises(CallbackFailed):
            self.post(f"https://callback.example:{server.server_address[1]}/drip", deadline_seconds=1)
        self.assertLess(time.monotonic() - started, 4)

    def test_a_redirect_is_reported_not_followed(self):
        self._as_public()
        server = self.serve("redirect")
        self.assertEqual(self.post(f"https://callback.example:{server.server_address[1]}/r"), 302)
        self.assertEqual(len(server.requests), 1)


if __name__ == "__main__":
    unittest.main()
