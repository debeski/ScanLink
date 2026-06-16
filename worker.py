import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None

from scanner import ScanError, ScannerManager
from utils import get_logger, load_config

logger = get_logger()

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out"}

# Optional compatibility hook for future push-based status updates.
_status_callback = None


def set_status_callback(callback):
    global _status_callback
    _status_callback = callback


def emit_status(job_id, status, **kwargs):
    if _status_callback:
        try:
            _status_callback(job_id, status, **kwargs)
        except Exception as exc:
            logger.warning(f"Status callback failed: {exc}")


class BusyError(Exception):
    def __init__(self, active_job_id=None):
        super().__init__("Another scan job is already queued or running.")
        self.active_job_id = active_job_id


class GuiTaskTimeoutError(Exception):
    pass


class ScanProcessTimeoutError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class ScanWorker(threading.Thread):
    def __init__(self, gui_task_queue):
        super().__init__(daemon=True)
        self.scan_queue = queue.Queue()
        self.gui_task_queue = gui_task_queue
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.scanner_manager = ScannerManager()
        self.running = True
        self.current_job_id = None
        self.active_scan_process = None
        self.active_scan_process_lock = threading.Lock()

        config = load_config()
        self.job_ttl_seconds = int(config.get("job_ttl_seconds", 900))
        self.result_ttl_seconds = int(config.get("result_ttl_seconds", 300))
        self.scan_timeout_seconds = int(config.get("scan_timeout_seconds", 600))
        self.gui_task_timeout_seconds = int(config.get("gui_task_timeout_seconds", 900))
        self.scan_idle_timeout_seconds = int(config.get("scan_idle_timeout_seconds", 45))

    def submit_job(self, doc_id=None, callback_url=None, metadata=None, source="api"):
        with self.jobs_lock:
            self._cleanup_expired_jobs_locked()
            active_job_id = self._find_active_job_id_locked()
            if active_job_id:
                raise BusyError(active_job_id=active_job_id)

            job_id = str(uuid.uuid4())
            now = time.time()
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "submitted_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "doc_id": doc_id,
                "callback_url": callback_url,
                "metadata": metadata or {},
                "page_count": 0,
                "result_bytes": None,
                "result_retrieved_at": None,
                "source": source,
                "error": None,
            }

        self.scan_queue.put(job_id)
        logger.info("Job %s queued (source=%s, doc_id=%s)", job_id, source, doc_id)
        emit_status(job_id, "queued", doc_id=doc_id)
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self.jobs_lock:
            self._cleanup_expired_jobs_locked()
            job = self.jobs.get(job_id)
            return self._serialize_job(job) if job else None

    def consume_result(self, job_id):
        with self.jobs_lock:
            self._cleanup_expired_jobs_locked()
            job = self.jobs.get(job_id)
            if not job:
                return None, None

            result_bytes = job.get("result_bytes")
            if result_bytes:
                job["result_bytes"] = None
                job["result_retrieved_at"] = time.time()
                job["updated_at"] = time.time()

            return self._serialize_job(job), result_bytes

    def is_busy(self):
        with self.jobs_lock:
            return self._find_active_job_id_locked() is not None

    def is_twain_available(self):
        return self.scanner_manager.is_available()

    def run(self):
        logger.info("ScanWorker started")
        while self.running:
            try:
                job_id = self.scan_queue.get(timeout=0.5)
            except queue.Empty:
                self._cleanup_expired_jobs()
                continue

            if job_id is None:
                self.scan_queue.task_done()
                break

            try:
                self._process_job(job_id)
            finally:
                self.scan_queue.task_done()
                self._cleanup_expired_jobs()

        logger.info("ScanWorker stopped")

    def stop(self):
        self.running = False
        self._stop_active_scan_process()
        self.scan_queue.put(None)

    def _process_job(self, job_id):
        if not self._update_job(job_id, status="processing", started_at=time.time()):
            return

        self.current_job_id = job_id
        logger.info("Processing job %s", job_id)
        emit_status(job_id, "processing")

        scan_deadline = None
        if self.scan_timeout_seconds > 0:
            scan_deadline = time.monotonic() + self.scan_timeout_seconds

        try:
            def on_progress(status, **data):
                updates = {"status": status, "updated_at": time.time()}
                if "page_count" in data:
                    updates["page_count"] = data["page_count"]
                self._update_job(job_id, **updates)
                emit_status(job_id, status, **data)

            pdf_buffer = self._run_scan_subprocess(job_id, on_progress)
            pdf_bytes = pdf_buffer.getvalue()
            pdf_buffer.close()

            job_snapshot = self._update_job(
                job_id,
                status="completed",
                completed_at=time.time(),
                updated_at=time.time(),
                result_bytes=pdf_bytes,
                error=None,
            )
            logger.info("Job %s completed with %s pages", job_id, job_snapshot.get("page_count", 0))
            emit_status(job_id, "completed", page_count=job_snapshot.get("page_count", 0))
            self._send_callback(job_snapshot, pdf_bytes)
        except GuiTaskTimeoutError:
            self._fail_job(
                job_id,
                code="scan_timeout",
                message="The scan helper did not finish within the allowed time.",
                status="timed_out",
            )
        except ScanProcessTimeoutError as exc:
            self._fail_job(
                job_id,
                code=exc.code,
                message=exc.message,
                status="timed_out" if exc.code.endswith("timeout") else "failed",
            )
        except ScanError as exc:
            self._fail_job(job_id, code=exc.code, message=exc.message, status=exc.status)
        except Exception as exc:
            self._fail_job(
                job_id,
                code="unexpected_error",
                message=str(exc),
                status="failed",
            )
        finally:
            self.current_job_id = None

    def _fail_job(self, job_id, code, message, status="failed"):
        job = self._update_job(
            job_id,
            status=status,
            completed_at=time.time(),
            updated_at=time.time(),
            error={"code": code, "message": message},
            result_bytes=None,
        )
        logger.warning("Job %s ended with status=%s code=%s message=%s", job_id, status, code, message)
        emit_status(job_id, status, error=job.get("error"))

    def _execute_gui(self, func, timeout=None):
        result_queue = queue.Queue(maxsize=1)
        self.gui_task_queue.put((func, result_queue))

        try:
            outcome, payload = result_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise GuiTaskTimeoutError() from exc

        if outcome == "error":
            raise payload
        return payload

    def run_gui_task(self, func, timeout=30):
        return self._execute_gui(func, timeout=timeout)

    def _run_scan_subprocess(self, job_id, on_progress):
        work_dir = tempfile.mkdtemp(prefix="scanlink-job-")
        state_path = os.path.join(work_dir, "state.json")
        result_path = os.path.join(work_dir, "result.pdf")
        request_path = os.path.join(work_dir, "request.json")
        started_at = time.monotonic()
        last_progress_at = started_at
        last_state_signature = None
        last_state_status = None

        request_payload = {
            "job_id": job_id,
            "scan_timeout_seconds": self.scan_timeout_seconds,
        }
        with open(request_path, "w", encoding="utf-8") as request_file:
            json.dump(request_payload, request_file, indent=2)

        process = None
        try:
            process = subprocess.Popen(
                self._build_scan_subprocess_command(work_dir),
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            with self.active_scan_process_lock:
                self.active_scan_process = process

            while True:
                state = self._read_state_file(state_path)
                if state:
                    signature = json.dumps(
                        [
                            state.get("status"),
                            state.get("page_count", 0),
                            (state.get("error") or {}).get("code"),
                        ],
                        sort_keys=True,
                    )
                    if signature != last_state_signature:
                        last_state_signature = signature
                        last_progress_at = time.monotonic()
                        last_state_status = state.get("status")
                        progress_payload = {}
                        if "page_count" in state:
                            progress_payload["page_count"] = state["page_count"]
                        if "error" in state:
                            progress_payload["error"] = state["error"]
                        on_progress(state["status"], **progress_payload)

                return_code = process.poll()
                if return_code is not None:
                    break

                now = time.monotonic()
                if self.gui_task_timeout_seconds > 0 and now - started_at > self.gui_task_timeout_seconds:
                    self._terminate_scan_process(process)
                    raise ScanProcessTimeoutError(
                        "scan_timeout",
                        "The scan helper did not finish within the allowed time.",
                    )
                if (
                    self.scan_idle_timeout_seconds > 0
                    and last_state_status in {"acquiring", "page_scanned"}
                    and now - last_progress_at > self.scan_idle_timeout_seconds
                ):
                    self._terminate_scan_process(process)
                    raise ScanProcessTimeoutError(
                        "scan_idle_timeout",
                        "The scanner did not make progress and was reset.",
                    )

                time.sleep(0.25)

            final_state = self._read_state_file(state_path)
            if process.returncode == 0 and os.path.exists(result_path):
                with open(result_path, "rb") as result_file:
                    return io.BytesIO(result_file.read())

            if final_state and final_state.get("error"):
                error = final_state["error"]
                raise ScanError(
                    error.get("code", "scan_failed"),
                    error.get("message", "The scan could not be completed."),
                    status=final_state.get("status", "failed"),
                )

            raise ScanError(
                "scan_worker_crashed",
                f"Scan worker exited unexpectedly with code {process.returncode}.",
            )
        finally:
            with self.active_scan_process_lock:
                if self.active_scan_process is process:
                    self.active_scan_process = None
            if process and process.poll() is None:
                self._terminate_scan_process(process)
            shutil.rmtree(work_dir, ignore_errors=True)

    def _build_scan_subprocess_command(self, work_dir):
        if getattr(sys, "frozen", False):
            return [sys.executable, "--scan-worker-dir", work_dir]
        return [sys.executable, os.path.abspath("main.py"), "--scan-worker-dir", work_dir]

    def _read_state_file(self, state_path):
        if not os.path.exists(state_path):
            return None
        try:
            with open(state_path, "r", encoding="utf-8") as state_file:
                return json.load(state_file)
        except (json.JSONDecodeError, OSError):
            return None

    def _terminate_scan_process(self, process):
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass

    def _stop_active_scan_process(self):
        with self.active_scan_process_lock:
            process = self.active_scan_process
        if process and process.poll() is None:
            logger.warning("Stopping active scan subprocess during worker shutdown")
            self._terminate_scan_process(process)

    def _send_callback(self, job, pdf_bytes):
        callback_url = job.get("callback_url")
        if not callback_url:
            return
        if requests is None:
            logger.warning("requests is not installed; skipping callback delivery for job %s", job["job_id"])
            return

        parsed = urlparse(callback_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            logger.warning("Skipping callback for job %s because callback_url is not absolute: %s", job["job_id"], callback_url)
            return

        try:
            files = {
                "pdf": (
                    f"scan_{job['job_id']}.pdf",
                    pdf_bytes,
                    "application/pdf",
                )
            }
            data = {
                "job_id": job["job_id"],
                "doc_id": job.get("doc_id"),
                "page_count": job.get("page_count", 0),
                "status": "completed",
            }
            response = requests.post(callback_url, files=files, data=data, timeout=30)
            if response.ok:
                logger.info("Callback sent to %s for job %s", callback_url, job["job_id"])
            else:
                logger.warning(
                    "Callback for job %s failed with status %s",
                    job["job_id"],
                    response.status_code,
                )
        except Exception as exc:
            logger.error(f"Callback error for job {job['job_id']}: {exc}")

    def _find_active_job_id_locked(self):
        if self.current_job_id:
            return self.current_job_id

        for job_id, job in self.jobs.items():
            if job.get("status") not in TERMINAL_STATUSES:
                return job_id
        return None

    def _update_job(self, job_id, **updates):
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            job.update(updates)
            job["updated_at"] = updates.get("updated_at", time.time())
            return self._serialize_job(job)

    def _serialize_job(self, job):
        if not job:
            return None

        response = {
            "job_id": job["job_id"],
            "status": job["status"],
            "submitted_at": job.get("submitted_at"),
            "updated_at": job.get("updated_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "doc_id": job.get("doc_id"),
            "page_count": job.get("page_count", 0),
        }
        if job.get("metadata"):
            response["metadata"] = job["metadata"]
        if job.get("error"):
            response["error"] = dict(job["error"])
        return response

    def _cleanup_expired_jobs(self):
        with self.jobs_lock:
            self._cleanup_expired_jobs_locked()

    def _cleanup_expired_jobs_locked(self):
        now = time.time()
        expired_job_ids = []

        for job_id, job in self.jobs.items():
            status = job.get("status")
            if status not in TERMINAL_STATUSES:
                continue

            completed_at = job.get("completed_at") or job.get("updated_at") or now
            age_seconds = now - completed_at
            result_missing = job.get("result_bytes") is None
            result_retrieved_at = job.get("result_retrieved_at")

            if result_missing and result_retrieved_at:
                expired_job_ids.append(job_id)
                continue

            ttl_seconds = self.job_ttl_seconds
            if status == "completed" and job.get("result_bytes") is not None:
                ttl_seconds = self.result_ttl_seconds

            if age_seconds >= ttl_seconds:
                expired_job_ids.append(job_id)

        for job_id in expired_job_ids:
            logger.info("Cleaning up expired job %s", job_id)
            self.jobs.pop(job_id, None)
