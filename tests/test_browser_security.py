import threading
import unittest
from unittest.mock import patch

from tests.test_server import FakeWorker

try:
    import server
except ImportError:
    server = None


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class BrowserSecurityTests(unittest.TestCase):
    cors_origins = ["*"]

    def setUp(self):
        self.worker = FakeWorker()
        self.shutdown_event = threading.Event()
        config = patch(
            "server.load_config", return_value={"cors_origins": self.cors_origins}
        )
        config.start()
        self.addCleanup(config.stop)
        self.app = server.create_app(
            self.worker, self.shutdown_event, {"http_enabled": True}
        )
        self.client = self.app.test_client()

    def test_rebound_host_names_are_refused(self):
        for host in (
            "evil.example:5000",
            "127.0.0.1.nip.io:5000",
            "localhost.evil.example",
            "evil.localhost:5443",
            "a b",
        ):
            with self.subTest(host=host):
                health = self.client.get("/health", headers={"Host": host})
                scan = self.client.post("/scan", json={}, headers={"Host": host})
                shutdown = self.client.post("/shutdown", headers={"Host": host})
                for response in (health, scan, shutdown):
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(
                        response.get_json()["error"]["code"], "invalid_host"
                    )
        self.assertEqual(self.worker.jobs, {})
        self.assertFalse(self.shutdown_event.is_set())

    def test_loopback_host_names_are_served(self):
        for host in (
            "localhost:5000",
            "localhost:5443",
            "127.0.0.1:5000",
            "[::1]:5443",
            "LOCALHOST:5443",
            "127.0.0.1",
        ):
            with self.subTest(host=host):
                response = self.client.get("/health", headers={"Host": host})
                self.assertEqual(response.status_code, 200)

    def test_browser_requests_cannot_use_local_control_endpoints(self):
        browser_headers = (
            {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},
        )
        for headers in browser_headers:
            with self.subTest(headers=headers):
                shutdown = self.client.post(
                    "/shutdown",
                    data="x=1",
                    content_type="application/x-www-form-urlencoded",
                    headers=headers,
                )
                protocol = self.client.post(
                    "/internal/protocol/scan", json={"action": "scan"}, headers=headers
                )
                for response in (shutdown, protocol):
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(
                        response.get_json()["error"]["code"], "local_only"
                    )
        self.assertFalse(self.shutdown_event.is_set())
        self.assertEqual(self.worker.jobs, {})

    def test_local_tools_keep_local_control_endpoints(self):
        protocol = self.client.post("/internal/protocol/scan", json={"action": "scan"})
        shutdown = self.client.post("/shutdown")
        self.assertEqual(protocol.status_code, 202)
        self.assertEqual(shutdown.status_code, 200)
        self.assertTrue(self.shutdown_event.is_set())


if __name__ == "__main__":
    unittest.main()
