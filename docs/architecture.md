# ScanLink Architecture

ScanLink is a Windows tray application that exposes a local browser API and isolates scanner acquisition in a child process.

## Runtime Modules

| File | Role |
| --- | --- |
| `main.py` | Main entry point. Handles CLI modes, initializes Tk, starts the worker, server, and tray threads. |
| `server.py` | Flask app for local REST endpoints. Starts HTTP and optional HTTPS loopback listeners. |
| `worker.py` | Owns scan job state, enforces one active job, launches scan subprocesses, stores results, and sends callbacks. |
| `callback_transport.py` | Checks callback destinations (public `https` only) and posts a finished scan to the address it checked, with an overall deadline. |
| `sites.py` | Websites allowed to scan: `cors_origins`, linked websites, their lists, and the rationing of approval windows. |
| `scan_runtime.py` | Runs inside the child scan process. Reads job request files, calls the scanner, writes progress state and result PDF. |
| `scanner.py` | TWAIN scanner manager. Lists sources, opens the selected scanner, acquires pages, and generates PDFs. |
| `tray.py` | System tray icon and menu actions. Controls source, side, color mode, resolution, diagnostics, startup, scanner UI, paper protection, and quit. |
| `protocol_handler.py` | Parses `scanlink://` URLs and forwards protocol launches to an existing local instance. |
| `certificates.py` | Per-user localhost identity, Windows trust, DPAPI key-password protection, and renewal. |
| `utils.py` | Shared logging, config, version, SSL certificate, startup, and resource helpers. |
| `gui/dialogs.py` | Tk dialogs for scanner selection, diagnostics output and website approval. |

## Non-Runtime Project Files

| File | Role |
| --- | --- |
| `build_exe.py` | Creates PyInstaller executables for x86/x64 builds. |
| `generate_icon.py` | Generates `app_icon.png` and `app_icon.ico`. |
| `tests/*.py` | Unit tests. |
| `setup.iss` | Inno Setup installer script. |
| `static/scanlink.js` | Browser helper for REST polling and deep-link triggering. |

## Process Model

The normal tray app process does not directly perform scanner acquisition. Instead, it starts a child scan process for each job.

```text
main.py
  creates Tk root
  starts ScanWorker thread
  starts Flask server thread
  starts tray thread
  runs Tk event loop

server.py
  POST /scan
    -> worker.submit_job()

worker.py
  accepts one active job
  creates temp job directory
  writes request.json
  launches:
    python main.py --scan-worker-dir <temp-job-dir>

main.py --scan-worker-dir
  routes to scan_runtime.run_scan_job()

scan_runtime.py
  creates child Tk root
  calls scanner.ScannerManager.scan_to_pdf()
  writes state.json progress
  writes result.pdf

worker.py
  reads state.json
  stores final PDF bytes in memory
  exposes result through server.py
```

This subprocess boundary protects the tray/API process from scanner driver crashes, stuck TWAIN calls, and long-running acquisition operations.

The child does not outlive ScanLink. On Windows, `ScanWorker` places every child
in a job object that ends it when ScanLink's own process ends (kill-on-close),
which also releases the TWAIN source. `request.json` carries `parent_pid`, and
the child watches that process: when it disappears, the child removes its job
directory and exits. When the worker starts, and every 10 minutes while it is
idle, it removes `scanlink-job-*` and `scanlink-pages-*` folders older than 30
seconds from the temp directory, which an earlier ScanLink killed mid-scan left
with the scanned pages inside.

The child writes `page_count` into its final `completed` state, and the parent
applies that last state after the child exits, so the reported page count does
not depend on which progress states its 250 ms polls happened to see.

`scan_runtime.run_scan_job()` only runs in a `scanlink-job-*` directory directly
inside the user's temp directory, the only kind `ScanWorker` creates. Any other
`--scan-worker-dir` value, such as one injected through an unescaped
`scanlink://` launch or a network share path, exits with code 1 before reading
or writing anything.

The child compresses each page to JPEG (quality 85) as soon as it is captured and
embeds those JPEG files in the PDF unchanged, so its memory grows with the
compressed page size rather than with decoded images (about 26 MB per A4 page at
300 DPI color). Long ADF batches therefore fit in a 32-bit (x86) build.

## Thread Model

