import argparse
import multiprocessing
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from gui.dialogs import init_gui
from protocol_handler import (
    extract_protocol_url_from_args,
    forward_protocol_command,
    is_existing_instance_running,
    parse_protocol_url,
)
from scan_runtime import run_scan_job
from server import run_server
from tray import TrayApp
from utils import APP_VERSION, ensure_ssl_certificates, get_logger, setup_logging
from worker import ScanWorker, set_status_callback


def main():
    multiprocessing.freeze_support()
    logger = setup_logging()
    logger.info("ScanLink v%s starting", APP_VERSION)

    parser = argparse.ArgumentParser(
        description="ScanLink - Scanner Bridge for Web Apps"
    )
    parser.add_argument("url", nargs="?", help="Protocol URL (scanlink://...)")
    parser.add_argument("--scan-worker-dir", help=argparse.SUPPRESS)
    parser.add_argument(
        "--generate-ssl",
        action="store_true",
        help="Generate trusted localhost SSL certificates and exit",
    )
    args, unknown = parser.parse_known_args()

    if args.scan_worker_dir:
        return run_scan_job(args.scan_worker_dir)

    if args.generate_ssl:
        logger.info("Generating SSL certificates...")
        if ensure_ssl_certificates(generate_if_missing=True):
            logger.info("SSL certificates generated successfully")
            return 0
        logger.error("Failed to generate SSL certificates")
        return 1

    protocol_url = args.url or extract_protocol_url_from_args(unknown)
    protocol_command = parse_protocol_url(protocol_url) if protocol_url else None
    if protocol_command:
        logger.info("Launched via protocol: %s", protocol_command)

    if protocol_command and forward_protocol_command(protocol_command):
        logger.info("Protocol request forwarded to the already-running instance")
        return 0

    if is_existing_instance_running():
        logger.info("Another ScanLink instance is already running. Exiting.")
        return 0

    root = tk.Tk()
    root.withdraw()
    root.update()
    init_gui(root)
    logger.info("GUI root initialized with window handle %s", root.winfo_id())

    shutdown_event = threading.Event()
    gui_task_queue = queue.Queue()
    https_retry_event = threading.Event()
    worker = ScanWorker(gui_task_queue)

    def offer_https_retry():
        def show_setup_message():
            if messagebox.askretrycancel(
                "ScanLink connection setup",
                "ScanLink could not finish setting up its secure connection. "
                "Approve any Windows security prompt, then choose Retry. "
                "If your organization manages this computer, ask your support team for help.",
                parent=root,
            ):
                https_retry_event.set()

        gui_task_queue.put((show_setup_message, queue.Queue()))

    set_status_callback(None)

    tray = TrayApp(worker, shutdown_event, https_retry_event)

    worker.start()

    server_thread = threading.Thread(
        target=run_server,
        args=(worker, shutdown_event, https_retry_event, offer_https_retry),
        daemon=True,
        name="LoopbackServerManager",
    )
    server_thread.start()

    tray_thread = threading.Thread(
        target=tray.start,
        daemon=True,
        name="TrayThread",
    )
    tray_thread.start()

    if protocol_command and protocol_command.get("action") == "scan":

        def queue_protocol_scan():
            try:
                worker.submit_job(
                    doc_id=protocol_command.get("doc_id"),
                    callback_url=protocol_command.get("callback_url"),
                    source="protocol",
                )
                logger.info("Protocol-triggered scan queued locally")
            except Exception as exc:
                logger.error(f"Failed to queue protocol-triggered scan: {exc}")

        root.after(500, queue_protocol_scan)

    def process_gui_tasks():
        if shutdown_event.is_set():
            logger.info("Shutdown signal received")
            worker.stop()
            tray.stop()
            root.quit()
            return

        try:
            while True:
                func, result_queue = gui_task_queue.get_nowait()
                try:
                    result = func()
                    result_queue.put(("ok", result))
                except Exception as exc:
                    logger.exception("GUI task failed")
                    result_queue.put(("error", exc))
                finally:
                    gui_task_queue.task_done()
        except queue.Empty:
            pass

        root.after(100, process_gui_tasks)

    root.after(100, process_gui_tasks)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        shutdown_event.set()
        worker.stop()
        tray.stop()
        server_thread.join(timeout=5)
        worker.join(timeout=5)
        logger.info("Application stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
