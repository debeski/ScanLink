import io
import queue
import time
import unittest
from unittest.mock import patch

from worker import BusyError, ScanWorker


class FakeScannerManager:
    def is_available(self):
        return True

    def scan_to_pdf(self, request_id, progress_callback=None, deadline=None):
        if progress_callback:
            progress_callback("processing")
            progress_callback("acquiring")
            progress_callback("page_scanned", page_count=1)
            progress_callback("generating_pdf", page_count=1)
        return io.BytesIO(b"%PDF-1.4\nfake\n")


class WorkerTests(unittest.TestCase):
    def test_submit_job_rejects_second_active_job(self):
        worker = ScanWorker(queue.Queue())
        worker.submit_job(doc_id="1")

        with self.assertRaises(BusyError):
            worker.submit_job(doc_id="2")

    def test_process_job_marks_completion_and_stores_result(self):
        worker = ScanWorker(queue.Queue())
        worker._run_scan_subprocess = (
            lambda job_id, on_progress: FakeScannerManager().scan_to_pdf(
                job_id,
                progress_callback=on_progress,
            )
        )

        queued = worker.submit_job(doc_id="abc")
        queued_job_id = worker.scan_queue.get_nowait()
        worker._process_job(queued_job_id)

        snapshot = worker.get_job(queued["job_id"])
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["page_count"], 1)

        completed_job, result_bytes = worker.consume_result(queued["job_id"])
        self.assertEqual(completed_job["status"], "completed")
        self.assertEqual(result_bytes, b"%PDF-1.4\nfake\n")

    def test_consumed_result_keeps_metadata_until_job_ttl(self):
        worker = ScanWorker(queue.Queue())
        now = time.time()
        worker.jobs["job-1"] = {
            "job_id": "job-1",
            "status": "completed",
            "submitted_at": now,
            "updated_at": now,
            "started_at": now,
            "completed_at": now,
            "doc_id": None,
            "callback_url": None,
            "metadata": {},
            "page_count": 1,
            "result_bytes": b"pdf",
            "result_retrieved_at": None,
            "source": "test",
            "error": None,
        }

        _job, result_bytes = worker.consume_result("job-1")
        self.assertEqual(result_bytes, b"pdf")
        self.assertIsNone(worker.jobs["job-1"]["result_bytes"])
        self.assertEqual(worker.get_job("job-1")["status"], "completed")
        worker.job_ttl_seconds = 0
        self.assertIsNone(worker.get_job("job-1"))

    def test_unparseable_callback_is_skipped(self):
        worker = ScanWorker(queue.Queue())
        with patch("worker.requests") as requests:
            worker._send_callback({"job_id": "job-1", "callback_url": "http://["}, b"pdf")
        requests.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
