# ScanLink API Reference

ScanLink exposes a browser-friendly local API for starting scans, polling status, and downloading the scanned PDF.

## Base URLs

| Transport | URL | Notes |
| --- | --- | --- |
| HTTP | `http://127.0.0.1:5000` | Always attempted by the app. |
| HTTPS | `https://127.0.0.1:5443` | Enabled only when trusted localhost certificates exist. |

The JavaScript helper also defaults to `http://localhost:5000` and `https://localhost:5443`. The server binds to `127.0.0.1`.

Every request must address the helper as `localhost`, `127.0.0.1` or `[::1]` in its `Host` header (any port). Other host names, such as a DNS name rebound to `127.0.0.1`, receive `403 invalid_host`.

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

Some errors include extra fields such as `active_job_id` or `current_status`. Protocol-level errors (unknown route `404`, wrong method `405`, oversized body `413`, internal error `500`) use the same shape, with CORS headers on browser endpoints.

Request bodies are limited to 64 KB.

## GET /health

Checks whether ScanLink is running and what transports are enabled.

Response:

```json
{
  "status": "ok",
  "version": "0.7.2",
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
| 400 | `invalid_payload` | JSON root was not an object. |
| 400 | `invalid_callback` | Callback URL was not a string or could not be parsed. |
| 400 | `invalid_metadata` | `metadata` was provided but is not an object. |
| 409 | `busy` | Another scan job is queued or running. |
| 413 | `payload_too_large` | Request body exceeded 64 KB. |
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

`active_job_id` is included only when the request comes from the same `Origin` that started the active job (or, for jobs started without an `Origin`, from a local tool that sends none).

## GET /scan/<job_id>

Returns job status.

A job belongs to the `Origin` that started it. Status and result requests from any other `Origin`, or without an `Origin` for a browser-started job, receive `404 job_not_found`, so one website cannot follow or download another website's scan.

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

Downloads the scanned PDF for a completed job. `completed` is published only after the child has exited and the parent has stored the PDF. Concurrent downloads are single-use: exactly one receives the bytes; later requests return `410` until the job metadata expires. PDF bytes are freed immediately after retrieval, while metadata remains until `job_ttl_seconds` from completion.

Response:

- `200 OK`
- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename=scan_<job_id>.pdf`

Errors:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 404 | `job_not_found` | Job does not exist or expired. |
| 409 | `result_not_ready` | Job is not completed yet. |
| 410 | `result_unavailable` | Result was already consumed. |

## POST /internal/protocol/scan

Requires an `application/json` object and applies the same metadata/callback validation as `/scan`; malformed requests never queue a scan. The optional `action` must be `scan`.

Internal endpoint used by `scanlink://` launches to forward commands into an already-running ScanLink instance. Application integrations should normally use `POST /scan`.

## POST /shutdown

Requests ScanLink shutdown. This is intended for local control, not browser integrations.

`/shutdown` and `/internal/protocol/scan` refuse browser requests: any request carrying an `Origin` or `Sec-Fetch-Site` header receives `403 local_only`. Local tools such as the protocol forwarder, PowerShell or `curl` send neither header.

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

Preflights that carry `Access-Control-Request-Private-Network: true` from an allowed origin are answered with `Access-Control-Allow-Private-Network: true`, as Chromium's Private Network Access requires for a public website calling the loopback helper.

When `cors_origins` is not `["*"]`, the request `Origin` must exactly match an entry in the list. Browser-endpoint requests from any other `Origin`, including preflights, receive `403 origin_not_allowed` before any work is done.

With the default `["*"]`, every website the operator opens can call `/health` and `/scan` and download the scans it starts itself. Job ownership keeps each website away from scans started by others. List the DjangoLux origins in `cors_origins` to restrict which websites can scan.

## Automatic HTTPS setup status (0.7.5b1)

`GET /health` adds `https_setup`: `preparing` while background certificate setup
runs, `ready` after trusted HTTPS starts, and `failed` after a setup/listener
failure. Existing `http_enabled` and `https_enabled` remain listener flags.
Older clients may ignore the new field; newer clients must tolerate its absence
on older helpers. Existing HTTP scan jobs remain usable while setup runs.

## Browser transport retries

The bundled JavaScript client re-negotiates a healthy transport through `/health`
before every scan, so a lost transport is reported as `helper_unavailable` or
`insecure_origin` and a stale preferred transport falls back before the POST.
A scan POST is sent once on that transport. If the response or its body is lost,
it rejects with `scan_request_uncertain` instead of resending the request over
the other transport; the helper may already be scanning. Check ScanLink before
starting another scan. Health and status reads retain transport fallback.
