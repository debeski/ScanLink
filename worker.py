import threading
import uuid
import queue
import time
from scanner import ScannerManager
from utils import get_logger

logger = get_logger()

class ScanWorker(threading.Thread):
    def __init__(self, gui_task_queue):
        super().__init__(daemon=True)
        self.scan_queue = queue.Queue()
        self.gui_task_queue = gui_task_queue # Queue to send tasks to Main Thread
        self.jobs = {}
        self.scanner_manager = ScannerManager()
        self.running = True
        self.current_job_id = None

    def submit_job(self):
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {
            'status': 'queued',
            'submitted_at': time.time()
        }
        self.scan_queue.put(job_id)
        return job_id

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def run(self):
        logger.info("ScanWorker started")
        while self.running:
            try:
                # Timeout allows checking self.running
                job_id = self.scan_queue.get(timeout=1)
            except queue.Empty:
                continue

            self.current_job_id = job_id
            self.jobs[job_id]['status'] = 'processing'
            logger.info(f"Processing job {job_id}")

            try:
                # Execute scan
                # We pass _execute_gui as the executor for UI tasks
                pdf_buffer = self.scanner_manager.scan_to_pdf(
                    job_id, 
                    gui_executor=self._execute_gui
                )

                if pdf_buffer:
                    self.jobs[job_id]['status'] = 'completed'
                    self.jobs[job_id]['result'] = pdf_buffer
                    logger.info(f"Job {job_id} completed successfully")
                else:
                    self.jobs[job_id]['status'] = 'failed'
                    self.jobs[job_id]['error'] = "No pages scanned or cancelled"
                    logger.warning(f"Job {job_id} failed: No output")

            except Exception as e:
                self.jobs[job_id]['status'] = 'failed'
                self.jobs[job_id]['error'] = str(e)
                logger.error(f"Job {job_id} exception: {e}")
            finally:
                self.current_job_id = None
                self.scan_queue.task_done()

    def _execute_gui(self, func):
        """
        Helper to execute a function on the Main Thread and wait for result.
        """
        result_queue = queue.Queue()
        # Put task in main queue: (function, result_queue)
        self.gui_task_queue.put((func, result_queue))
        
        # Wait for result
        result = result_queue.get()
        return result

    def stop(self):
        self.running = False

    def is_busy(self):
        return self.current_job_id is not None
