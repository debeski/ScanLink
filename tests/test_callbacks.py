"""A finished scan reaches its callback URL, and only a linked website's."""

import io
import queue
import threading
import unittest
from unittest.mock import MagicMock, patch

from callback_transport import CallbackFailed, CallbackRefused
from sites import SiteRegistry
from worker import CallbackNotAllowedError, ScanWorker

try:
    import server
except ImportError:
    server = None

CRM = "https://crm.example"
SALES = "https://sales.example"
INTRANET = "https://intranet.example:8443"
EVIL = "https://evil.example"
PDF = b"%PDF-1.4\nscanned\n"


def registry():
    return SiteRegistry(
        listed=[INTRANET],
        links={CRM: {"sites": [SALES], "linked_at": "2026-11-25T00:00:00Z"}},
        persist=lambda links: None,
    )


def scan_worker(guard):
    worker = ScanWorker(queue.Queue(), callback_guard=guard)
    worker._run_scan_subprocess = lambda job_id, on_progress: io.BytesIO(PDF)
    return worker


def run_queued_job(worker, status_code=200, post_error=None):
    job_id = worker.scan_queue.get_nowait()
    with patch("worker.post_scan") as post:
        post.return_value = status_code
        if post_error is not None:
            post.side_effect = post_error
        worker._process_job(job_id)
        if worker.callback_thread is not None:
            worker.callback_thread.join(5)
    return job_id, post


class AllowsCallbackTests(unittest.TestCase):
    def test_local_callers_may_name_any_allowed_website(self):
        sites = registry()
        for url in (f"{CRM}/scans", f"{SALES}/upload?x=1", f"{INTRANET}/in"):
            with self.subTest(url=url):
                self.assertTrue(sites.allows_callback(url))
        self.assertFalse(sites.allows_callback(f"{EVIL}/steal"))

    def test_a_website_may_only_name_itself_or_the_sites_linked_with_it(self):
        sites = registry()
        self.assertTrue(sites.allows_callback(f"{CRM}/scans", CRM))
        self.assertTrue(sites.allows_callback(f"{SALES}/scans", CRM))
        self.assertTrue(sites.allows_callback(f"{CRM}/scans", SALES))
        self.assertFalse(sites.allows_callback(f"{INTRANET}/scans", CRM))
        self.assertTrue(sites.allows_callback(f"{INTRANET}/scans", INTRANET))
        self.assertFalse(sites.allows_callback(f"{CRM}/scans", INTRANET))
        self.assertFalse(sites.allows_callback(f"{EVIL}/scans", EVIL))

    def test_disguised_and_malformed_urls_are_refused(self):
        sites = registry()
        for url in (
            "https://crm.example@evil.example/scans",
            "https://user:pw@crm.example/scans",
            "https://crm.example.evil.example/scans",
            "http://crm.example/scans",
            "https://127.0.0.1/scans",
            "https://crm.example:8443/scans",
            "ftp://crm.example/scans",
            "/relative/scans",
            "http://[",
            "",
            None,
            5,
        ):
            with self.subTest(url=url):
                self.assertFalse(sites.allows_callback(url))


