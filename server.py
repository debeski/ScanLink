from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading
from utils import load_config, get_logger, get_ssl_context, is_ssl_available

logger = get_logger()

# Global SocketIO instance (initialized in create_app)
socketio = None

def create_app(worker, shutdown_event):
    global socketio
    
    app = Flask(__name__)
    config = load_config()
    
    # Configure CORS
    origins = config.get('cors_origins', ["*"])
    CORS(app, resources={r"/scan/*": {"origins": origins}, r"/health": {"origins": origins}})
    
    # Initialize SocketIO with CORS
    socketio = SocketIO(app, cors_allowed_origins=origins, async_mode='threading')
    
    # Store worker reference for WebSocket handlers
    app.worker = worker

    # =========================================================================
    # REST API Endpoints (Backward Compatible)
    # =========================================================================
    
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            "status": "ok", 
            "scanner_busy": worker.is_busy(),
            "ssl_enabled": is_ssl_available()
        })

    @app.route('/scan', methods=['POST'])
    def start_scan():
        data = request.get_json(silent=True) or {}
        doc_id = data.get('doc_id')
        callback_url = data.get('callback_url')
        
        job_id = worker.submit_job(doc_id=doc_id, callback_url=callback_url)
        
        # Emit WebSocket event
        if socketio:
            socketio.emit('scan_status', {
                'job_id': job_id, 
                'status': 'queued',
                'doc_id': doc_id
            })
        
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
        if 'page_count' in job:
            response['page_count'] = job['page_count']
            
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

    # =========================================================================
    # WebSocket Events
    # =========================================================================
    
    @socketio.on('connect')
    def handle_connect():
        logger.info("WebSocket client connected")
        emit('connected', {'message': 'Connected to ScanLink'})

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info("WebSocket client disconnected")

    @socketio.on('start_scan')
    def handle_start_scan(data):
        """WebSocket-initiated scan request."""
        doc_id = data.get('doc_id') if data else None
        callback_url = data.get('callback_url') if data else None
        
        job_id = worker.submit_job(doc_id=doc_id, callback_url=callback_url)
        emit('scan_status', {
            'job_id': job_id, 
            'status': 'queued',
            'doc_id': doc_id
        })

    @socketio.on('get_status')
    def handle_get_status(data):
        """Get status of a specific job."""
        job_id = data.get('job_id') if data else None
        if not job_id:
            emit('error', {'message': 'job_id required'})
            return
            
        job = worker.get_job(job_id)
        if not job:
            emit('error', {'message': 'Job not found'})
            return
            
        emit('scan_status', {
            'job_id': job_id,
            'status': job['status'],
            'page_count': job.get('page_count', 0)
        })

    return app

def emit_scan_status(job_id, status, **kwargs):
    """Helper to emit scan status from worker thread."""
    global socketio
    if socketio:
        data = {'job_id': job_id, 'status': status}
        data.update(kwargs)
        socketio.emit('scan_status', data)

def run_server(worker, shutdown_event):
    app = create_app(worker, shutdown_event)
    
    # Check for SSL
    ssl_context = get_ssl_context()
    
    try:
        if ssl_context:
            # HTTPS mode
            logger.info("Starting server with HTTPS on port 5443")
            socketio.run(app, host="127.0.0.1", port=5443, 
                        ssl_context=(
                            app.config.get('SSL_CERT') or __import__('utils').SSL_CERT_FILE,
                            app.config.get('SSL_KEY') or __import__('utils').SSL_KEY_FILE
                        ),
                        debug=False, use_reloader=False)
        else:
            # HTTP fallback
            logger.info("Starting server with HTTP on port 5000 (no SSL certificates)")
            socketio.run(app, host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Server error: {e}")
