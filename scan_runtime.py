import json
import os
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk

from gui.dialogs import init_gui
from scanner import ScanError, ScannerManager
from utils import SCAN_JOB_DIRECTORY_PREFIX, get_logger

REQUEST_FILE = "request.json"
STATE_FILE = "state.json"
RESULT_FILE = "result.pdf"

logger = get_logger()


def _atomic_write_json(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as temp_file:
        json.dump(payload, temp_file, indent=2)
    os.replace(temp_path, path)


def _read_request(work_dir):
    request_path = os.path.join(work_dir, REQUEST_FILE)
    with open(request_path, "r", encoding="utf-8") as request_file:
        return json.load(request_file)


def _write_state(work_dir, status, **extra):
    payload = {
        "status": status,
        "updated_at": time.time(),
    }
    payload.update(extra)
    _atomic_write_json(os.path.join(work_dir, STATE_FILE), payload)


def _write_result(work_dir, pdf_buffer):
    result_path = os.path.join(work_dir, RESULT_FILE)
    with open(result_path, "wb") as result_file:
        result_file.write(pdf_buffer.getvalue())


def _parent_alive_check(parent_pid):
    """A function telling whether ``parent_pid`` still runs, or None when it cannot be watched."""
    if not isinstance(parent_pid, int) or parent_pid <= 0 or parent_pid == os.getpid():
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            # Opened once, now: a handle keeps naming this process even if its id is reused.
            handle = kernel32.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE
        except Exception:
            return None
        if not handle:
            return lambda: False
        return lambda: kernel32.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0: ended

    direct_child = os.getppid() == parent_pid

    def alive():
        # A direct child is re-parented when its parent ends, even while the
        # parent is still an unreaped zombie.
        if direct_child and os.getppid() != parent_pid:
            return False
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    return alive


def watch_parent(parent_pid, on_gone, interval=1.0):
    """Call ``on_gone`` from a daemon thread once ``parent_pid`` has ended; returns the thread."""
    alive = _parent_alive_check(parent_pid)
    if alive is None:
        return None

    def loop():
        while alive():
            time.sleep(interval)
        on_gone()

    thread = threading.Thread(target=loop, daemon=True, name="ScanLinkParentWatch")
    thread.start()
    return thread


def _abandon(work_dir):
    # ScanLink itself is gone: nobody will collect this scan, so drop it and
    # end the process, which also releases the scanner.
    logger.warning("ScanLink ended during a scan; the scan child stops and removes %r", work_dir)
    shutil.rmtree(work_dir, ignore_errors=True)
    os._exit(4)


def is_job_directory(work_dir):
    """True only for a directory ScanWorker created with tempfile.mkdtemp()."""
    path = os.path.abspath(work_dir)
    return (
        os.path.basename(path).startswith(SCAN_JOB_DIRECTORY_PREFIX)
        and os.path.normcase(os.path.dirname(path))
        == os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        and os.path.isdir(path)
    )


def run_scan_job(work_dir):
    # A launcher that passes an unescaped scanlink:// URL could inject
    # --scan-worker-dir pointing at another folder or a remote share.
    if not is_job_directory(work_dir):
        logger.error("Refusing scan worker directory outside ScanLink's temp jobs: %r", work_dir)
        return 1
    root = None
    try:
        request = _read_request(work_dir)
        job_id = request.get("job_id") or "scan-job"
        timeout_seconds = int(request.get("scan_timeout_seconds") or 0)
        watch_parent(request.get("parent_pid"), lambda: _abandon(work_dir))

        root = tk.Tk()
        root.withdraw()
        root.update()
        init_gui(root)
        logger.info("Scan child GUI initialized with window handle %s", root.winfo_id())

        scanner_manager = ScannerManager()
        deadline = None
        if timeout_seconds > 0:
            deadline = time.monotonic() + timeout_seconds

        pages = {"count": 0}

        def on_progress(status, **data):
            if isinstance(data.get("page_count"), int):
                pages["count"] = data["page_count"]
            _write_state(work_dir, status, **data)

        _write_state(work_dir, "processing")
        pdf_buffer = scanner_manager.scan_to_pdf(
            job_id,
            progress_callback=on_progress,
            deadline=deadline,
        )
        _write_result(work_dir, pdf_buffer)
        pdf_buffer.close()
        _write_state(work_dir, "completed", page_count=pages["count"])
        return 0
    except ScanError as exc:
        _write_state(
            work_dir,
            exc.status,
            error={"code": exc.code, "message": exc.message},
        )
        logger.warning("Scan child failed with %s: %s", exc.code, exc.message)
        return 2
    except Exception as exc:
        _write_state(
            work_dir,
            "failed",
            error={"code": "scan_worker_crashed", "message": str(exc)},
        )
        logger.exception("Scan child crashed")
        return 3
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        return 1
    return run_scan_job(args[0])


if __name__ == "__main__":
    sys.exit(main())
