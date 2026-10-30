# ScanLink Architecture

ScanLink is a Windows tray application that exposes a local browser API and isolates scanner acquisition in a child process.

## Runtime Modules

| File | Role |
| --- | --- |
| `main.py` | Main entry point. Handles CLI modes, initializes Tk, starts the worker, server, and tray threads. |
| `server.py` | Flask app for local REST endpoints. Starts HTTP and optional HTTPS loopback listeners. |
| `worker.py` | Owns scan job state, enforces one active job, launches scan subprocesses, stores results, and sends callbacks. |
| `scan_runtime.py` | Runs inside the child scan process. Reads job request files, calls the scanner, writes progress state and result PDF. |
| `scanner.py` | TWAIN scanner manager. Lists sources, opens the selected scanner, acquires pages, and generates PDFs. |
| `tray.py` | System tray icon and menu actions. Controls source, side, color mode, resolution, diagnostics, startup, scanner UI, paper protection, and quit. |
| `protocol_handler.py` | Parses `scanlink://` URLs and forwards protocol launches to an existing local instance. |
| `certificates.py` | Per-user localhost identity, Windows trust, DPAPI key-password protection, and renewal. |
| `utils.py` | Shared logging, config, version, SSL certificate, startup, and resource helpers. |
| `gui/dialogs.py` | Tk dialogs for scanner selection and diagnostics output. |

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
  "cors_origins": ["*"],
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
3. If forwarding succeeds, the new process exits.
4. If no instance is running, the new process becomes the tray instance and queues the protocol scan after startup.

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
parent force-terminates it. Unparseable callback URLs are skipped without
affecting the stored PDF. Idle timeout remains an independent progress guard. Downloading frees
the PDF immediately and retains consumed-job metadata until the normal job TTL,
so repeated or racing downloads report `410` while that metadata exists.

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