class CallbackDeliveryTests(unittest.TestCase):
    def test_finished_scan_is_posted_to_its_callback(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(doc_id="D-1", callback_url=f"{CRM}/scans/upload", origin=CRM)

        _job_id, post = run_queued_job(worker, status_code=201)

        post.assert_called_once()
        (url, fields, files), kwargs = post.call_args
        self.assertEqual(url, f"{CRM}/scans/upload")
        self.assertEqual(files, [("pdf", (f"scan_{queued['job_id']}.pdf", PDF, "application/pdf"))])
        self.assertEqual(dict(fields)["doc_id"], "D-1")
        self.assertEqual(dict(fields)["job_id"], queued["job_id"])
        self.assertEqual(kwargs["delivery_id"], queued["job_id"])
        job = worker.get_job(queued["job_id"])
        self.assertEqual(job["callback"], {"state": "delivered", "status_code": 201})
        self.assertNotIn("callback_url", job)
        _job, result = worker.consume_result(queued["job_id"])
        self.assertEqual(result, PDF)

    def test_unlinked_callback_is_refused_before_any_scan(self):
        worker = scan_worker(registry().allows_callback)
        with self.assertRaises(CallbackNotAllowedError):
            worker.submit_job(callback_url=f"{EVIL}/steal")
        with self.assertRaises(CallbackNotAllowedError):
            worker.submit_job(callback_url=f"{INTRANET}/scans", origin=CRM)
        self.assertTrue(worker.scan_queue.empty())
        self.assertEqual(worker.jobs, {})

    def test_without_a_guard_every_callback_is_refused(self):
        worker = scan_worker(None)
        with self.assertRaises(CallbackNotAllowedError):
            worker.submit_job(callback_url=f"{CRM}/scans")
        self.assertIsNotNone(worker.submit_job(doc_id="no-callback"))

    def test_website_unlinked_during_the_scan_gets_nothing(self):
        linked = {"now": True}
        worker = scan_worker(lambda url, origin: linked["now"])
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)
        linked["now"] = False

        _job_id, post = run_queued_job(worker)

        post.assert_not_called()
        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "refused", "reason": "not_linked"})

    def test_a_redirect_counts_as_failed(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)

        run_queued_job(worker, status_code=302)

        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "failed", "status_code": 302})

    def test_a_destination_that_resolves_to_a_private_address_is_refused(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)

        run_queued_job(worker, post_error=CallbackRefused("blocked_address"))

        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "refused", "reason": "blocked_address"})
        _job, result = worker.consume_result(queued["job_id"])
        self.assertEqual(result, PDF)

    def test_unreachable_callback_keeps_the_result_for_polling(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)

        run_queued_job(worker, post_error=CallbackFailed("refused"))

        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "failed", "reason": "unreachable"})
        _job, result = worker.consume_result(queued["job_id"])
        self.assertEqual(result, PDF)

    def test_failed_scan_reports_the_callback_as_not_sent(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)
        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "waiting"})

        worker._fail_job(queued["job_id"], code="no_scanner", message="No scanner.")

        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "not_sent"})

    def test_slow_callback_does_not_hold_the_worker(self):
        worker = scan_worker(registry().allows_callback)
        worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)
        job_id = worker.scan_queue.get_nowait()
        release = threading.Event()
        with patch("worker.post_scan") as post:
            post.side_effect = lambda *a, **k: release.wait(5) and 200
            worker._process_job(job_id)
            self.assertTrue(worker.callback_thread.is_alive())
            self.assertIsNotNone(worker.submit_job(doc_id="next"))
            release.set()
            worker.callback_thread.join(5)

    def test_callbacks_in_flight_are_capped(self):
        # R2-055: every hanging callback used to keep its own thread and PDF.
        worker = scan_worker(registry().allows_callback)
        release = threading.Event()
        threads = []
        with patch("worker.post_scan") as post:
            post.side_effect = lambda *a, **k: release.wait(5) and 200
            jobs = []
            for _ in range(3):
                jobs.append(worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)["job_id"])
                worker._process_job(worker.scan_queue.get_nowait())
                threads.append(worker.callback_thread)
            self.assertEqual(worker.get_job(jobs[2])["callback"], {"state": "failed", "reason": "busy"})
            release.set()
            for thread in threads[:2]:
                thread.join(5)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(worker.get_job(jobs[0])["callback"], {"state": "delivered", "status_code": 200})


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class CallbackRequestTests(unittest.TestCase):
    def setUp(self):
        sites = registry()
        self.worker = ScanWorker(queue.Queue(), callback_guard=sites.allows_callback)
        self.client = server.create_app(
            self.worker, threading.Event(), {"http_enabled": True, "https_enabled": False}, sites=sites
        ).test_client()

    def test_browser_scan_with_a_foreign_callback_is_refused(self):
        response = self.client.post(
            "/scan", json={"callback_url": f"{EVIL}/steal"}, headers={"Origin": CRM}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "callback_not_allowed")
        self.assertEqual(self.worker.jobs, {})

    def test_callbacks_to_this_computer_or_its_network_are_refused(self):
        # R2-010: a linked site could list loopback, private or metadata
        # addresses, or ScanLink itself, and receive the scan there.
        local = "http://127.0.0.1:18702"
        sites = SiteRegistry(listed=[CRM], links={
            CRM: {"sites": [local, "http://localhost:5000", "https://10.0.0.5", "https://169.254.169.254",
                            "https://[::ffff:127.0.0.1]", "https://2130706433", "https://localhost",
                            "https://scanner.localhost"]},
        }, persist=lambda links: None)
        for url in (f"{local}/api/admin/reset?all=1", "http://localhost:5000/shutdown", "https://10.0.0.5/in",
                    "https://169.254.169.254/latest/meta-data", "https://[::ffff:127.0.0.1]/x",
                    "https://2130706433/x", "https://localhost/x", "https://scanner.localhost/x"):
            with self.subTest(url=url):
                self.assertFalse(sites.allows_callback(url, CRM))
                self.assertFalse(sites.allows_callback(url))

    def test_browser_scan_may_call_back_to_its_linked_site(self):
        response = self.client.post(
            "/scan", json={"callback_url": f"{SALES}/scans"}, headers={"Origin": CRM}
        )

        self.assertEqual(response.status_code, 202)

    def test_scanlink_link_with_a_foreign_callback_is_refused(self):
        response = self.client.post("/internal/protocol/scan", json={"callback": f"{EVIL}/steal"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "callback_not_allowed")
        self.assertEqual(self.worker.jobs, {})


if __name__ == "__main__":
    unittest.main()
