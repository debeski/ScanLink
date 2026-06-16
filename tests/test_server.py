import unittest
from unittest.mock import patch

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
            "page_count": 0,
            "metadata": metadata or {},
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

        return {
            key: value
            for key, value in job.items()
            if key != "result_bytes"
        }

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
        self.config_patch = patch("server.load_config", return_value={"cors_origins": ["*"]})
        self.config_patch.start()
        self.app = server.create_app(self.worker, shutdown_event=type("E", (), {"set": lambda self: None})(), transport_state=self.transport_state)
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

    def test_scan_requires_json(self):
        response = self.client.post("/scan", data="not-json")

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["error"]["code"], "json_required")

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
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:82")

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


if __name__ == "__main__":
    unittest.main()
