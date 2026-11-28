"""Break-it round 2 regressions: jobs, results, the scan child and the listener (R2-118 … R2-125)."""

import io
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

import scan_runtime
import scanner
from gui.dialogs import site_list_size
from scanner import ScanError
from worker import ScanWorker, sweep_stale_directories

try:
    import server
except ImportError:
    server = None

ORIGIN = "https://crm.example"
PDF = b"%PDF-1.4\nscanned\n"


def completed_worker():
    worker = ScanWorker(queue.Queue())
    worker._run_scan_subprocess = lambda job_id, on_progress: io.BytesIO(PDF)
    job = worker.submit_job(doc_id="D-1", origin=ORIGIN)
    worker._process_job(worker.scan_queue.get_nowait())
    return worker, job["job_id"]


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class RequestValidationTests(unittest.TestCase):
    def setUp(self):
        self.worker = ScanWorker(queue.Queue())
        self.shutdown = threading.Event()
        self.client = server.create_app(
            self.worker, self.shutdown, {"http_enabled": True}, sites=MagicMock(is_allowed=lambda origin: True)
        ).test_client()

    def post(self, endpoint, body, **headers):
        return self.client.post(endpoint, data=body, content_type="application/json", headers=headers)

    def test_doc_ids_that_could_forge_log_lines_are_refused(self):
        # R2-122
        for endpoint in ("/scan", "/internal/protocol/scan"):
            for doc_id in ("D-1\n2026-11-27 - INFO - The operator linked 'https://forged.example'",
                           "D\r1", "D‮1", {"a": 1}, ["x"], True, 1.5, "x" * 201, 2 ** 70):
                with self.subTest(endpoint=endpoint, doc_id=doc_id):
                    response = self.post(endpoint, json.dumps({"doc_id": doc_id}))
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["error"]["code"], "invalid_doc_id")
        self.assertEqual(self.worker.jobs, {})

    def test_doc_ids_as_text_or_whole_numbers_are_kept(self):
        for doc_id in ("DOC-123", "وثيقة ١٢", 42):
            with self.subTest(doc_id=doc_id):
                self.worker.jobs.clear()
                self.worker.current_job_id = None
                response = self.post("/scan", json.dumps({"doc_id": doc_id}), Origin=ORIGIN)
                self.assertEqual(response.status_code, 202)
                status = self.client.get(f"/scan/{response.get_json()['job_id']}", headers={"Origin": ORIGIN})
                self.assertEqual(status.get_json()["doc_id"], doc_id)

    def test_nan_and_infinity_are_not_json(self):
        # R2-123: they were stored and echoed back as invalid JSON.
        for body in ('{"doc_id": NaN}', '{"doc_id": Infinity}', '{"metadata": {"n": -Infinity}}'):
            with self.subTest(body=body):
                response = self.post("/scan", body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"]["code"], "invalid_json")
        self.assertEqual(self.worker.jobs, {})

    def test_scanlinks_own_deliveries_cannot_reach_its_control_endpoints(self):
        # R2-010: a callback once shut ScanLink down through /shutdown.
        for endpoint in ("/shutdown", "/internal/protocol/scan", "/scan"):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, data=b"x", headers={"X-ScanLink-Delivery": "job-1"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["error"]["code"], "local_only")
        self.assertFalse(self.shutdown.is_set())


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class ResultDownloadTests(unittest.TestCase):
    def setUp(self):
        self.worker, self.job_id = completed_worker()
        self.client = server.create_app(
            self.worker, threading.Event(), {"http_enabled": True}, sites=MagicMock(is_allowed=lambda origin: True)
        ).test_client()
        self.url = f"/scan/{self.job_id}/result"

    def test_head_does_not_spend_the_result(self):
        # R2-120
        head = self.client.head(self.url, headers={"Origin": ORIGIN})
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.headers["Content-Length"], str(len(PDF)))
        self.assertEqual(head.data, b"")
        self.assertEqual(self.client.get(self.url, headers={"Origin": ORIGIN}).data, PDF)
        self.assertEqual(self.client.head(self.url, headers={"Origin": "https://evil.example"}).status_code, 404)

    def test_a_cut_off_download_can_be_retried_once(self):
        # R2-120: one dropped connection used to lose the scan.
        first = self.client.get(self.url, headers={"Origin": ORIGIN})
        retry = self.client.get(self.url, headers={"Origin": ORIGIN})
        third = self.client.get(self.url, headers={"Origin": ORIGIN})
        self.assertEqual((first.data, retry.data), (PDF, PDF))
        self.assertEqual(third.status_code, 410)
        self.assertIsNone(self.worker.jobs[self.job_id]["result_bytes"])

    def test_the_retry_window_closes(self):
        self.client.get(self.url, headers={"Origin": ORIGIN})
        later = time.monotonic() + 31
        with patch("worker.time.monotonic", return_value=later):
            self.assertEqual(self.client.get(self.url, headers={"Origin": ORIGIN}).status_code, 410)


