"""Posting a finished scan to a callback URL on the public internet only.

A callback leaves the operator's computer with a scanned document, so its
destination is checked twice: the URL itself when the scan is requested
(``check_callback_url``), and the address ScanLink actually connects to when it
sends (``post_scan``). The second check resolves the host name itself, refuses
the delivery if any address it resolves to is not a public one, and connects to
the checked address, so a host name re-pointed between the check and the
connection (DNS rebinding) cannot reach this computer or its network.

Refused destinations: anything but ``https``; ``localhost`` and ``*.localhost``;
loopback, private, carrier-grade NAT, link-local (cloud metadata), unique-local,
multicast, reserved, unspecified and documentation addresses, including IPv4
addresses embedded in IPv6 (mapped, NAT64, 6to4, Teredo); and every address of
this computer itself.
"""

import http.client
import ipaddress
import socket
import ssl
import threading
import time
import unicodedata
import uuid
from urllib.parse import urlsplit

try:
    import certifi
except ImportError:
    certifi = None

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 30
# Whole delivery, from resolving the host to reading the status line and headers.
DELIVERY_DEADLINE_SECONDS = 120
DELIVERY_HEADER = "X-ScanLink-Delivery"

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_LOCAL_NAT64 = ipaddress.ip_network("64:ff9b:1::/48")


class CallbackRefused(Exception):
    """The destination is not a public https website."""

    def __init__(self, reason, detail=""):
        super().__init__(detail or reason)
        self.reason = reason


class CallbackFailed(Exception):
    """The destination could not be reached or did not answer in time."""


def _embedded_ipv4(address):
    if address.version != 6:
        return None
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address in _NAT64 or address in _LOCAL_NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    # IPv4-compatible ::a.b.c.d (deprecated, still routed by some stacks).
    if int(address) >> 32 == 0 and int(address) > 1:
        return ipaddress.IPv4Address(int(address))
    return None


def is_public_address(value):
    """True only for a globally routable unicast address."""
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0] if isinstance(value, str) else value)
    except ValueError:
        return False
    embedded = _embedded_ipv4(address)
    if embedded is not None and not is_public_address(embedded):
        return False
    return bool(
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_unspecified
        and not address.is_private
    )


def _literal_address(host):
    """The address a host spelled as a number means, in any notation the resolver accepts."""
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    try:
        # Shorthand, decimal, octal and hex spellings such as 127.1 or 0x7f000001.
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def _clean_host(host):
    if not host:
        return None
    host = host.rstrip(".").lower()
    if not host or any(unicodedata.category(ch)[0] in "CZ" for ch in host):
        return None
    return host


