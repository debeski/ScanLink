import threading
import queue # queue module
import tkinter as tk
import time
import sys
import os

# Import modules
from utils import setup_logging, get_logger
from worker import ScanWorker
from server import run_server
from tray import TrayApp
from gui.dialogs import init_gui

def main():
    # 1. Setup Logging
    logger = setup_logging()
    logger.info("ScanLink Refactored Starting...")

    # 2. Shared Objects
    shutdown_event = threading.Event()
    gui_task_queue = queue.Queue()

    # 3. Initialize Worker
    # Worker needs gui_task_queue to request UI actions
    worker = ScanWorker(gui_task_queue)
    
    # 4. Initialize Tray
    tray = TrayApp(worker, shutdown_event)
    
    # 5. Threads
    # Start Worker
    worker.start()
    
    # Start Flask Server
    flask_thread = threading.Thread(
        target=run_server,
        args=(worker, shutdown_event),
        daemon=True
    )
    flask_thread.start()
    
    # Start Tray
    # Tray.run blocks? No, pystray icon.run() blocks.
    # We run it in a thread.
    tray_thread = threading.Thread(
        target=tray.start,
        daemon=True
    )
    tray_thread.start()

    # 6. Main Thread Loop (Tkinter)
    root = tk.Tk()
    root.withdraw() # Hide the root window
    
    # Initialize GUI helper with root
    init_gui(root)

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
