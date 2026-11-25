"""A finished scan reaches its callback URL, and only a linked website's."""

import io
import queue
import threading
import unittest
from unittest.mock import MagicMock, patch

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
    with patch("worker.requests") as requests:
        requests.post.return_value = MagicMock(status_code=status_code)
        if post_error is not None:
            requests.post.side_effect = post_error
        worker._process_job(job_id)
        if worker.callback_thread is not None:
            worker.callback_thread.join(5)
    return job_id, requests.post


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
        args, kwargs = post.call_args
        self.assertEqual(args, (f"{CRM}/scans/upload",))
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(kwargs["files"]["pdf"][1], PDF)
        self.assertEqual(kwargs["data"]["doc_id"], "D-1")
        self.assertEqual(kwargs["data"]["job_id"], queued["job_id"])
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

    def test_a_redirect_is_not_followed(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)

        _job_id, post = run_queued_job(worker, status_code=302)

        self.assertIs(post.call_args.kwargs["allow_redirects"], False)
        self.assertEqual(worker.get_job(queued["job_id"])["callback"], {"state": "failed", "status_code": 302})

    def test_unreachable_callback_keeps_the_result_for_polling(self):
        worker = scan_worker(registry().allows_callback)
        queued = worker.submit_job(callback_url=f"{CRM}/scans", origin=CRM)

        run_queued_job(worker, post_error=ConnectionError("refused"))

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
        with patch("worker.requests") as requests:
            requests.post.side_effect = lambda *a, **k: release.wait(5) and MagicMock(status_code=200)
            worker._process_job(job_id)
            self.assertTrue(worker.callback_thread.is_alive())
            self.assertIsNotNone(worker.submit_job(doc_id="next"))
            release.set()
            worker.callback_thread.join(5)


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