class ResultLifetimeTests(unittest.TestCase):
    def test_wall_clock_jumps_do_not_decide_result_lifetime(self):
        # R2-121
        worker, job_id = completed_worker()
        with patch("worker.time.time", return_value=time.time() + 301):
            self.assertIsNotNone(worker.get_job(job_id))
        with patch("worker.time.time", return_value=time.time() - 86400):
            self.assertIsNotNone(worker.get_job(job_id))
        with patch("worker.time.monotonic", return_value=time.monotonic() + worker.result_ttl_seconds + 1):
            self.assertIsNone(worker.get_job(job_id))


class PageCountTests(unittest.TestCase):
    def test_the_child_reports_the_page_count_when_it_completes(self):
        # R2-118: the final state carried no page count, so short scans reported 0 or 1.
        directory = Path(tempfile.mkdtemp(prefix="scanlink-job-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        (directory / "request.json").write_text(json.dumps({"job_id": "job", "scan_timeout_seconds": 5}))

        def scan(job_id, progress_callback, deadline):
            for page in range(1, 6):
                progress_callback("page_scanned", page_count=page)
            progress_callback("generating_pdf", page_count=5)
            return io.BytesIO(PDF)

        manager = MagicMock()
        manager.return_value.scan_to_pdf.side_effect = scan
        with patch("scan_runtime.ScannerManager", manager), patch("scan_runtime.tk.Tk", MagicMock()), \
                patch("scan_runtime.init_gui", MagicMock()):
            self.assertEqual(scan_runtime.run_scan_job(str(directory)), 0)
        state = json.loads((directory / "state.json").read_text())
        self.assertEqual((state["status"], state["page_count"]), ("completed", 5))

    def test_the_parent_applies_the_final_page_count(self):
        worker = ScanWorker(queue.Queue())
        seen = []
        process = MagicMock(returncode=0)
        process.poll.return_value = 0
        states = iter([None, {"status": "completed", "page_count": 7}])

        with patch("worker.subprocess.Popen", return_value=process), \
                patch.object(worker, "_read_state_file", side_effect=lambda path: next(states)), \
                patch("worker.os.path.exists", return_value=True), \
                patch("builtins.open", unittest.mock.mock_open(read_data=PDF)):
            worker._run_scan_subprocess("job", lambda status, **data: seen.append((status, data)))
        self.assertEqual(seen, [("completed", {"page_count": 7})])


class OrphanedScanTests(unittest.TestCase):
    def test_stale_scan_folders_are_removed(self):
        # R2-119: a killed ScanLink left the scanned document in %TEMP%.
        root = Path(".xclude/test-output/sweep") / uuid.uuid4().hex
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        old = time.time() - 3600
        for name in ("scanlink-job-old", "scanlink-pages-old", "scanlink-job-fresh", "other-folder"):
            (root / name).mkdir()
            (root / name / "result.pdf").write_bytes(PDF)
            if name.endswith("old") or name == "other-folder":
                os.utime(root / name, (old, old))
        (root / "scanlink-job-file").write_bytes(b"not a folder")
        os.utime(root / "scanlink-job-file", (old, old))

        removed = sweep_stale_directories(str(root))

        self.assertEqual(sorted(removed), ["scanlink-job-old", "scanlink-pages-old"])
        self.assertEqual(sorted(p.name for p in root.iterdir()),
                         ["other-folder", "scanlink-job-file", "scanlink-job-fresh"])

    def test_the_child_stops_when_scanlink_ends(self):
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        gone = threading.Event()
        self.assertIsNotNone(scan_runtime.watch_parent(parent.pid, gone.set, interval=0.1))
        time.sleep(0.3)
        self.assertFalse(gone.is_set())
        parent.kill()
        parent.wait(5)
        self.assertTrue(gone.wait(3))

    def test_the_worker_tells_the_child_who_its_parent_is(self):
        worker = ScanWorker(queue.Queue())
        written = {}
        real_dump = json.dump

        def capture(payload, handle, **kwargs):
            written.update(payload)
            return real_dump(payload, handle, **kwargs)

        with patch("worker.json.dump", side_effect=capture), \
                patch("worker.subprocess.Popen", side_effect=OSError("no child")):
            with self.assertRaises(OSError):
                worker._run_scan_subprocess("job", lambda *a, **k: None)
        self.assertEqual(written["parent_pid"], os.getpid())


class _TimingOutSource:
    def acquire_natively(self, after, before, show_ui, modal):
        for index in range(11):
            before(None)
            after(object(), index < 10)


class ScanDeadlineTests(unittest.TestCase):
    def test_a_deadline_reached_while_pages_arrive_is_a_timeout(self):
        # R2-124: it was re-wrapped as acquire_failed / failed.
        manager = scanner.ScannerManager()
        pages = []

        def check(deadline, code, message):
            if "processing" in message and len(pages) >= 3:
                raise ScanError(code, message, status="timed_out")

        with patch.object(scanner, "twain", MagicMock()), \
                patch.object(manager, "_get_parent_window", return_value=0), \
                patch.object(manager, "_get_configs", return_value={}), \
                patch.object(manager, "_open_source", return_value=(MagicMock(), _TimingOutSource())), \
                patch.object(manager, "_configure_source"), \
                patch.object(manager, "_choose_transfer_mode", return_value="native"), \
                patch.object(manager, "_check_deadline", side_effect=check), \
                patch.object(manager, "_twain_image_to_pil", return_value=None), \
                patch.object(manager, "_encode_page", side_effect=lambda image: pages.append(1) or b"jpeg"):
            with self.assertRaises(ScanError) as caught:
                manager.scan_to_pdf("job", deadline=1)
        self.assertEqual((caught.exception.code, caught.exception.status), ("acquire_timeout", "timed_out"))


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class SlowClientTests(unittest.TestCase):
    def listener(self, **patches):
        for name, value in patches.items():
            patcher = patch(f"server.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)
        from tests.test_server import FakeWorker

        app = server.create_app(FakeWorker(), threading.Event(), {"http_enabled": True},
                                sites=MagicMock(is_allowed=lambda origin: True))
        listener = server.LoopbackServer(app, "127.0.0.1", 0, label="HTTP")
        listener.start()
        self.assertTrue(listener.started.wait(5))
        self.addCleanup(listener.join, 5)
        self.addCleanup(listener.shutdown)
        return listener.httpd.server_port

    def test_a_dripping_request_is_closed_at_the_deadline(self):
        # R2-125: the timeout restarted on every byte.
        port = self.listener(REQUEST_TIMEOUT_SECONDS=2, REQUEST_DEADLINE_SECONDS=1)
        sock = socket.create_connection(("127.0.0.1", port))
        self.addCleanup(sock.close)
        started = time.monotonic()
        closed = False
        for byte in b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: " + b"a" * 40:
            try:
                sock.sendall(bytes([byte]))
            except OSError:
                closed = True
                break
            sock.settimeout(0.4)
            try:
                if sock.recv(1024) == b"":
                    closed = True
                    break
            except socket.timeout:
                continue
            except OSError:
                closed = True
                break
        self.assertTrue(closed)
        self.assertLess(time.monotonic() - started, 4)

    def test_connections_beyond_the_cap_are_closed(self):
        port = self.listener(MAX_CONCURRENT_CONNECTIONS=2, REQUEST_TIMEOUT_SECONDS=5, REQUEST_DEADLINE_SECONDS=5)
        held = [socket.create_connection(("127.0.0.1", port)) for _ in range(2)]
        self.addCleanup(lambda: [sock.close() for sock in held])
        time.sleep(0.2)
        extra = socket.create_connection(("127.0.0.1", port))
        self.addCleanup(extra.close)
        extra.settimeout(2)
        try:
            self.assertEqual(extra.recv(1024), b"")
        except ConnectionResetError:
            pass
        for sock in held:
            sock.close()
        time.sleep(0.2)
        probe = socket.create_connection(("127.0.0.1", port))
        self.addCleanup(probe.close)
        probe.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        probe.settimeout(3)
        self.assertTrue(probe.recv(1024).startswith(b"HTTP/1.1 200"))


class ApprovalWindowTests(unittest.TestCase):
    def test_every_listed_site_is_shown_in_full(self):
        # R2-115: 6 rows of 56 characters cut off long or many sites.
        sites = [f"https://archive.office.test.{'a' * 40}.attacker{n}.example" for n in range(19)]
        rows, width = site_list_size(sites)
        self.assertEqual(rows, 19)
        self.assertGreaterEqual(width, max(len(site) for site in sites))
        self.assertEqual(site_list_size(["https://a.example"]), (1, 40))

    def test_the_listing_widget_has_every_row(self):
        import tkinter as tk

        from gui import dialogs

        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display for Tk")
        root.withdraw()
        self.addCleanup(root.destroy)
        sites = [f"https://archive.office.test.{'a' * 60}.attacker{n}.example" for n in range(19)]
        listing = dialogs._site_listing(tk.Frame(root), sites)
        self.assertEqual(listing.size(), 19)
        self.assertEqual(int(listing.cget("height")), 19)
        self.assertEqual(int(listing.cget("width")), dialogs.SITE_LIST_MAX_WIDTH)
        self.assertTrue(listing.cget("xscrollcommand"))


if __name__ == "__main__":
    unittest.main()
