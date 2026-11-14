import threading
import unittest
from unittest.mock import patch

from tests.test_server import FakeWorker
from utils import _normalize_config, normalize_origin

try:
    import server
    from sites import DECLINE_COOLDOWN_SECONDS, MAX_SITES_PER_LINK, SiteRegistry
except ImportError:
    server = None

ARCHIVE = {"Origin": "https://archive.example"}
CRM = {"Origin": "https://crm.example"}
EVIL = {"Origin": "https://evil.example"}


class OriginTests(unittest.TestCase):
    def test_only_plain_website_origins_are_accepted(self):
        for value, expected in (
            ("https://archive.example", "https://archive.example"),
            ("https://Archive.Example:443/", "https://archive.example"),
            ("http://intranet:8080", "http://intranet:8080"),
            ("http://[::1]:8000", "http://[::1]:8000"),
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_origin(value), expected)
        for value in ("*", "null", "", None, 5, "file:///c:/x", "https://*.example", "https://a.example/path",
                      "https://user:pw@a.example", "https://a.example?x=1", "javascript:alert(1)", "https://"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_origin(value))

    def test_saved_wildcard_and_bad_links_are_dropped_on_load(self):
        config = _normalize_config({
            "cors_origins": ["*", "https://archive.example", "https://archive.example/"],
            "linked_sites": {
                "https://crm.example": {"sites": ["https://sales.example", "*"], "linked_at": "2026-11-14T00:00:00Z"},
                "*": {"sites": []},
                "https://bad.example": "not a link",
            },
        })
        self.assertEqual(config["cors_origins"], ["https://archive.example"])
        self.assertEqual(config["linked_sites"], {
            "https://crm.example": {"sites": ["https://crm.example", "https://sales.example"],
                                    "linked_at": "2026-11-14T00:00:00Z"},
        })