def check_callback_url(url):
    """``(host, port, path)`` for a callback URL ScanLink may post to; else ``CallbackRefused``.

    Host names are only checked here; their addresses are checked when sending.
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise CallbackRefused("invalid_url")
    try:
        parts = urlsplit(url.strip())
        port = parts.port or 443
    except ValueError as exc:
        raise CallbackRefused("invalid_url") from exc
    if parts.scheme != "https":
        raise CallbackRefused("https_required")
    if parts.username is not None or parts.password is not None:
        raise CallbackRefused("invalid_url")
    host = _clean_host(parts.hostname)
    if host is None:
        raise CallbackRefused("invalid_url")
    if host == "localhost" or host.endswith(".localhost"):
        raise CallbackRefused("blocked_address")
    literal = _literal_address(host)
    if literal is not None and not is_public_address(literal):
        raise CallbackRefused("blocked_address")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in path):
        raise CallbackRefused("invalid_url")
    return host, port, path


def _own_addresses():
    addresses = set()
    for name in {socket.gethostname(), socket.getfqdn()}:
        try:
            for info in socket.getaddrinfo(name, None):
                addresses.add(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
        except (OSError, ValueError):
            continue
    return addresses


def resolve_public(host, port, resolver=None, own_addresses=None):
    """Every address ``host`` resolves to, refusing the host if any of them is not public."""
    resolver = resolver or socket.getaddrinfo
    own_addresses = own_addresses or _own_addresses
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CallbackFailed(f"Could not resolve {host!r}: {exc}") from exc
    own = own_addresses()
    candidates = []
    for family, socktype, proto, _canonname, sockaddr in infos:
        address = sockaddr[0]
        if not is_public_address(address):
            raise CallbackRefused("blocked_address", f"{host!r} resolves to {address}")
        try:
            if ipaddress.ip_address(address.split("%", 1)[0]) in own:
                raise CallbackRefused("blocked_address", f"{host!r} resolves to this computer")
        except ValueError:
            raise CallbackRefused("blocked_address", f"{host!r} resolves to {address!r}")
        candidates.append((family, socktype, proto, sockaddr))
    if not candidates:
        raise CallbackFailed(f"{host!r} has no address")
    return candidates


class _Watchdog:
    """Closes the connection when the whole delivery runs past its deadline."""

    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds
        self.expired = False
        self._sock = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self):
        return self.deadline - time.monotonic()

    def watch(self, sock):
        with self._lock:
            self._sock = sock
            if self.expired:
                self._close()

    def _expire(self):
        with self._lock:
            self.expired = True
            self._close()

    def _close(self):
        if self._sock is None:
            return
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def cancel(self):
        self._timer.cancel()


def _ssl_context():
    context = ssl.create_default_context()
    if certifi is not None:
        try:
            context.load_verify_locations(certifi.where())
        except OSError:
            pass
    return context


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects only to addresses ``resolve_public`` approved; verifies TLS for the host name."""

    def __init__(self, host, port, watchdog, resolver, own_addresses, context):
        super().__init__(host, port, timeout=READ_TIMEOUT_SECONDS, context=context)
        self._watchdog = watchdog
        self._resolver = resolver
        self._own_addresses = own_addresses
        self._ssl_context = context
        self.peer_address = None

    def connect(self):
        candidates = resolve_public(self.host, self.port, self._resolver, self._own_addresses)
        last_error = None
        for family, socktype, proto, sockaddr in candidates:
            remaining = self._watchdog.remaining()
            if remaining <= 0:
                break
            sock = socket.socket(family, socktype, proto)
            self._watchdog.watch(sock)
            try:
                sock.settimeout(min(CONNECT_TIMEOUT_SECONDS, remaining))
                sock.connect(sockaddr)
                peer = sock.getpeername()[0]
                if not is_public_address(peer):
                    raise CallbackRefused("blocked_address", f"connected to {peer}")
                sock.settimeout(READ_TIMEOUT_SECONDS)
                self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)
                self._watchdog.watch(self.sock)
                self.peer_address = peer
                return
            except CallbackRefused:
                sock.close()
                raise
            except OSError as exc:
                last_error = exc
                sock.close()
        raise CallbackFailed(f"Could not connect to {self.host!r}: {last_error or 'deadline reached'}")


def encode_multipart(fields, files):
    boundary = f"scanlink-{uuid.uuid4().hex}"
    chunks = []
    for name, value in fields:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii")
            + str(value).encode("utf-8")
            + b"\r\n"
        )
    for name, (filename, content, content_type) in files:
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("ascii")
            + content
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post_scan(
    url,
    fields,
    files,
    *,
    delivery_id,
    user_agent="ScanLink",
    deadline_seconds=DELIVERY_DEADLINE_SECONDS,
    resolver=None,
    own_addresses=None,
    context=None,
):
    """POST a multipart scan to ``url``; returns the HTTP status code.

    The response body is never read, redirects are never followed, proxies are
    never used, and the whole exchange ends at ``deadline_seconds``.
    """
    host, port, path = check_callback_url(url)
    body, content_type = encode_multipart(fields, files)
    watchdog = _Watchdog(deadline_seconds)
    connection = _PinnedHTTPSConnection(
        host, port, watchdog, resolver, own_addresses, context or _ssl_context()
    )
    try:
        connection.putrequest("POST", path, skip_accept_encoding=True)
        connection.putheader("Accept-Encoding", "identity")
        connection.putheader("Content-Type", content_type)
        connection.putheader("Content-Length", str(len(body)))
        connection.putheader("User-Agent", user_agent)
        connection.putheader(DELIVERY_HEADER, delivery_id)
        connection.endheaders(body)
        response = connection.getresponse()
        return response.status
    except (CallbackRefused, CallbackFailed):
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        if watchdog.expired:
            raise CallbackFailed(f"No answer within {deadline_seconds} seconds") from exc
        raise CallbackFailed(str(exc) or exc.__class__.__name__) from exc
    finally:
        watchdog.cancel()
        try:
            connection.close()
        except Exception:
            pass


__all__ = [
    "CallbackFailed",
    "CallbackRefused",
    "DELIVERY_HEADER",
    "check_callback_url",
    "is_public_address",
    "post_scan",
    "resolve_public",
]
