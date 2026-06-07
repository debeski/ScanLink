# ScanLink API Reference

ScanLink exposes a browser-friendly local API for starting scans, polling status, and downloading the scanned PDF.

## Base URLs

| Transport | URL | Notes |
| --- | --- | --- |
| HTTP | `http://127.0.0.1:5000` | Always attempted by the app. |
| HTTPS | `https://127.0.0.1:5443` | Enabled only when trusted localhost certificates exist. |

The JavaScript helper also defaults to `http://localhost:5000` and `https://localhost:5443`. The server binds to `127.0.0.1`.

## Error Shape

Errors use this shape:

```json
{
  "error": {
    "code": "busy",
    "message": "Another scan job is already queued or running."
  }
}
```

Some errors include extra fields such as `active_job_id` or `current_status`.

## GET /health

Checks whether ScanLink is running and what transports are enabled.

Response:

```json
{
  "status": "ok",
  "version": "0.7.1",
  "busy": false,
  "http_enabled": true,
  "https_enabled": false,
  "twain_available": true
}
```

## POST /scan

Starts a scan job.

Request headers:

```http
Content-Type: application/json
```

Request body:

```json
{
  "doc_id": "DOC-123",
  "callback_url": "https://example.com/scan-callback",
  "metadata": {
    "module": "invoices"
  }
}
```

Accepted aliases:

- `doc_id` or `docId`
- `callback_url` or `callback`

Response `202`:

```json
{
  "job_id": "db8ffb4d-8f76-4b85-b04e-9626c41e5d7d",
  "status": "queued"
}
```

Errors:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `invalid_json` | Body could not be parsed as JSON. |
| 400 | `invalid_metadata` | `metadata` was provided but is not an object. |
| 409 | `busy` | Another scan job is queued or running. |
| 415 | `json_required` | Request did not use JSON. |

Busy response:

```json
{
  "error": {
    "code": "busy",
    "message": "Another scan job is already queued or running.",
    "active_job_id": "db8ffb4d-8f76-4b85-b04e-9626c41e5d7d"
  }
}
```

## GET /scan/<job_id>

Returns job status.

Response:

```json
{
  "job_id": "db8ffb4d-8f76-4b85-b04e-9626c41e5d7d",
  "status": "page_scanned",
  "submitted_at": 1760000000.0,
  "updated_at": 1760000005.0,
  "started_at": 1760000001.0,
  "completed_at": null,
  "doc_id": "DOC-123",
  "page_count": 2,
  "metadata": {
    "module": "invoices"
  }
}
```

Terminal failure response:

```json
{
  "job_id": "db8ffb4d-8f76-4b85-b04e-9626c41e5d7d",
  "status": "failed",
  "page_count": 0,
  "error": {
    "code": "twain_unavailable",
    "message": "TWAIN support is not available on this computer."
  }
}
```

Errors:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 404 | `job_not_found` | Job does not exist or expired. |

## GET /scan/<job_id>/result

Downloads the scanned PDF for a completed job.

Response:

- `200 OK`
- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename=scan_<job_id>.pdf`

Errors:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 404 | `job_not_found` | Job does not exist or expired. |
| 409 | `result_not_ready` | Job is not completed yet. |
| 410 | `result_unavailable` | Result was already consumed or expired. |

## POST /internal/protocol/scan

Internal endpoint used by `scanlink://` launches to forward commands into an already-running ScanLink instance. Application integrations should normally use `POST /scan`.

## POST /shutdown

Requests ScanLink shutdown. This is intended for local control, not browser integrations.

## Scan Error Codes

Errors from the scanner/runtime layer can appear inside the job `error` object:

| Code | Meaning |
| --- | --- |
| `twain_unavailable` | `pytwain` or TWAIN support is unavailable. |
| `scanner_selection_cancelled` | User cancelled scanner selection. |
| `open_source_failed` | Selected scanner could not be opened. |
| `acquire_timeout` | Scanner acquisition exceeded the scan deadline. |
| `acquire_failed` | Scanner acquisition failed. |
| `no_pages_scanned` | Scan ended without captured pages. |
| `image_runtime_unavailable` | Pillow is unavailable. |
| `pdf_runtime_unavailable` | ReportLab is unavailable. |
| `pdf_generation_failed` | PDF creation failed. |
| `scan_failed` | Generic scan failure from the child process. |
| `scan_timeout` | Scan helper exceeded the configured timeout. |
| `scan_idle_timeout` | Scanner stopped making progress. |
| `scan_worker_crashed` | Child scan process exited unexpectedly. |
| `unexpected_error` | Unhandled worker exception. |

## CORS

Browser endpoints support CORS for:

- `/health`
- `/scan`
- `/scan/<job_id>`
- `/scan/<job_id>/result`

Allowed origins come from `%LOCALAPPDATA%\ScanLink\config.json`:

```json
{
  "cors_origins": ["*"]
}
```

When `cors_origins` is not `["*"]`, the request `Origin` must exactly match an entry in the list.
