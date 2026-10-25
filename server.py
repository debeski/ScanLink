import io
import socket
import ssl
import threading
import time

from flask import Flask, Response, jsonify, request, send_file
from werkzeug.serving import make_server

from utils import (
    APP_ARCH,
    APP_VERSION,
    HTTP_HOST,
    HTTP_PORT,
    HTTPS_PORT,
    get_logger,
    get_ssl_context,
    ensure_ssl_certificates,
    load_config,
)
from worker import BusyError

logger = get_logger()


def create_app(worker, shutdown_event, transport_state):
    app = Flask(__name__)
    config = load_config()
    allowed_origins = config.get("cors_origins", ["*"])

    def is_browser_endpoint(path):
        return path == "/health" or path == "/scan" or path.startswith("/scan/")

    def is_origin_allowed(origin):
        return "*" in allowed_origins or origin in allowed_origins

    def apply_cors(response):
        origin = request.headers.get("Origin")
        if not origin or not is_origin_allowed(origin):
            return response

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        response.headers["Vary"] = "Origin"
        return response

    def empty_options_response():
        return apply_cors(Response(status=204))

    def error_response(status_code, code, message, **extra):
        payload = {"error": {"code": code, "message": message}}
        payload["error"].update(extra)
        response = jsonify(payload)
        response.status_code = status_code
        return apply_cors(response)

    @app.after_request
    def add_cors_headers(response):
        if is_browser_endpoint(request.path):
            return apply_cors(response)
        return response

    @app.route("/health", methods=["GET", "OPTIONS"])
    def health():
        if request.method == "OPTIONS":
            return empty_options_response()

        return jsonify(
            {
                "status": "ok",
                "version": APP_VERSION,
                "arch": APP_ARCH,
                "busy": worker.is_busy(),
                "http_enabled": transport_state.get("http_enabled", False),
                "https_enabled": transport_state.get("https_enabled", False),
                "twain_available": worker.is_twain_available(),
                "https_setup": transport_state.get(
                    "https_setup",
                    "ready" if transport_state.get("https_enabled") else "unavailable",
                ),
            }
        )

    @app.route("/scan", methods=["POST", "OPTIONS"])
    def start_scan():
        if request.method == "OPTIONS":
            return empty_options_response()

        if not request.is_json:
            return error_response(
                415, "json_required", "Scan requests must use an application/json body."
            )

        data = request.get_json(silent=True)
        if data is None:
            return error_response(
                400, "invalid_json", "Request body could not be parsed as JSON."
            )

        metadata = data.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return error_response(
                400, "invalid_metadata", "metadata must be a JSON object when provided."
            )

        doc_id = data.get("doc_id") or data.get("docId")
        callback_url = data.get("callback_url") or data.get("callback")

        try:
            job = worker.submit_job(
                doc_id=doc_id,
                callback_url=callback_url,
                metadata=metadata,
                source="api",
            )
        except BusyError as exc:
            return error_response(
                409,
                "busy",
                "Another scan job is already queued or running.",
                active_job_id=exc.active_job_id,
            )

        return jsonify({"job_id": job["job_id"], "status": "queued"}), 202

    @app.route("/scan/<job_id>", methods=["GET", "OPTIONS"])
    def get_scan_status(job_id):
        if request.method == "OPTIONS":
            return empty_options_response()

        job = worker.get_job(job_id)
        if not job:
            return error_response(
                404, "job_not_found", "The requested scan job was not found."
            )
        return jsonify(job)

    @app.route("/scan/<job_id>/result", methods=["GET", "OPTIONS"])
    def get_scan_result(job_id):
        if request.method == "OPTIONS":
            return empty_options_response()

        job = worker.get_job(job_id)
        if not job:
            return error_response(
                404, "job_not_found", "The requested scan job was not found."
            )
        if job["status"] != "completed":
            return error_response(
                409,
                "result_not_ready",
                "The scan result is not ready yet.",
                current_status=job["status"],
            )

        updated_job, result_bytes = worker.consume_result(job_id)
        if not updated_job:
            return error_response(
                404, "job_not_found", "The requested scan job was not found."
            )
        if not result_bytes:
            return error_response(
                410,
                "result_unavailable",
                "The scan result is no longer available.",
            )

        return send_file(
            io.BytesIO(result_bytes),
            as_attachment=True,
            download_name=f"scan_{job_id}.pdf",
            mimetype="application/pdf",
        )

    @app.route("/internal/protocol/scan", methods=["POST"])
    def internal_protocol_scan():
        data = request.get_json(silent=True) or {}
        if data.get("action", "scan") != "scan":
            return (
                jsonify(
                    {
                        "error": {
                            "code": "unsupported_action",
                            "message": "Only scan actions are supported.",
                        }
                    }
                ),
                400,
            )

        try:
            job = worker.submit_job(
                doc_id=data.get("doc_id"),
                callback_url=data.get("callback_url"),
                metadata=data.get("metadata"),
                source="protocol",
            )
        except BusyError as exc:
            return (
                jsonify(
                    {
                        "error": {
                            "code": "busy",
                            "message": "Another scan job is already queued or running.",
                            "active_job_id": exc.active_job_id,
                        }
                    }
                ),
                409,
            )

        return jsonify({"job_id": job["job_id"], "status": "queued"}), 202

    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        shutdown_event.set()
        return jsonify({"message": "Shutting down..."})

    return app