Main process:

- Main thread: Tk event loop.
- `ScanWorker`: queue and job lifecycle.
- `LoopbackServerManager`: starts HTTP/HTTPS listener threads.
- `TrayThread`: pystray icon loop.

The worker can ask the main Tk loop to run GUI-sensitive work through `gui_task_queue`. This keeps scanner dialogs and diagnostics on the GUI side when needed.

Child scan process:

- Initializes its own Tk root.
- Runs one scan.
- Reports progress through files in the temporary job directory.
- Exits with a status code.

## Job State

`worker.ScanWorker` stores jobs in memory. Job objects include:

- `job_id`
- `status`
- timestamps
- `doc_id`
- `metadata`
- `page_count`
- `result_bytes`
- `error`

Terminal statuses:

- `completed`
- `failed`
- `cancelled`
- `timed_out`

## Configuration

Configuration is stored per user:

```text
%LOCALAPPDATA%\ScanLink\config.json
```

Defaults are provided in `utils.load_config()`:

```json
{
  "scan_profile_version": 1,
  "resolution": 200,
  "scan_source": "adf",
  "scan_side": "front",
  "color_mode": "color",
  "default_scanner": null,
  "show_scanner_ui": false,
  "paper_protection": false,
  "cors_origins": [],
  "linked_sites": {},
  "job_ttl_seconds": 900,
  "result_ttl_seconds": 300,
  "scan_timeout_seconds": 600,
  "gui_task_timeout_seconds": 900,
  "scan_idle_timeout_seconds": 45
}
```

The default scan profile is tuned for archive uploads: ADF, front-only/simplex,
200 DPI, color, and paper protection off. Older config files without
`scan_profile_version` are migrated to those profile values when loaded.

Logs are written to:

```text
%LOCALAPPDATA%\ScanLink\scanner.log
```

## Local Transports

HTTP:

```text
127.0.0.1:5000
```

HTTPS:

```text
127.0.0.1:5443
```

Each listener is a threaded werkzeug server that serves one connection per
thread, at most 64 at once (`MAX_CONCURRENT_CONNECTIONS` in `server.py`); a
connection beyond that is closed when it is accepted. Its
`LoopbackRequestHandler` applies a 30-second socket timeout
(`REQUEST_TIMEOUT_SECONDS`) to every connection and a 30-second deadline
(`REQUEST_DEADLINE_SECONDS`) to each request: its line, headers and body must
all arrive within 30 seconds, however slowly the bytes trickle in, and the TLS
handshake must finish within the same time. The HTTPS listener performs the
handshake in that connection's thread rather than in the accept loop, so an idle
or slow client only holds its own thread until the deadline and never blocks
other clients. Time a request spends being answered, such as `POST /link`
waiting for the operator, does not count.

On normal startup the server thread starts HTTP first, then prepares a trusted
HTTPS identity automatically. A one-year self-signed **server** certificate
(`BasicConstraints CA=False`, serverAuth EKU, no certificate-signing usage)
covers only `localhost`, `127.0.0.1`, and `::1`. Windows CryptoAPI adds that
specific certificate to **CurrentUser\Root**; no general-purpose CA, shared key,
external certificate service, administrator CLI or machine-wide trust is used.
Browser/organization policy can still block user-installed trust.

`certificates.LocalIdentity` keeps immutable identities under
`%LOCALAPPDATA%\ScanLink\https\<identity>\`. `localhost.pem` contains the
public certificate and an encrypted PKCS#8 private key; `password.dpapi` holds
the random key password encrypted for this Windows login. `active.json` points
to the current identity. Key material is validated before activation; HTTPS is enabled only after trust verification.
failed trust installation is reported as failure and retried with the same
identity. Superseded identities move to `.xclude/https/` in the app data folder.
Existing legacy mkcert credentials are not used or removed.

Each launch checks validity, names, purpose, key matching and Windows root-store
membership. Missing trust is repaired without replacing the key. Identities
within 30 days of expiry are renewed. The server rechecks hourly and selects
the current SSLContext on each new TLS handshake, preserving active connections.
HTTP scanning stays available during setup. `/health.https_setup` is
`preparing`, `ready`, or `failed`. A failed first attempt opens a native Retry
prompt; the tray has **Retry secure connection setup** for later repairs.
Automatic hourly retries do not repeatedly open dialogs.

`--generate-ssl` remains a support/development compatibility command; ordinary
installation and use do not require it. The installer launches the normal app,
which performs the same setup for installed and portable builds. Uninstall
keeps the encrypted identity so a reinstall can reuse it. The generated certificate has server-only usage and no certificate-signing
permission. Nothing is sent to the application VM.

The paired DjangoLux patch is 1.15.1b1; the REST API remains compatible with older
clients. Browser local-network permission, CSP and an insecure application
origin are separate from ScanLink certificate provisioning.

## Single Instance and Protocol Handling

When launched with a `scanlink://` URL:

