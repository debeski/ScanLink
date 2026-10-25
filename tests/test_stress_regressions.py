import concurrent.futures
import json
from pathlib import Path
import queue
import sys
import threading
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from server import create_app
from worker import ScanWorker, TERMINAL_STATUSES


class RealWorkerRegressions(unittest.TestCase):
    def setUp(self):
        self.artifacts = (
            Path(__file__).resolve().parents[1]
            / ".xclude"
            / "worker-tests"
            / uuid.uuid4().hex
        )
        self.artifacts.mkdir(parents=True)
        self.worker = ScanWorker(queue.Queue())
        self.worker.scan_idle_timeout_seconds = 0
        self.worker._build_scan_subprocess_command = lambda directory: [
            sys.executable,
            str(Path(__file__).with_name("fixtures") / "scan_child.py"),
            directory,
            self.scenario,
        ]
        self.scenario = "complete"
        make_directory = tempfile.mkdtemp
        self.temporary = patch(
            "worker.tempfile.mkdtemp",
            side_effect=lambda **options: make_directory(dir=self.artifacts, **options),
        )
        self.temporary.start()
        self.cleanup = patch("worker.shutil.rmtree", side_effect=self.preserve)
        self.cleanup.start()
        self.app = create_app(self.worker, threading.Event(), {"http_enabled": True})
        self.client = self.app.test_client()
        self.worker.start()

    def preserve(self, directory, **kwargs):
        source = Path(directory)
        self.assertEqual(source.parent, self.artifacts)

    def tearDown(self):
        self.worker.stop()
        self.worker.join(6)
        self.cleanup.stop()
        self.temporary.stop()
        self.assertFalse(self.worker.is_alive())

    def finish(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.worker.get_job(job_id)
            if job["status"] in TERMINAL_STATUSES:
                return job
            time.sleep(0.01)
        self.fail("Worker did not finish")

    def test_completion_requires_pdf_available_and_child_exited(self):
        job_id = self.client.post("/scan", json={}).get_json()["job_id"]
        self.assertEqual(self.finish(job_id)["status"], "completed")
        self.assertTrue(
            self.worker.active_scan_process is None
            or self.worker.active_scan_process.poll() is not None
        )
        self.assertEqual(self.client.get(f"/scan/{job_id}/result").status_code, 200)

    def test_parent_scan_deadline_applies_despite_child_progress(self):
        self.scenario = "heartbeat"
        self.worker.scan_timeout_seconds = 1
        self.worker.gui_task_timeout_seconds = 3
        started = time.monotonic()
        job = self.finish(self.client.post("/scan", json={}).get_json()["job_id"])
        self.assertEqual(job["status"], "timed_out")
        self.assertEqual(job["error"]["code"], "scan_timeout")
        self.assertLess(time.monotonic() - started, 2)

    def test_parallel_result_downloads_consume_pdf_once(self):
        job_id = self.client.post("/scan", json={}).get_json()["job_id"]
        self.finish(job_id)
        self.worker.scan_queue.join()

        def download(_):
            with self.app.test_client() as client:
                return client.get(f"/scan/{job_id}/result").status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(download, range(24)))
        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(410), 23)
        self.assertIsNone(self.worker.jobs[job_id]["result_bytes"])
        self.worker.job_ttl_seconds = 0
        self.assertIsNone(self.worker.get_job(job_id))

    def test_invalid_requests_never_start_hardware(self):
        for endpoint in ("/scan", "/internal/protocol/scan"):
            for value in (
                [],
                True,
                42,
                "bad",
                {"metadata": []},
                {"callback_url": True},
                {"callback_url": "http://["},
                {"callback": "http://["},
            ):
                with self.subTest(endpoint=endpoint, value=value):
                    response = self.client.post(
                        endpoint,
                        data=json.dumps(value),
                        content_type="application/json",
                    )
                    self.assertEqual(response.status_code, 400)
            self.assertEqual(
                self.client.post(
                    endpoint, data="not-json", content_type="text/plain"
                ).status_code,
                415,
            )
            self.assertEqual(
                self.client.post(
                    endpoint, data="{", content_type="application/json"
                ).status_code,
                400,
            )
        self.assertEqual(self.worker.jobs, {})