def emit_scan_status(job_id, status, **kwargs):
    """
    Compatibility no-op. The robust integration uses REST polling.
    """
    return None


class LoopbackServer(threading.Thread):
    def __init__(self, app, host, port, ssl_context=None, label="HTTP"):
        super().__init__(daemon=True)
        self.app = app
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.label = label
        self.httpd = None
        self.started = threading.Event()
        self.error = None

    def _select_context(self, connection, server_name, initial_context):
        connection.context = self.ssl_context

    def run(self):
        try:
            if self.ssl_context is not None:
                self.ssl_context.sni_callback = self._select_context
            self.httpd = make_server(
                self.host,
                self.port,
                self.app,
                threaded=True,
                ssl_context=self.ssl_context,
            )
            logger.info("%s listener ready on %s:%s", self.label, self.host, self.port)
        except Exception as exc:
            self.error = exc
            logger.error(
                "Failed to start %s listener on %s:%s: %s",
                self.label,
                self.host,
                self.port,
                exc,
            )
            self.started.set()
            return

        self.started.set()

        try:
            self.httpd.serve_forever()
        except Exception as exc:
            self.error = exc
            logger.error("%s listener stopped unexpectedly: %s", self.label, exc)

    def shutdown(self):
        if self.httpd is not None:
            self.httpd.shutdown()


def run_server(worker, shutdown_event, https_retry_event=None, on_https_error=None):
    retry = https_retry_event or threading.Event()
    transport_state = {
        "http_enabled": False,
        "https_enabled": False,
        "https_setup": "preparing",
    }
    app = create_app(worker, shutdown_event, transport_state)
    listeners = []
    http_listener = LoopbackServer(app, HTTP_HOST, HTTP_PORT, label="HTTP")
    http_listener.start()
    http_listener.started.wait(timeout=5)
    if not http_listener.error and http_listener.started.is_set():
        transport_state["http_enabled"] = True
        listeners.append(http_listener)

    https_listener = None
    next_check = 0
    report_failure = True
    try:
        while not shutdown_event.is_set():
            if retry.is_set():
                retry.clear()
                next_check = 0
                report_failure = True
            if time.monotonic() >= next_check:
                try:
                    transport_state["https_setup"] = "preparing"
                    if not ensure_ssl_certificates(generate_if_missing=True):
                        raise RuntimeError("Certificate setup failed")
                    context = get_ssl_context()
                    if context is None:
                        raise RuntimeError("Certificate trust could not be verified")
                    if https_listener is None:
                        candidate = LoopbackServer(
                            app,
                            HTTP_HOST,
                            HTTPS_PORT,
                            ssl_context=context,
                            label="HTTPS",
                        )
                        candidate.start()
                        candidate.started.wait(timeout=5)
                        if candidate.error or not candidate.started.is_set():
                            raise RuntimeError("Secure connection could not be started")
                        https_listener = candidate
                        listeners.append(candidate)
                    else:
                        # New accepted connections use the renewed identity; active scans continue.
                        https_listener.ssl_context = context
                    with socket.create_connection(
                        (HTTP_HOST, HTTPS_PORT), timeout=3
                    ) as connection:
                        with ssl.create_default_context().wrap_socket(
                            connection, server_hostname="localhost"
                        ):
                            pass
                    transport_state.update(https_enabled=True, https_setup="ready")
                    next_check = time.monotonic() + 3600
                except Exception:
                    logger.exception("Automatic HTTPS setup failed")
                    transport_state["https_setup"] = "failed"
                    next_check = time.monotonic() + 3600
                    if report_failure and on_https_error:
                        on_https_error()
                report_failure = False
            if not listeners:
                shutdown_event.set()
            shutdown_event.wait(0.5)
    finally:
        for listener in listeners:
            listener.shutdown()
        for listener in listeners:
            listener.join(timeout=5)
