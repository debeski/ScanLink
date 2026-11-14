import queue
import threading
import time
import unittest
from unittest.mock import patch

from tests.test_server import FakeWorker
from worker import ScanWorker

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


LEGIT = {"Origin": "https://archive.example"}
OTHER = {"Origin": "https://crm.example"}
EVIL = {"Origin": "https://evil.example"}


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class JobOwnershipTests(unittest.TestCase):
    cors_origins = ["*"]

    def setUp(self):
        config = patch(
            "server.load_config", return_value={"cors_origins": self.cors_origins}
        )
        config.start()
        self.addCleanup(config.stop)
        # Not started: submitted jobs stay queued until a test completes them.
        self.worker = ScanWorker(queue.Queue())
        self.app = server.create_app(
            self.worker, threading.Event(), {"http_enabled": True}
        )
        self.client = self.app.test_client()

    def complete(self, job_id):
        self.worker._update_job(
            job_id,
            status="completed",
            completed_at=time.time(),
            result_bytes=b"%PDF-1.4\nsecret\n",
        )

    def test_another_origin_cannot_find_or_take_a_scan(self):
        job_id = self.client.post("/scan", json={}, headers=LEGIT).get_json()["job_id"]

        other_busy = self.client.post("/scan", json={}, headers=OTHER)
        self.assertEqual(other_busy.status_code, 409)
        self.assertNotIn("active_job_id", other_busy.get_json()["error"])
        owner_busy = self.client.post("/scan", json={}, headers=LEGIT)
        self.assertEqual(owner_busy.get_json()["error"]["active_job_id"], job_id)

        self.complete(job_id)
        for headers in (OTHER, {}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                for path in (f"/scan/{job_id}", f"/scan/{job_id}/result"):
                    response = self.client.get(path, headers=headers)
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(
                        response.get_json()["error"]["code"], "job_not_found"
                    )

        self.assertEqual(
            self.client.get(f"/scan/{job_id}", headers=LEGIT).get_json()["status"],
            "completed",
        )
        result = self.client.get(f"/scan/{job_id}/result", headers=LEGIT)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, b"%PDF-1.4\nsecret\n")

    def test_jobs_started_without_an_origin_stay_with_local_tools(self):
        job_id = self.client.post("/scan", json={}).get_json()["job_id"]
        self.assertEqual(self.client.post("/scan", json={}).get_json()["error"]["active_job_id"], job_id)
        self.assertNotIn(
            "active_job_id",
            self.client.post("/scan", json={}, headers=LEGIT).get_json()["error"],
        )
        self.assertEqual(
            self.client.get(f"/scan/{job_id}", headers=LEGIT).status_code, 404
        )
        self.complete(job_id)
        self.assertEqual(self.client.get(f"/scan/{job_id}/result").status_code, 200)


class AllowListTests(JobOwnershipTests):
    cors_origins = ["https://archive.example", "https://crm.example"]

    def test_unlisted_origin_is_refused_before_any_work(self):
        preflight = self.client.options(
            "/scan",
            headers={**EVIL, "Access-Control-Request-Method": "POST"},
        )
        for response in (
            preflight,
            self.client.get("/health", headers=EVIL),
            self.client.post("/scan", json={}, headers=EVIL),
            self.client.get("/scan/anything", headers=EVIL),
        ):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.get_json()["error"]["code"], "origin_not_allowed"
            )
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertEqual(self.worker.jobs, {})

        accepted = self.client.post("/scan", json={}, headers=LEGIT)
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(
            accepted.headers["Access-Control-Allow-Origin"], LEGIT["Origin"]
        )


if __name__ == "__main__":
    unittest.main()
