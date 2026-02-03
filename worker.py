import threading
import uuid
import queue
import time
import requests
from scanner import ScannerManager
from utils import get_logger

logger = get_logger()

# Status callback reference (set by server.py)
_status_callback = None

def set_status_callback(callback):
    """Set the callback function for emitting scan status updates."""
    global _status_callback
    _status_callback = callback

def emit_status(job_id, status, **kwargs):
    """Emit scan status via callback if available."""
    if _status_callback:
        try:
            _status_callback(job_id, status, **kwargs)
        except Exception as e:
            logger.warning(f"Status callback failed: {e}")

class ScanWorker(threading.Thread):
    def __init__(self, gui_task_queue):
        super().__init__(daemon=True)
        self.scan_queue = queue.Queue()
        self.gui_task_queue = gui_task_queue  # Queue to send tasks to Main Thread
        self.jobs = {}
        self.scanner_manager = ScannerManager()
        self.running = True
        self.current_job_id = None

    def submit_job(self, doc_id=None, callback_url=None):
        """
        Submit a new scan job.
        
        Args:
            doc_id: Optional document ID from Django
            callback_url: Optional URL to POST result when complete
        """
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {
            'status': 'queued',
            'submitted_at': time.time(),
            'doc_id': doc_id,
            'callback_url': callback_url,
            'page_count': 0
        }
        self.scan_queue.put(job_id)
        logger.info(f"Job {job_id} queued (doc_id={doc_id})")
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
            job = self.jobs[job_id]
            job['status'] = 'processing'
            logger.info(f"Processing job {job_id}")
            emit_status(job_id, 'processing', doc_id=job.get('doc_id'))

            try:
                # Progress callback for real-time updates
                def on_progress(event, **data):
                    if event == 'page_scanned':
                        job['page_count'] = data.get('page_count', 0)
                        emit_status(job_id, 'page_scanned', 
                                   page_count=job['page_count'],
                                   doc_id=job.get('doc_id'))
                    elif event == 'generating_pdf':
                        emit_status(job_id, 'generating_pdf',
                                   page_count=job['page_count'],
                                   doc_id=job.get('doc_id'))

                # Execute scan with progress callback
                pdf_buffer = self.scanner_manager.scan_to_pdf(
                    job_id, 
                    gui_executor=self._execute_gui,
                    progress_callback=on_progress
                )

                if pdf_buffer:
                    job['status'] = 'completed'
                    job['result'] = pdf_buffer
                    logger.info(f"Job {job_id} completed ({job['page_count']} pages)")
                    emit_status(job_id, 'completed', 
                               page_count=job['page_count'],
                               doc_id=job.get('doc_id'))
                    
                    # POST to callback URL if provided
                    self._send_callback(job_id, job)
                else:
                    job['status'] = 'failed'
                    job['error'] = "No pages scanned or cancelled"
                    logger.warning(f"Job {job_id} failed: No output")
                    emit_status(job_id, 'failed', 
                               error=job['error'],
                               doc_id=job.get('doc_id'))

            except Exception as e:
                job['status'] = 'failed'
                job['error'] = str(e)
                logger.error(f"Job {job_id} exception: {e}")
                emit_status(job_id, 'failed', 
                           error=str(e),
                           doc_id=job.get('doc_id'))
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

    def _send_callback(self, job_id, job):
        """POST the result to callback URL if provided."""
        callback_url = job.get('callback_url')
        if not callback_url:
            return
            
        try:
            pdf_buffer = job.get('result')
            if pdf_buffer:
                pdf_buffer.seek(0)
                files = {'pdf': (f'scan_{job_id}.pdf', pdf_buffer, 'application/pdf')}
                data = {
                    'job_id': job_id,
                    'doc_id': job.get('doc_id'),
                    'page_count': job.get('page_count', 0),
                    'status': 'completed'
                }
                response = requests.post(callback_url, files=files, data=data, timeout=30)
                if response.ok:
                    logger.info(f"Callback sent to {callback_url}")
                else:
                    logger.warning(f"Callback failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Callback error: {e}")

    def stop(self):
        self.running = False

    def is_busy(self):
        return self.current_job_id is not None
