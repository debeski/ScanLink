"""Websites allowed to use ScanLink's browser API.

A website may scan when it is listed in ``cors_origins`` (set by hand or by IT)
or linked. A DjangoLux site links itself with ``POST /link``, naming the sites
its administrator allows; the operator approves the link in ScanLink's own
window, which names the requesting site as the browser reported it. A linked
site may shorten its list without asking; a list that gains a site opens the
window again, naming the new sites. The operator unlinks a site from the tray
menu.

Approval windows are rationed: a declined or unanswered website's domain waits
before it can ask again, a website ScanLink does not know yet cannot open a
window shortly after another unknown website's window closed unanswered or
declined, and a website ScanLink already knows (linked, or allowed by a list)
closes an unknown website's open window to ask its own question.
"""

import ipaddress
import threading
import time
from collections import namedtuple
from datetime import datetime, timezone
from urllib.parse import urlsplit

from callback_transport import CallbackRefused, check_callback_url
from utils import get_logger, load_config, normalize_origin, save_config, url_origin

logger = get_logger()

MAX_SITES_PER_LINK = 20
MAX_LINKS = 50
# A declined website's domain cannot open the approval window again for this long.
DECLINE_COOLDOWN_SECONDS = 600
# Nor can an unanswered one's, for this long.
UNANSWERED_COOLDOWN_SECONDS = 300
# After an unknown website's window closes without Allow, other unknown websites wait this long.
UNKNOWN_PROMPT_INTERVAL_SECONDS = 120
# How long a known website waits for an unknown website's window to close.
PREEMPT_WAIT_SECONDS = 5
LINK_PROMPT_SECONDS = 120
# Second-level labels under which a registrable domain has three labels (example.co.uk).
_SHARED_SECOND_LEVEL = {"ac", "co", "com", "edu", "gov", "mil", "net", "nic", "org", "sch"}

_Prompt = namedtuple("_Prompt", "origin known cancel")


def cooldown_key(origin):
    """The part of an origin a cooldown applies to: its registrable domain, or its address."""
    host = (urlsplit(origin).hostname or "").rstrip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    labels = host.split(".")
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SHARED_SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


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
        """``confirm(origin, other_sites, added_sites=None, cancel=None)`` returns True, False,
        or None when unanswered or cancelled.

        ``added_sites`` lists what a linked website's list gains (None for a new link);
        ``cancel`` is a ``threading.Event`` that closes the window unanswered when set.
        """
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
        self._prompt = None
        # cooldown key -> (clock value it ends at, error code)
        self._cooldowns = {}
        self._unknown_prompt_after = None

    def is_allowed(self, origin):
        with self._lock:
            return self._allowed_locked(origin)

    def allows_callback(self, callback_url, requester=None):
        """Whether ScanLink may post a finished scan to ``callback_url``.

        The URL must be ``https`` on a public host (``check_callback_url``) and
        point at a website the operator allowed. A browser request
        (``requester`` is its Origin) may only name its own website or a site
        linked together with it; a local tool or a ``scanlink://`` link, which
        has no Origin, may name any allowed website. The address the host
        resolves to is checked again when the scan is sent.
        """
        try:
            check_callback_url(callback_url)
        except CallbackRefused:
            return False
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
            added = None
            if link is not None:
                added = [site for site in sites if site not in link["sites"]]
                if not added:
                    if link["sites"] != sites:
                        self._links[origin] = {**link, "sites": sites}
                        self._save()
                        logger.info("Linked website %r shortened its allowed sites to %r", origin, sites)
                    return {"linked": True, "prompted": False, "sites": sites}
            elif len(self._links) >= MAX_LINKS:
                raise LinkError(409, "too_many_links", "ScanLink is linked to too many websites. Unlink one from the tray menu first.")
            known = link is not None or self._allowed_locked(origin)
            self._check_cooldown_locked(origin, known)

        answer = self._ask_once(origin, sites[1:], added, known)

        with self._lock:
            if answer is not True:
                self._record_refusal_locked(origin, known, answered=answer is False)
            if answer is None:
                raise LinkError(408, "link_timeout", "Nobody answered ScanLink's approval window.")
            if answer is False:
                logger.info("The operator declined %s %r", "widening" if added else "linking", origin)
                raise LinkError(403, "link_declined", "Linking this website was declined on this computer.")
            self._cooldowns.pop(cooldown_key(origin), None)
            previous = self._links.get(origin)
            self._links[origin] = {
                "sites": sites,
                "linked_at": (previous or {}).get("linked_at")
                or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._save()
        if added:
            logger.info("The operator allowed %r to add %r; allowed sites %r", origin, added, sites)
        else:
            logger.info("The operator linked %r; allowed sites %r", origin, sites)
        return {"linked": True, "prompted": True, "sites": sites}

    def _check_cooldown_locked(self, origin, known):
        now = self._clock()
        ends_at, code = self._cooldowns.get(cooldown_key(origin), (None, None))
        if ends_at is not None and now < ends_at:
            if code == "link_declined":
                raise LinkError(403, "link_declined", "Linking this website was declined on this computer.")
            raise LinkError(429, "link_rate_limited", "ScanLink asked about this website recently. Try again in a few minutes.")
        if not known and self._unknown_prompt_after is not None and now < self._unknown_prompt_after:
            raise LinkError(429, "link_rate_limited", "ScanLink asked about another website recently. Try again in a few minutes.")

    def _record_refusal_locked(self, origin, known, answered):
        now = self._clock()
        if answered:
            self._cooldowns[cooldown_key(origin)] = (now + DECLINE_COOLDOWN_SECONDS, "link_declined")
        else:
            self._cooldowns[cooldown_key(origin)] = (now + UNANSWERED_COOLDOWN_SECONDS, "link_rate_limited")
        if not known:
            self._unknown_prompt_after = now + UNKNOWN_PROMPT_INTERVAL_SECONDS

    def _ask_once(self, origin, other_sites, added, known):
        """One approval window at a time; a known website closes an unknown website's window."""
        if not self._prompting.acquire(blocking=False):
            holder = self._prompt
            if not (known and holder is not None and not holder.known):
                raise LinkError(409, "link_pending", "Another website is waiting for approval in ScanLink.")
            holder.cancel.set()
            if not self._prompting.acquire(timeout=PREEMPT_WAIT_SECONDS):
                raise LinkError(409, "link_pending", "Another website is waiting for approval in ScanLink.")
            logger.info("Closed the approval window for %r to ask about %r", holder.origin, origin)
        prompt = _Prompt(origin, known, threading.Event())
        self._prompt = prompt
        try:
            answer = self._ask(origin, other_sites, added, prompt.cancel)
        finally:
            self._prompt = None
            self._prompting.release()
        if prompt.cancel.is_set():
            raise LinkError(409, "link_pending", "ScanLink closed this window to ask about a website it already knows.")
        return answer

    def unlink(self, origin):
        with self._lock:
            removed = self._links.pop(origin, None) is not None
            if removed:
                self._save()
        if removed:
            logger.info("The operator unlinked %r", origin)
        return removed

    def _ask(self, origin, other_sites, added, cancel):
        if self._confirm is None:
            return None
        try:
            return self._confirm(origin, other_sites, added_sites=added, cancel=cancel)
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
