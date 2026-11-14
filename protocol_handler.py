"""
Protocol helpers for scanlink:// URLs and single-instance forwarding.
"""

from urllib.parse import parse_qs, urlparse

try:
    import requests
except ImportError:
    requests = None

from utils import HTTP_HOST, HTTP_PORT, get_logger

logger = get_logger()

PROTOCOL_SCHEME = "scanlink"
INTERNAL_PROTOCOL_ENDPOINT = f"http://{HTTP_HOST}:{HTTP_PORT}/internal/protocol/scan"
HEALTH_ENDPOINT = f"http://{HTTP_HOST}:{HTTP_PORT}/health"


def parse_protocol_url(url):
    """
    Parse a scanlink:// URL and return a structured command object.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() != PROTOCOL_SCHEME:
            logger.warning(f"Invalid protocol scheme: {parsed.scheme}")
            return None

        action = parsed.netloc.lower() if parsed.netloc else "scan"
        params = parse_qs(parsed.query)

        doc_id = params.get("docId", params.get("doc_id", [None]))[0]
        callback_url = params.get("callback", params.get("callback_url", [None]))[0]

        result = {
            "action": action,
            "doc_id": doc_id,
            "callback_url": callback_url,
        }
        logger.info("Parsed protocol URL: %r", result)
        return result
    except Exception as exc:
        logger.error("Failed to parse protocol URL %r: %s", url, exc)
        return None


def is_protocol_url(arg):
    """Check if a command-line argument is a scanlink:// URL."""
    if not arg:
        return False
    return arg.lower().startswith(f"{PROTOCOL_SCHEME}://")


def extract_protocol_url_from_args(args):
    """Extract the first scanlink:// URL from command-line arguments."""
    for arg in args:
        if is_protocol_url(arg):
            return arg
    return None


def _json_object(response):
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_existing_instance_running(timeout=1.0):
    """Probe the loopback HTTP health endpoint for an already-running helper."""
    if requests is None:
        logger.warning("requests is not installed; cannot probe for an existing ScanLink instance")
        return False

    try:
        response = requests.get(HEALTH_ENDPOINT, timeout=timeout)
    except requests.RequestException:
        return False
    # Another program on port 5000 must not make ScanLink exit as a duplicate.
    health = _json_object(response)
    return (
        response.ok
        and health.get("status") == "ok"
        and "version" in health
        and "twain_available" in health
    )


def forward_protocol_command(command, timeout=3.0):
    """
    Forward a protocol-triggered scan request into the already-running instance.
    Returns True when the request was handed off successfully.
    """
    if not command or command.get("action") != "scan":
        return False
    if requests is None:
        logger.warning("requests is not installed; cannot forward protocol command to an existing instance")
        return False

    try:
        response = requests.post(INTERNAL_PROTOCOL_ENDPOINT, json=command, timeout=timeout)
        payload = _json_object(response)
        error = payload.get("error")
        if (response.status_code == 202 and payload.get("job_id")) or (
            response.status_code == 409
            and isinstance(error, dict)
            and error.get("code") == "busy"
        ):
            logger.info(
                "Forwarded protocol command to existing instance with response %s",
                response.status_code,
            )
            return True
        logger.warning(
            "Existing instance responded with unexpected status %s while forwarding protocol command",
            response.status_code,
        )
    except requests.RequestException as exc:
        logger.debug(f"Could not forward protocol command to existing instance: {exc}")
    return False
