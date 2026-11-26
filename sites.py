"""Websites allowed to use ScanLink's browser API.

A website may scan when it is listed in ``cors_origins`` (set by hand or by IT)
or linked. A DjangoLux site links itself with ``POST /link``, naming the sites
its administrator allows; the operator approves the link once, in ScanLink's
own window, which names the requesting site as the browser reported it. A
linked site may later change its list without asking again, and the operator
unlinks it from the tray menu.
"""

import threading
import time
from datetime import datetime, timezone

from utils import get_logger, load_config, normalize_origin, save_config, url_origin

logger = get_logger()

MAX_SITES_PER_LINK = 20
MAX_LINKS = 50
# A declined website cannot open the approval window again for this long.
DECLINE_COOLDOWN_SECONDS = 600
LINK_PROMPT_SECONDS = 120


class LinkError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def save_links(links):
    config = load_config()
    config["linked_sites"] = links
    save_config(config)


class SiteRegistry:
    def __init__(self, listed=(), links=None, *, confirm=None, persist=save_links, clock=time.monotonic):
        """``confirm(origin, other_sites)`` returns True, False, or None when unanswered."""
        self._listed = frozenset(origin for origin in map(normalize_origin, listed or ()) if origin)
        self._links = {}
        for origin, link in (links or {}).items():
            origin = normalize_origin(origin)
            if origin and isinstance(link, dict):
                sites = [site for site in map(normalize_origin, link.get("sites") or ()) if site]
                self._links[origin] = {
                    "sites": list(dict.fromkeys([origin, *sites])),
                    "linked_at": str(link.get("linked_at") or ""),
                }
        self._confirm = confirm
        self._persist = persist
        self._clock = clock
        self._lock = threading.Lock()
        self._prompting = threading.Lock()
        self._declined = {}

    def is_allowed(self, origin):
        with self._lock:
            return self._allowed_locked(origin)

    def allows_callback(self, callback_url, requester=None):
        """Whether ScanLink may post a finished scan to ``callback_url``.

        The URL must point at a website the operator allowed. A browser request
        (``requester`` is its Origin) may only name its own website or a site
        linked together with it; a local tool or a ``scanlink://`` link, which
        has no Origin, may name any allowed website.
        """
        target = url_origin(callback_url)
        if target is None:
            return False
        with self._lock:
            if not self._allowed_locked(target):
                return False
            if requester is None:
                return True
            if not self._allowed_locked(requester):
                return False
            return target == requester or any(
                requester in link["sites"] and target in link["sites"]
                for link in self._links.values()
            )

    def _allowed_locked(self, origin):
        return (
            origin in self._listed
            or origin in self._links
            or any(origin in link["sites"] for link in self._links.values())
        )

    def link_for(self, origin):
        with self._lock:
            link = self._links.get(origin)
            return {"sites": list(link["sites"]), "linked_at": link["linked_at"]} if link else None

    def links(self):
        with self._lock:
            return {origin: list(link["sites"]) for origin, link in self._links.items()}

    def link(self, origin, sites):
        sites = self._clean_sites(origin, sites)
        with self._lock:
            link = self._links.get(origin)
            if link is not None:
                if link["sites"] != sites:
                    self._links[origin] = {**link, "sites": sites}
                    self._save()
                    logger.info("Linked website %r changed its allowed sites to %r", origin, sites)
                return {"linked": True, "prompted": False, "sites": sites}
            if len(self._links) >= MAX_LINKS:
                raise LinkError(409, "too_many_links", "ScanLink is linked to too many websites. Unlink one from the tray menu first.")
            declined_at = self._declined.get(origin)
            if declined_at is not None and self._clock() - declined_at < DECLINE_COOLDOWN_SECONDS:
                raise LinkError(403, "link_declined", "Linking this website was declined on this computer.")
        if not self._prompting.acquire(blocking=False):
            raise LinkError(409, "link_pending", "Another website is waiting for approval in ScanLink.")
        try:
            answer = self._ask(origin, sites[1:])
        finally:
            self._prompting.release()
        if answer is None:
            raise LinkError(408, "link_timeout", "Nobody answered ScanLink's approval window.")
        with self._lock:
            if not answer:
                self._declined[origin] = self._clock()
                logger.info("The operator declined linking %r", origin)
                raise LinkError(403, "link_declined", "Linking this website was declined on this computer.")
            self._declined.pop(origin, None)
            self._links[origin] = {
                "sites": sites,
                "linked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._save()
        logger.info("The operator linked %r; allowed sites %r", origin, sites)
        return {"linked": True, "prompted": True, "sites": sites}

    def unlink(self, origin):
        with self._lock:
            removed = self._links.pop(origin, None) is not None
            if removed:
                self._save()
        if removed:
            logger.info("The operator unlinked %r", origin)
        return removed

    def _ask(self, origin, other_sites):
        if self._confirm is None:
            return None
        try:
            return self._confirm(origin, other_sites)
        except Exception:
            logger.exception("Could not show the link approval window")
            return None

    def _save(self):
        try:
            self._persist({origin: dict(link) for origin, link in self._links.items()})
        except Exception:
            logger.exception("Could not save the linked websites")

    @staticmethod
    def _clean_sites(origin, sites):
        if sites is None:
            sites = []
        if not isinstance(sites, list):
            raise LinkError(400, "invalid_sites", "sites must be a list of website origins.")
        cleaned = [origin]
        for value in sites:
            site = normalize_origin(value)
            if site is None:
                raise LinkError(400, "invalid_site", f"{str(value)[:80]!r} is not a website origin such as https://example.org.")
            if site not in cleaned:
                cleaned.append(site)
        if len(cleaned) > MAX_SITES_PER_LINK:
            raise LinkError(400, "too_many_sites", f"A website can allow at most {MAX_SITES_PER_LINK} sites.")
        return cleaned