@unittest.skipIf(server is None, "Flask is not installed in this environment")
class LinkTests(unittest.TestCase):
    def setUp(self):
        self.answers = []
        self.asked = []
        self.saved = []
        self.now = [1000.0]
        self.sites = SiteRegistry(
            ["https://listed.example"],
            confirm=self.confirm,
            persist=self.saved.append,
            clock=lambda: self.now[0],
        )
        self.worker = FakeWorker()
        self.client = server.create_app(
            self.worker, threading.Event(), {"http_enabled": True}, self.sites
        ).test_client()

    def confirm(self, origin, other_sites):
        self.asked.append((origin, other_sites))
        return self.answers.pop(0) if self.answers else None

    def link(self, headers, sites=()):
        return self.client.post("/link", json={"sites": list(sites)}, headers=headers)

    def test_an_unlinked_site_can_read_why_it_is_refused(self):
        health = self.client.get("/health", headers=EVIL)
        self.assertEqual(health.status_code, 403)
        self.assertEqual(health.get_json()["error"]["code"], "origin_not_allowed")
        self.assertEqual(health.headers["Access-Control-Allow-Origin"], EVIL["Origin"])
        preflight = self.client.options("/link", headers={**EVIL, "Access-Control-Request-Method": "POST"})
        self.assertEqual(preflight.status_code, 204)
        self.assertEqual(preflight.headers["Access-Control-Allow-Origin"], EVIL["Origin"])

    def test_an_approved_link_allows_the_site_and_the_sites_its_admin_lists(self):
        self.answers.append(True)
        response = self.link(ARCHIVE, ["https://crm.example", "https://archive.example", "https://CRM.example/"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "linked": True, "prompted": True, "sites": ["https://archive.example", "https://crm.example"],
        })
        self.assertEqual(self.asked, [("https://archive.example", ["https://crm.example"])])
        self.assertEqual(list(self.saved[-1]), ["https://archive.example"])

        health = self.client.get("/health", headers=ARCHIVE).get_json()
        self.assertEqual(health["link"], {"linked": True, "sites": ["https://archive.example", "https://crm.example"]})
        self.assertEqual(self.client.get("/health", headers=CRM).get_json()["link"], {"linked": False, "sites": []})
        self.assertEqual(self.client.post("/scan", json={}, headers=CRM).status_code, 202)
        self.assertEqual(self.client.post("/scan", json={}, headers=EVIL).status_code, 403)

    def test_a_linked_site_changes_its_list_without_asking_again(self):
        self.answers.append(True)
        self.link(ARCHIVE, ["https://crm.example"])
        response = self.link(ARCHIVE, ["https://sales.example"])
        self.assertEqual(response.get_json()["prompted"], False)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.client.get("/health", headers=CRM).status_code, 403)
        self.assertEqual(self.client.get("/health", headers={"Origin": "https://sales.example"}).status_code, 200)

    def test_a_listed_site_cannot_change_another_sites_link(self):
        self.answers.append(True)
        self.link(ARCHIVE, ["https://crm.example"])
        self.answers.append(False)
        response = self.link(CRM, ["https://evil.example"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(self.client.get("/health", headers=EVIL).status_code, 403)

    def test_a_declined_site_cannot_ask_again_until_the_cooldown_ends(self):
        self.answers.append(False)
        first = self.link(EVIL)
        self.assertEqual((first.status_code, first.get_json()["error"]["code"]), (403, "link_declined"))
        self.assertEqual(first.headers["Access-Control-Allow-Origin"], EVIL["Origin"])
        again = self.link(EVIL)
        self.assertEqual(again.get_json()["error"]["code"], "link_declined")
        self.assertEqual(len(self.asked), 1)
        self.now[0] += DECLINE_COOLDOWN_SECONDS + 1
        self.answers.append(True)
        self.assertEqual(self.link(EVIL).status_code, 200)
        self.assertEqual(len(self.asked), 2)

    def test_an_unanswered_window_links_nothing(self):
        response = self.link(EVIL)
        self.assertEqual((response.status_code, response.get_json()["error"]["code"]), (408, "link_timeout"))
        self.assertEqual(self.client.get("/health", headers=EVIL).status_code, 403)
        self.assertEqual(self.saved, [])

    def test_one_approval_window_at_a_time(self):
        opened, release = threading.Event(), threading.Event()

        def slow_confirm(origin, other_sites):
            opened.set()
            release.wait(5)
            return True

        self.sites._confirm = slow_confirm
        results = {}
        thread = threading.Thread(target=lambda: results.setdefault("first", self.link(ARCHIVE)))
        thread.start()
        self.assertTrue(opened.wait(5))
        try:
            second = self.link(EVIL)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual((second.status_code, second.get_json()["error"]["code"]), (409, "link_pending"))
        self.assertEqual(results["first"].status_code, 200)
        self.assertEqual(self.client.get("/health", headers=EVIL).status_code, 403)

    def test_bad_link_requests_are_refused_without_a_window(self):
        too_many = [f"https://s{n}.example" for n in range(MAX_SITES_PER_LINK)]
        for headers, body, code in (
            ({}, {"sites": []}, "origin_required"),
            ({"Origin": "null"}, {"sites": []}, "origin_required"),
            (ARCHIVE, ["https://a.example"], "invalid_payload"),
            (ARCHIVE, {"sites": "https://a.example"}, "invalid_sites"),
            (ARCHIVE, {"sites": ["https://*.example"]}, "invalid_site"),
            (ARCHIVE, {"sites": ["*"]}, "invalid_site"),
            (ARCHIVE, {"sites": too_many}, "too_many_sites"),
        ):
            with self.subTest(code=code, headers=headers):
                response = self.client.post("/link", json=body, headers=headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"]["code"], code)
        self.assertEqual(self.asked, [])

    def test_link_keeps_the_loopback_host_check(self):
        response = self.client.post("/link", json={"sites": []}, headers={**EVIL, "Host": "evil.example:5000"})
        self.assertEqual(response.get_json()["error"]["code"], "invalid_host")
        self.assertEqual(self.asked, [])

    def test_unlinking_removes_the_site_and_its_list(self):
        self.answers.append(True)
        self.link(ARCHIVE, ["https://crm.example"])
        self.assertTrue(self.sites.unlink("https://archive.example"))
        self.assertEqual(self.saved[-1], {})
        for headers in (ARCHIVE, CRM):
            self.assertEqual(self.client.get("/health", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/health", headers={"Origin": "https://listed.example"}).status_code, 200)

    def test_saved_links_are_restored(self):
        self.answers.append(True)
        self.link(ARCHIVE, ["https://crm.example"])
        restored = SiteRegistry([], self.saved[-1])
        self.assertTrue(restored.is_allowed("https://crm.example"))
        self.assertEqual(restored.link_for("https://archive.example")["sites"],
                         ["https://archive.example", "https://crm.example"])

    def test_config_wiring_links_from_the_saved_file(self):
        with patch("server.load_config", return_value=_normalize_config({
            "cors_origins": ["*"],
            "linked_sites": {"https://archive.example": {"sites": ["https://crm.example"]}},
        })):
            client = server.create_app(FakeWorker(), threading.Event(), {"http_enabled": True}).test_client()
        self.assertEqual(client.post("/scan", json={}, headers=CRM).status_code, 202)
        self.assertEqual(client.post("/scan", json={}, headers=EVIL).status_code, 403)
        self.assertEqual(client.post("/link", json={"sites": []}, headers=EVIL).get_json()["error"]["code"],
                         "link_timeout")


if __name__ == "__main__":
    unittest.main()
