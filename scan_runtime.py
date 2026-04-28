import json
import os
import sys
import time
import tkinter as tk

from gui.dialogs import init_gui
from scanner import ScanError, ScannerManager
from utils import get_logger

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


def run_scan_job(work_dir):
    root = None
    try:
        request = _read_request(work_dir)
        job_id = request.get("job_id") or "scan-job"
        timeout_seconds = int(request.get("scan_timeout_seconds") or 0)

        root = tk.Tk()
        root.withdraw()
        root.update()
        init_gui(root)
        logger.info("Scan child GUI initialized with window handle %s", root.winfo_id())

        scanner_manager = ScannerManager()
        deadline = None
        if timeout_seconds > 0:
            deadline = time.monotonic() + timeout_seconds

        def on_progress(status, **data):
            _write_state(work_dir, status, **data)

        _write_state(work_dir, "processing")
        pdf_buffer = scanner_manager.scan_to_pdf(
            job_id,
            progress_callback=on_progress,
            deadline=deadline,
        )
        _write_result(work_dir, pdf_buffer)
        pdf_buffer.close()
        _write_state(work_dir, "completed")
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
