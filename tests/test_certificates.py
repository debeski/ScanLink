import json
from pathlib import Path
import ssl
import socket
import threading
from urllib.request import urlopen
import unittest
from unittest.mock import patch
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import certificates


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(".xclude/test-output/certificates") / uuid.uuid4().hex
        self.identity = certificates.LocalIdentity(self.directory)
        self.trusted = set()
        self.secret_patch = patch(
            "certificates._protect_secret",
            side_effect=lambda value, decrypt=False: value,
        )
        self.trust_patch = patch(
            "certificates._is_trusted", side_effect=lambda der: der in self.trusted
        )
        self.install_patch = patch(
            "certificates._install_trust", side_effect=self.trusted.add
        )
        for mock in (self.secret_patch, self.trust_patch, self.install_patch):
            mock.start()
            self.addCleanup(mock.stop)

    def active(self):
        return json.loads(self.identity.pointer.read_text())["identity"]

    def test_first_run_creates_a_trusted_encrypted_localhost_leaf(self):
        context = self.identity.ensure()
        certificate, _ = self.identity._read()
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertFalse(
            certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value.ca
        )
        self.assertEqual(
            len(
                certificate.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName
                ).value
            ),
            3,
        )
        self.assertIn(
            certificate.public_bytes(serialization.Encoding.DER), self.trusted
        )
        bundle = (self.identity.root / self.active() / "localhost.pem").read_bytes()
        self.assertIn(b"BEGIN ENCRYPTED PRIVATE KEY", bundle)
        self.assertNotIn(b"BEGIN PRIVATE KEY", bundle)
        self.identity.context()

    def test_healthy_launch_reuses_identity_without_reinstalling_trust(self):
        self.identity.ensure()
        previous = self.active()
        with patch("certificates._install_trust") as install:
            self.identity.ensure()
        self.assertEqual(self.active(), previous)
        install.assert_not_called()

    def test_missing_trust_is_repaired_without_replacing_identity(self):
        self.identity.ensure()
        previous = self.active()
        self.trusted.clear()
        with self.assertRaises(OSError):
            self.identity.context()
        self.identity.ensure()
        self.assertEqual(self.active(), previous)
        self.identity.context()

    def test_trust_failure_does_not_report_success_or_generate_a_new_key_on_retry(self):
        with patch("certificates._install_trust", side_effect=OSError("policy denied")):
            with self.assertRaisesRegex(OSError, "policy denied"):
                self.identity.ensure()
        pending = self.active()
        with self.assertRaises(OSError):
            self.identity.context()
        self.identity.ensure()
        self.assertEqual(self.active(), pending)
        self.identity.context()

    def test_renewal_preserves_previous_credentials_under_xclude(self):
        self.identity.ensure()
        previous = self.active()
        with patch("certificates.RENEW_BEFORE", certificates.timedelta(days=400)):
            self.identity.ensure()
        self.assertNotEqual(self.active(), previous)
        self.assertTrue(
            (self.directory / ".xclude/https" / previous / "localhost.pem").exists()
        )
        self.identity.context()

    def test_corrupt_identity_is_replaced_without_losing_the_original(self):
        self.identity.ensure()
        previous = self.active()
        bundle = self.identity.root / previous / "localhost.pem"
        bundle.write_bytes(b"damaged")
        self.identity.ensure()
        self.assertNotEqual(self.active(), previous)
        self.assertEqual(
            (
                self.directory / ".xclude/https" / previous / "localhost.pem"
            ).read_bytes(),
            b"damaged",
        )

    def test_real_tls_handshake_and_live_identity_reload(self):
        import server
        from tests.test_server import FakeWorker

        context = self.identity.ensure()
        certificate, _ = self.identity._read()
        verifier = ssl.create_default_context(
            cadata=certificate.public_bytes(serialization.Encoding.PEM).decode()
        )
        app = server.create_app(
            FakeWorker(), threading.Event(), {"https_enabled": True}
        )
        listener = server.LoopbackServer(app, "127.0.0.1", 0, ssl_context=context)
        listener.start()
        self.assertTrue(listener.started.wait(5))
        self.assertIsNone(listener.error)
        port = listener.httpd.server_port
        try:
            with urlopen(
                f"https://127.0.0.1:{port}/health", context=verifier, timeout=3
            ) as response:
                self.assertEqual(json.load(response)["status"], "ok")
            with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    verifier.wrap_socket(
                        connection, server_hostname="another-host.invalid"
                    )
            with patch("certificates.RENEW_BEFORE", certificates.timedelta(days=400)):
                renewed = self.identity.ensure()
            listener.ssl_context = renewed
            certificate, _ = self.identity._read()
            verifier = ssl.create_default_context(
                cadata=certificate.public_bytes(serialization.Encoding.PEM).decode()
            )
            for hostname in ("localhost", "127.0.0.1"):
                with urlopen(
                    f"https://{hostname}:{port}/health", context=verifier, timeout=3
                ) as response:
                    self.assertEqual(json.load(response)["status"], "ok")
        finally:
            listener.shutdown()
            listener.join(5)

    def test_pointer_cannot_escape_the_identity_directory(self):
        self.identity.root.mkdir(parents=True)
        self.identity.pointer.write_text(json.dumps({"identity": "../outside"}))
        self.identity.ensure()
        self.assertNotEqual(self.active(), "../outside")


@unittest.skipUnless(certificates.os.name == "nt", "Windows DPAPI integration")
class WindowsSecretTests(unittest.TestCase):
    def test_private_key_password_is_bound_to_the_windows_user(self):
        password = b"ScanLink-test-" + uuid.uuid4().bytes
        protected = certificates._protect_secret(password)
        self.assertNotIn(password, protected)
        self.assertEqual(
            certificates._protect_secret(protected, decrypt=True), password
        )
