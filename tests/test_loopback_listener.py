import datetime
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from tests.test_server import FakeWorker

try:
    import server
except ImportError:
    server = None


def localhost_tls():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    directory = Path(".xclude/test-output/listener") / uuid.uuid4().hex
    directory.mkdir(parents=True)
    bundle = directory / "localhost.pem"
    bundle.write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(str(bundle))
    return server_context, ssl.create_default_context(cafile=str(bundle))


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class LoopbackListenerTests(unittest.TestCase):
    def setUp(self):
        timeout = patch("server.REQUEST_TIMEOUT_SECONDS", 1)
        timeout.start()
        self.addCleanup(timeout.stop)
        config = patch("server.load_config", return_value={"cors_origins": ["*"]})
        config.start()
        self.addCleanup(config.stop)
        app = server.create_app(FakeWorker(), threading.Event(), {"http_enabled": True})
        self.server_context, self.client_context = localhost_tls()
        self.http = server.LoopbackServer(app, "127.0.0.1", 0, label="HTTP")
        self.https = server.LoopbackServer(
            app, "127.0.0.1", 0, ssl_context=self.server_context, label="HTTPS"
        )
        for listener in (self.http, self.https):
            listener.start()
            self.assertTrue(listener.started.wait(5))
            self.assertIsNone(listener.error)
            self.addCleanup(listener.join, 5)
            self.addCleanup(listener.shutdown)

    def health(self, secure, timeout=3):
        if secure:
            raw = socket.create_connection(
                ("127.0.0.1", self.https.httpd.server_port), timeout=timeout
            )
            connection = http.client.HTTPConnection("localhost", timeout=timeout)
            connection.sock = self.client_context.wrap_socket(
                raw, server_hostname="localhost"
            )
        else:
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.http.httpd.server_port, timeout=timeout
            )
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_a_client_that_never_starts_tls_does_not_block_https(self):
        idle = [
            socket.create_connection(("127.0.0.1", self.https.httpd.server_port))
            for _ in range(3)
        ]
        self.addCleanup(lambda: [sock.close() for sock in idle])
        time.sleep(0.2)
        started = time.monotonic()
        status, payload = self.health(secure=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertLess(time.monotonic() - started, 1)

    def test_idle_connections_are_closed_after_the_request_timeout(self):
        for port in (self.http.httpd.server_port, self.https.httpd.server_port):
            with self.subTest(port=port):
                sock = socket.create_connection(("127.0.0.1", port))
                self.addCleanup(sock.close)
                if port == self.http.httpd.server_port:
                    sock.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n")
                sock.settimeout(10)
                started = time.monotonic()
                try:
                    data = sock.recv(1024)
                except ConnectionResetError:
                    data = b""
                self.assertLess(time.monotonic() - started, 5)
                self.assertFalse(data.startswith(b"HTTP/1.1 200"))
        self.assertEqual(self.health(secure=False)[0], 200)
        self.assertEqual(self.health(secure=True)[0], 200)


if __name__ == "__main__":
    unittest.main()