1. `main.py` parses the URL with `protocol_handler.parse_protocol_url()`.
2. It tries to forward the command to `http://127.0.0.1:5000/internal/protocol/scan`.
3. If forwarding succeeds, the new process exits. Forwarding succeeds only on a ScanLink answer: `202` with a `job_id`, or `409` with error code `busy`.
4. If no instance is running, the new process becomes the tray instance and queues the protocol scan after startup. An instance counts as running only when `/health` returns ScanLink's JSON (`status: ok` with `version` and `twain_available`), so another program answering on port 5000 does not make ScanLink exit.

This prevents duplicate tray apps and competing scanner sessions.

## Worker completion and deadlines

Child progress is provisional. A child `completed` update remains
`generating_pdf` to API clients until the process exits and the parent stores the
PDF atomically with the final `completed` status. Child failure states are also
published by the parent with their error details after process exit.

The parent enforces both `scan_timeout_seconds` and `gui_task_timeout_seconds`;
the first enabled deadline terminates the child, even if it keeps reporting
progress. The scan deadline includes a 15-second grace (`SCAN_TIMEOUT_GRACE_SECONDS`
in `worker.py`) covering child startup, so a child that honours its own
`scan_timeout_seconds` closes the TWAIN source and reports its error before the
parent force-terminates it.

A deadline the child reaches while pages are still arriving is reported as
`acquire_timeout` with status `timed_out`, like any other scan deadline.

Once the PDF is stored, the parent posts it to the job's callback URL on a
separate thread (`ScanWorker._start_callback`), at most two at a time
(`MAX_CALLBACKS_IN_FLIGHT`).
- **Destination check:** `SiteRegistry.allows_callback` decides where it may go: an `https` URL on an allowed website whose host is not `localhost` or a non-public address literal (`callback_transport.check_callback_url`). `main.py` gives it to the worker as `callback_guard`, and without one every callback is refused. It runs when the job is submitted and again before sending.
- **Connection check:** `callback_transport.post_scan` resolves the host itself, refuses it if any address is not public or belongs to this computer, connects to the checked address with TLS verified for the host name, and checks the connected peer again. No proxy is used, redirects are not followed, the answer's body is never read, and a watchdog closes the connection 120 seconds after the delivery started.
- **Failures:** a refused or failed callback never affects the stored PDF.

Idle timeout remains an independent progress guard. A PDF can be downloaded
twice, the second time within `RESULT_RETRY_GRACE_SECONDS` (30) of the first;
then its bytes are freed and the job's metadata stays until the job TTL, so
later downloads report `410` while that metadata exists. `HEAD` does not count
as a download. Job and result lifetimes run on `time.monotonic()`; the
wall-clock stamps in job snapshots are for display only.

## 0.8.0b1 release acceptance

The published x64/x86 installers passed Windows CI and release gates, including
the native certificate consent prompt, 120 normally verified HTTPS requests per
architecture and identity reuse after restart. Published installer digests were
checked through the development project's authenticated distribution endpoints.
The real worker also passed file-field/PDF-editor compatibility with published
DjangoLux 1.15.1b1. Scanner hardware was simulated for local job tests; physical
TWAIN and native browser/enterprise-policy acceptance remain separate checks.

The paired published DjangoLux 1.15.1b2 acceptance passed on 2026-10-26:
Composer upgrade with full backup, 694 package hashes in web/Celery, published
client/templates, 300 health checks, 30 scans, 20-way contention, PDF save/download
and Arabic lost-response guidance with one accepted scan POST. Both installer
distribution hashes matched. The helper was stopped; physical scanner acceptance
remains outstanding.
