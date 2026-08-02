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

HTTPS starts only when these files exist and load successfully:

```text
%LOCALAPPDATA%\ScanLink\localhost.pem
%LOCALAPPDATA%\ScanLink\localhost-key.pem
```

They can be generated with:

```powershell
ScanLink.exe --generate-ssl
```

when `mkcert.exe` is available in the bundled resources.

## Single Instance and Protocol Handling

When launched with a `scanlink://` URL:

1. `main.py` parses the URL with `protocol_handler.parse_protocol_url()`.
2. It tries to forward the command to `http://127.0.0.1:5000/internal/protocol/scan`.
3. If forwarding succeeds, the new process exits.
4. If no instance is running, the new process becomes the tray instance and queues the protocol scan after startup.

This prevents duplicate tray apps and competing scanner sessions.
