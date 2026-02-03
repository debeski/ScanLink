import threading
import queue  # queue module
import tkinter as tk
import time
import sys
import os
import argparse

# Import modules
from utils import setup_logging, get_logger, ensure_ssl_certificates
from worker import ScanWorker, set_status_callback
from server import run_server, emit_scan_status
from tray import TrayApp
from gui.dialogs import init_gui
from protocol_handler import parse_protocol_url, extract_protocol_url_from_args

def main():
    # 1. Setup Logging
    logger = setup_logging()
    logger.info("ScanLink v0.4.0 Starting...")

    # 2. Parse Command Line Arguments
    parser = argparse.ArgumentParser(description='ScanLink - Scanner Bridge for Web Apps')
    parser.add_argument('url', nargs='?', help='Protocol URL (scanlink://...)')
    parser.add_argument('--generate-ssl', action='store_true', help='Generate SSL certificates and exit')
    args, unknown = parser.parse_known_args()
    
    # Check for protocol URL in arguments (Windows passes it as first arg)
    protocol_url = args.url or extract_protocol_url_from_args(unknown)
    protocol_command = None
    if protocol_url:
        protocol_command = parse_protocol_url(protocol_url)
        logger.info(f"Launched via protocol: {protocol_command}")

    # 3. Handle --generate-ssl flag
    if args.generate_ssl:
        logger.info("Generating SSL certificates...")
        if ensure_ssl_certificates():
            logger.info("SSL certificates generated successfully")
            sys.exit(0)
        else:
            logger.error("Failed to generate SSL certificates")
            sys.exit(1)

    # 4. Ensure SSL certificates exist (generate on first run)
    ssl_ready = ensure_ssl_certificates()
    if ssl_ready:
        logger.info("SSL certificates ready")
    else:
        logger.warning("SSL not available, will use HTTP")

    # 5. Shared Objects
    shutdown_event = threading.Event()
    gui_task_queue = queue.Queue()

    # 6. Initialize Worker
    worker = ScanWorker(gui_task_queue)
    
    # Set status callback for WebSocket emissions
    set_status_callback(emit_scan_status)
    
    # 7. Initialize Tray
    tray = TrayApp(worker, shutdown_event)
    
    # 8. Threads
    # Start Worker
    worker.start()
    
    # Start Server (Flask-SocketIO)
    server_thread = threading.Thread(
        target=run_server,
        args=(worker, shutdown_event),
        daemon=True
    )
    server_thread.start()
    
    # Start Tray
    tray_thread = threading.Thread(
        target=tray.start,
        daemon=True
    )
    tray_thread.start()

    # 9. Main Thread Loop (Tkinter)
    root = tk.Tk()
    root.withdraw()  # Hide the root window
    
    # Initialize GUI helper with root
    init_gui(root)

    # 10. Handle Protocol Command (if launched via scanlink://)
    if protocol_command and protocol_command.get('action') == 'scan':
        # Queue a scan job after a short delay to let everything initialize
        def trigger_protocol_scan():
            time.sleep(1)  # Wait for server to start
            worker.submit_job(
                doc_id=protocol_command.get('doc_id'),
                callback_url=protocol_command.get('callback_url')
            )
            logger.info("Protocol-triggered scan queued")
        
        protocol_thread = threading.Thread(target=trigger_protocol_scan, daemon=True)
        protocol_thread.start()

    def process_gui_tasks():
        # Check for shutdown
        if shutdown_event.is_set():
            logger.info("Shutdown signal received. stopping...")
            worker.stop()
            tray.stop()
            root.quit()
            return

        # Process GUI tasks
        try:
            while True:
                # Non-blocking get
                task = gui_task_queue.get_nowait()
                func, result_queue = task
                try:
                    res = func()
                    result_queue.put(res)
                except Exception as e:
                    logger.error(f"GUI Task Failed: {e}")
                    result_queue.put(None)
                finally:
                    gui_task_queue.task_done()
        except queue.Empty:
            pass
        
        # Schedule next check
        root.after(100, process_gui_tasks)

    # Start polling
    root.after(100, process_gui_tasks)
    
    # Run Mainloop
    try:
        root.mainloop()
    except KeyboardInterrupt:
        shutdown_event.set()

    # Cleanup
    logger.info("Application Stopped.")
    sys.exit(0)

if __name__ == '__main__':
    main()
