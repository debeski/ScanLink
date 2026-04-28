import argparse
import queue
import sys
import threading
import tkinter as tk

from gui.dialogs import init_gui
from protocol_handler import (
    extract_protocol_url_from_args,
    forward_protocol_command,
    is_existing_instance_running,
    parse_protocol_url,
)
from server import run_server
from tray import TrayApp
from utils import APP_VERSION, ensure_ssl_certificates, get_logger, is_ssl_available, setup_logging
from worker import ScanWorker, set_status_callback


def main():
    logger = setup_logging()
    logger.info("ScanLink v%s starting", APP_VERSION)

    parser = argparse.ArgumentParser(description="ScanLink - Scanner Bridge for Web Apps")
    parser.add_argument("url", nargs="?", help="Protocol URL (scanlink://...)")
    parser.add_argument(
        "--generate-ssl",
        action="store_true",
        help="Generate trusted localhost SSL certificates and exit",
    )
    args, unknown = parser.parse_known_args()

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

    if is_ssl_available():
        logger.info("Trusted localhost HTTPS certificates are available")
    else:
        logger.info("Trusted localhost HTTPS certificates not found; HTTP loopback listener will remain available")

    shutdown_event = threading.Event()
    gui_task_queue = queue.Queue()
    worker = ScanWorker(gui_task_queue)
    set_status_callback(None)

    tray = TrayApp(worker, shutdown_event)

    worker.start()

    server_thread = threading.Thread(
        target=run_server,
        args=(worker, shutdown_event),
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

    root = tk.Tk()
    root.withdraw()
    init_gui(root)

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
