from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
import threading
from utils import load_config, get_logger

logger = get_logger()

def create_app(worker, shutdown_event):
    app = Flask(__name__)
    config = load_config()
    
    # Configure CORS
    origins = config.get('cors_origins', ["*"])
    CORS(app, resources={r"/scan/*": {"origins": origins}})

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            "status": "ok", 
            "scanner_busy": worker.is_busy()
        })

    @app.route('/scan', methods=['POST'])
    def start_scan():
        if worker.is_busy():
            # Optional: Reject if busy, or just queue it. 
            # Queue is better, but TWAIN is single-device.
            # If queue is long, user might wait.
            # We'll allow queueing.
            pass
        
        job_id = worker.submit_job()
        return jsonify({"job_id": job_id, "status": "queued"}), 202

    @app.route('/scan/<job_id>', methods=['GET'])
    def get_scan_status(job_id):
        job = worker.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        
        response = {
            "job_id": job_id,
            "status": job['status'],
            "submitted_at": job['submitted_at']
        }
        if 'error' in job:
            response['error'] = job['error']
            
        return jsonify(response)

    @app.route('/scan/<job_id>/result', methods=['GET'])
    def get_scan_result(job_id):
        job = worker.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
            
        if job['status'] != 'completed' or 'result' not in job:
            return jsonify({"error": "Job not completed or failed"}), 400
            
        # Result is BytesIO
        buffer = job['result']
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'scan_{job_id}.pdf',
            mimetype='application/pdf'
        )

    @app.route('/shutdown', methods=['POST'])
    def shutdown():
        shutdown_event.set()
        return jsonify({"message": "Shutting down..."})

    return app

def run_server(worker, shutdown_event):
    app = create_app(worker, shutdown_event)
    try:
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Server error: {e}")
