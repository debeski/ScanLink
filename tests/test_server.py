import threading
import json
from urllib.request import urlopen
import unittest
from unittest.mock import MagicMock, patch

from worker import BusyError

try:
    import server
except ImportError:
    server = None


class FakeWorker:
    def __init__(self):
        self.busy = False
        self.twain_available = True
        self.jobs = {}

    def is_busy(self):
        return self.busy

    def is_twain_available(self):
        return self.twain_available

    def submit_job(self, doc_id=None, callback_url=None, metadata=None, source="api"):
        if self.busy:
            raise BusyError(active_job_id="busy-job")

        job = {
            "job_id": "job-123",
            "status": "queued",
            "submitted_at": 1.0,
            "updated_at": 1.0,
            "started_at": None,
            "completed_at": None,
            "doc_id": doc_id,
            "callback_url": callback_url,
            "page_count": 0,
            "metadata": metadata or {},
            "source": source,
        }
        self.jobs[job["job_id"]] = {
            **job,
            "result_bytes": b"%PDF-1.4\nfake\n",
        }
        return job

    def get_job(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return None

        return {key: value for key, value in job.items() if key != "result_bytes"}

    def consume_result(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return None, None

        result_bytes = job.get("result_bytes")
        job["result_bytes"] = None
        return self.get_job(job_id), result_bytes


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.worker = FakeWorker()
        self.transport_state = {"http_enabled": True, "https_enabled": False}
        self.shutdown_event = threading.Event()
        self.config_patch = patch(
            "server.load_config", return_value={"cors_origins": ["*"]}
        )
        self.config_patch.start()
        self.app = server.create_app(
            self.worker, self.shutdown_event, self.transport_state
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.config_patch.stop()

    def test_health_reports_transport_flags(self):
        response = self.client.get("/health")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["http_enabled"])
        self.assertFalse(payload["https_enabled"])
        self.assertEqual(payload["version"], server.APP_VERSION)
        self.assertEqual(payload["arch"], server.APP_ARCH)
        self.assertFalse(payload["busy"])
        self.assertTrue(payload["twain_available"])

    def test_certificate_setup_failure_keeps_http_available_and_reports_failure(self):
        failed = threading.Event()
        listeners = []
        original_listener = server.LoopbackServer

        def create_listener(app, host, port, **options):
            listener = original_listener(app, host, 0, **options)
            listeners.append(listener)
            return listener

        with patch("server.LoopbackServer", side_effect=create_listener), patch(
            "server.ensure_ssl_certificates", return_value=False
        ):
            manager = threading.Thread(
                target=server.run_server,
                args=(self.worker, self.shutdown_event, threading.Event(), failed.set),
            )
            manager.start()
            try:
                self.assertTrue(failed.wait(5))
                port = listeners[0].httpd.server_port
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                    health = json.load(response)
                self.assertTrue(health["http_enabled"])
                self.assertFalse(health["https_enabled"])
                self.assertEqual(health["https_setup"], "failed")
                self.assertTrue(manager.is_alive())
            finally:
                self.shutdown_event.set()
                manager.join(5)
            self.assertFalse(manager.is_alive())

    def test_retry_enables_https_after_a_failed_first_attempt(self):
        retry = threading.Event()
        observations = []
        listeners = []
        shutdown = threading.Event()

        def listener_factory(app, *args, **kwargs):
            listener = MagicMock()
            listener.app = app
            listener.error = None
            listener.started.is_set.return_value = True
            listeners.append(listener)
            return listener

        def next_cycle(timeout):
            health = listeners[0].app.test_client().get("/health").get_json()
            observations.append(health["https_setup"])
            if len(observations) == 1:
                self.assertTrue(health["http_enabled"])
                self.assertFalse(health["https_enabled"])
                retry.set()
            else:
                self.assertTrue(health["https_enabled"])
                shutdown.set()

        with patch("server.LoopbackServer", side_effect=listener_factory), patch(
            "server.ensure_ssl_certificates", side_effect=[False, True]
        ), patch("server.get_ssl_context", return_value=MagicMock()), patch(
            "server.socket.create_connection"
        ), patch(
            "server.ssl.create_default_context"
        ), patch.object(
            shutdown, "wait", side_effect=next_cycle
        ):
            server.run_server(self.worker, shutdown, retry)
        self.assertEqual(observations, ["failed", "ready"])
        self.assertEqual(len(listeners), 2)
        for listener in listeners:
            listener.shutdown.assert_called_once()

    def test_scan_request_maps_browser_payload_to_job(self):
        response = self.client.post(
            "/scan",
            json={
                "docId": "DOC-42",
                "callback": "https://example.com/scans",
                "metadata": {"field": "pdf_file"},
            },
        )

        self.assertEqual(response.status_code, 202)
        job = self.worker.jobs[response.get_json()["job_id"]]
        self.assertEqual(job["doc_id"], "DOC-42")
        self.assertEqual(job["callback_url"], "https://example.com/scans")
        self.assertEqual(job["metadata"], {"field": "pdf_file"})
        self.assertEqual(job["source"], "api")

    def test_scan_requires_json(self):
        response = self.client.post("/scan", data="not-json")

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["error"]["code"], "json_required")

    def test_scan_rejects_invalid_json(self):
        response = self.client.post(
            "/scan",
            data="{invalid",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_json")

    def test_scan_rejects_non_object_metadata(self):
        response = self.client.post("/scan", json={"metadata": ["invalid"]})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_metadata")

    def test_scan_returns_busy_conflict(self):
        self.worker.busy = True

        response = self.client.post("/scan", json={})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "busy")

    def test_scan_endpoint_reflects_origin(self):
        response = self.client.post(
            "/scan",
            json={"metadata": {"field": "pdf_file"}},
            headers={"Origin": "http://localhost:82"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "http://localhost:82"
        )

    def test_result_endpoint_returns_pdf(self):
        self.worker.jobs["job-123"] = {
            "job_id": "job-123",
            "status": "completed",
            "submitted_at": 1.0,
            "updated_at": 2.0,
            "started_at": 1.5,
            "completed_at": 2.0,
            "doc_id": None,
            "page_count": 1,
            "metadata": {},
            "result_bytes": b"%PDF-1.4\nfake\n",
        }

        response = self.client.get("/scan/job-123/result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("scan_job-123.pdf", response.headers["Content-Disposition"])

    def test_status_and_result_report_missing_job(self):
        status_response = self.client.get("/scan/missing")
        result_response = self.client.get("/scan/missing/result")

        self.assertEqual(status_response.status_code, 404)
        self.assertEqual(status_response.get_json()["error"]["code"], "job_not_found")
        self.assertEqual(result_response.status_code, 404)
        self.assertEqual(result_response.get_json()["error"]["code"], "job_not_found")

    def test_result_reports_not_ready(self):
        self.worker.submit_job()

        response = self.client.get("/scan/job-123/result")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "result_not_ready")
        self.assertEqual(response.get_json()["error"]["current_status"], "queued")

    def test_completed_result_can_only_be_downloaded_once(self):
        self.worker.jobs["job-123"] = {
            "job_id": "job-123",
            "status": "completed",
            "result_bytes": b"%PDF-1.4\nfake\n",
        }

        first_response = self.client.get("/scan/job-123/result")
        second_response = self.client.get("/scan/job-123/result")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 410)
        self.assertEqual(
            second_response.get_json()["error"]["code"], "result_unavailable"
        )

    def test_protocol_endpoint_queues_protocol_job(self):
        response = self.client.post(
            "/internal/protocol/scan",
            json={"action": "scan", "doc_id": "DOC-9", "metadata": {"source": "link"}},
        )

        self.assertEqual(response.status_code, 202)
        job = self.worker.jobs[response.get_json()["job_id"]]
        self.assertEqual(job["doc_id"], "DOC-9")
        self.assertEqual(job["metadata"], {"source": "link"})
        self.assertEqual(job["source"], "protocol")

    def test_protocol_endpoint_rejects_unsupported_action(self):
        response = self.client.post("/internal/protocol/scan", json={"action": "probe"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "unsupported_action")

    def test_shutdown_sets_application_event(self):
        response = self.client.post("/shutdown")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.shutdown_event.is_set())


if __name__ == "__main__":
    unittest.main()
