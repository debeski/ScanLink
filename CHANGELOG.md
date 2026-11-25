# Changelog

This file owns the release history for `ScanLink`.

## Unreleased

- **Callbacks Delivered, To Linked Websites Only (security)**: a finished scan was never posted to its `callback_url`. Since 2026-04-28, `_process_job` passed `_send_callback` the public job snapshot, which carries no URL. `ScanWorker._start_callback` now posts the stored PDF on its own thread (connect 5 s, read 30 s, redirects not followed, only 2xx counts). `SiteRegistry.allows_callback` limits the destination to an allowed website: a browser request may name only its own website or the sites linked with it, and a local tool or `scanlink://` link may name any linked or listed website. The check runs at submission (`400 callback_not_allowed` on `/scan` and `/internal/protocol/scan`; a refused `scanlink://` launch never scans) and again before sending. Each job reports `callback.state` (`waiting`, `sending`, `delivered`, `failed`, `refused`, `not_sent`), and the PDF stays available to poll either way. Without the rule, delivery would have let any page post a scanned document to a host of its choosing through a `scanlink://` link.

## v0.8.0

- **Stable 0.8.0 For DjangoLux 1.16 (security)**: Promote the published and accepted 0.8.0b3, which includes 0.8.0b1 and b2. No website can scan until the operator allows it once (`POST /link`; `cors_origins` ignores wildcards); the API answers only loopback hosts, refuses cross-site control requests, limits request bodies and keeps each scan to the origin that started it. Scans survive slow scanners and worker failures (deadline grace, atomic PDF completion, single-use results). Needs DjangoLux 1.16.0 or later. No changes from the beta.

## v0.8.0b3

- **No Website Can Scan Until Allowed (security)**: `cors_origins` defaults to `[]` and ignores wildcards, so a saved `["*"]` no longer lets any website scan silently. A website asks with `POST /link`, and the operator allows it once in ScanLink's window, which names it; a linked DjangoLux site also allows its administrator's sites. Needs DjangoLux 1.16.0b3 or later.
- **Loopback Host Check**: `server.create_app()` refuses every request whose `Host` header is not `localhost`, `127.0.0.1` or `[::1]` with `403 invalid_host`, so a DNS-rebound page cannot reach the API as a same-origin client.
- **Local-Only Control Endpoints**: `POST /shutdown` and `POST /internal/protocol/scan` refuse any request carrying `Origin` or `Sec-Fetch-Site` with `403 local_only`, so a cross-site form post can no longer shut ScanLink down; the protocol forwarder and local scripts send neither header.
- **Scan Ownership By Origin**: `ScanWorker.submit_job()` records the requesting `Origin`; `GET /scan/<job_id>` and `/result` answer `404 job_not_found` to any other origin, and `409 busy` includes `active_job_id` only for the job's own origin, so a website can no longer learn, follow and download another website's scan.
- **Server-Side Origin Allow-List**: Browser-endpoint requests from a website that is not allowed are refused with `403 origin_not_allowed` before any work, instead of only omitting CORS headers; the refusal carries CORS headers so the page can read it and offer to link.
- **Request Body Limit**: `MAX_CONTENT_LENGTH` is 64 KB, answered as `413 payload_too_large`; a 64 MB `metadata` body was previously accepted, kept with the job for its 15-minute TTL and returned by every status poll. HTTP errors (`404`, `405`, `413`, `500`) now use the JSON error shape with CORS headers.
- **Private Network Access Preflight**: Preflights carrying `Access-Control-Request-Private-Network: true` receive `Access-Control-Allow-Private-Network: true`.
- **Non-Blocking TLS Accept**: `LoopbackServer` accepts HTTPS connections without handshaking and `LoopbackRequestHandler` completes the handshake in the connection's own thread; one TCP client that never sent a TLS hello previously stalled every HTTPS request indefinitely.
- **Connection Timeout**: `LoopbackRequestHandler` sets a 30-second socket timeout (`REQUEST_TIMEOUT_SECONDS`), so half-sent or idle connections no longer hold a server thread forever.
- **Compressed Page Capture**: `ScannerManager` encodes each captured page to JPEG on arrival (`_encode_page`) and `_create_pdf` embeds the JPEG files through `drawImage(path)` instead of decoding them again through `ImageReader`; the scan child's peak memory for 20 pages at 300 DPI drops from about 2 GB to 0.2 GB, which previously exhausted x86 builds. Image streams in the PDF are unchanged.
- **Scan Worker Directory Check**: `scan_runtime.run_scan_job()` refuses any `--scan-worker-dir` that is not a `scanlink-job-*` directory directly inside the temp directory, so an argument injected through an unescaped `scanlink://` launch cannot read a request from, or write a scanned PDF to, another folder or a network share.
- **Helper Identity Check**: `protocol_handler.is_existing_instance_running()` and `forward_protocol_command()` accept only ScanLink-shaped answers, so another program returning `200` on port 5000 no longer makes a new ScanLink exit as a duplicate or swallow a protocol scan.
- **Protocol Log Lines**: `parse_protocol_url()` logs URLs and parsed values with `%r`, so a `scanlink://` URL with encoded line breaks cannot forge `scanner.log` entries.

## v0.8.0b2

- **Scan Deadline Grace**: `ScanWorker` adds `SCAN_TIMEOUT_GRACE_SECONDS` (15s) to the parent's `scan_timeout_seconds` kill limit so the child's own deadline closes TWAIN and reports its error before forced termination; `gui_task_timeout_seconds` is unchanged.
- **Callback URL Parsing**: `_send_callback` skips URLs that `urlparse` rejects instead of raising after completion.
- **Per-Scan Transport Check**: `scanlink.js` `startScan()` health-checks before every scan POST, falling back from a stale preferred transport and reporting `helper_unavailable`/`insecure_origin` instead of `scan_request_uncertain` when the helper is unreachable.

## v0.8.0b1

- **Atomic PDF Completion**: Keep child completion provisional until the process exits and the parent stores result bytes; publish terminal errors with their details.
- **Parent Scan Deadline**: Enforce the configured scan deadline even when the child keeps reporting progress, independently of GUI and idle limits.
- **Scan Payload Validation**: Reject non-object JSON, invalid metadata/callback types and non-JSON protocol requests before queueing hardware work.
- **Single-Use Result Metadata**: Free consumed PDF bytes immediately while retaining job metadata until its TTL so racing downloads consistently receive 410.
- **One Scan POST Per Attempt**: Negotiate transport through health checks and report `scan_request_uncertain` after a lost scan response instead of resubmitting over another transport.
- **Real Worker Regressions**: Exercise actual child-process completion, parent timeout enforcement, malformed requests and competing PDF downloads with only the scanner child simulated.

## v0.7.5b1

- **Windows x86 Crypto Wheels**: Resolve cryptography from compatible binary wheels during executable builds, avoiding an unsupported latest-source Rust/OpenSSL compilation on 32-bit Python.

- **Windows First-Launch Consent Gate**: Exercise the specific ScanLink certificate Yes prompt in installed-app tests instead of bypassing trust; stress 120 normally verified HTTPS requests per architecture and log certificate setup stages.

- **Beta Publication**: Mark beta/RC tags as GitHub prereleases and keep the stable latest pointer unchanged.

- **Automatic Windows HTTPS Setup**: Provision and trust a localhost-only server certificate for the current Windows user during normal startup; encrypt its key with a DPAPI-protected password, repair missing trust, and renew within 30 days of expiry.
- **Background Setup And Renewal**: Preserve HTTP scanning while preparing HTTPS, expose `https_setup` in `/health`, swap renewed identities for new TLS handshakes, and offer native Retry plus a tray repair action on setup failures.
- **Installer HTTPS Verification**: Verify trusted HTTPS without bypassing certificate checks and reuse the identity after restart in both x86/x64 installed-app smoke gates; remove the optional mkcert build dependency.

## v0.7.4

- **Windows Installed-App Verification**: Added x86/x64 installer smoke tests for installed assets, HKCU startup/protocol registration, packaged runtime identity, live REST endpoints, protocol launch, and graceful shutdown before artifact publication.
- **Critical API Coverage**: Added unit tests for runtime health identity, browser scan payloads, validation failures, status/result errors, one-time PDF retrieval, protocol queuing, and shutdown signaling.

## v0.7.3

- **Mandatory Release Test Gate**: Made `tests` importable for top-level unittest discovery and blocked both release build jobs on the exact Windows test command used by CI.

## v0.7.2

- **Archive-Safe Scanner Profile Defaults**: Added persisted scan profile settings with legacy config migration to ADF source, front-only/simplex side mode, 200 DPI, color pixel type, and `CAP_PAPERPROTECTION=False` for scanner batches used by archive uploads.
- **TWAIN Source And Side Controls**: Added tray menu controls for source (`adf`/`flatbed`), side (`front`/`front_back`), and color mode (`color`/`grayscale`/`black_white`), applying `CAP_FEEDERENABLED`, `CAP_AUTOFEED`, `CAP_DUPLEXENABLED`, `ICAP_PIXELTYPE`, and optional `ICAP_BITDEPTH` before acquisition.

## v0.7.1

- **Paper Protection Fix**: Disabled the TWAIN `CAP_PAPERPROTECTION` capability by default during silent scanning. The scanner driver's default (high-sensitivity) setting was generating frequent false "paper stuck" errors during batch scanning, forcing operators to remove the paper stack and retry. Behaviour now matches PaperStream Capture.
- **Paper Protection Toggle**: Added a **Paper Protection** menu item to the system tray so the setting can be re-enabled for workflows that require it (e.g., scanning fragile documents) without editing config files.

## v0.7.0

- Removed deprecated Socket.IO/WebSocket runtime dependencies.
- Standardized ScanLink client behavior on REST health checks, status polling, and result download.
- Installer now includes the standalone `static/scanlink.js` helper.

## v0.5.0

- **REST-First Local API**: Standardized the helper around the `/health`, `/scan`, `/scan/<job_id>`, and `/scan/<job_id>/result` contract so browser clients can reliably poll for status and fetch finished PDFs.
- **Dual Loopback Transport**: Changed startup so ScanLink always serves HTTP on `127.0.0.1:5000` and enables HTTPS on `127.0.0.1:5443` only when trusted localhost certificates are available.
- **Single Active Job Enforcement**: Replaced silent queue stacking with explicit busy rejection, added structured terminal states (`failed`, `cancelled`, `timed_out`), and introduced result/job TTL cleanup after retrieval or expiry.
- **Single-Instance Protocol Forwarding**: Updated `scanlink://` handling so protocol launches are forwarded into the already-running tray app instead of spawning competing helper instances.
- **Tray and Installer Hardening**: Fixed tray menu boot reliability, moved the installer to per-user installation without requiring admin rights, and made trusted HTTPS generation optional instead of a critical-path requirement.

## v0.4.0

- **HTTPS/SSL**: Auto-generates trusted localhost certificates via mkcert.
- **Deep Links**: Added the `scanlink://` protocol for instant browser-triggered scans.
- **WebSocket**: Added real-time scan status streaming (`queued` to `page_scanned` to `completed`).
- **Django Integration**: Added the `scanlink.js` client library.
- **Startup Fix**: Registry-based startup prevents the double-launch bug.
- **Callback URLs**: POST scan results directly to Django endpoints.

## v0.3.0

- **Refactoring**: Modularized the codebase (`server`, `scanner`, `worker`, `tray`).
- **Queue System**: Added a job queue for reliable scanning.
- **UI Improvements**: Added "Test Scan" and active status in the tray.
- **Memory**: Optimized image handling with in-memory DIB processing.

## v0.2.0

- **Major Optimization**: Implemented image compression with JPEG 85%.
- Added resolution controls for 160, 200, 240, and 300 DPI.
- Reduced file size by 80%, with average pages under 500 KB.
- Added the Inno Setup installer script.

## v0.1.2

- Added "Select Scanner" GUI dialog.
- Improved error handling for busy scanners.
- Added logging system.

## v0.1.1

- Added multi-page support.
- Implemented system tray icon.
- Added default scanner memory.
- Added startup-on-boot option.

## v0.1.0

- Initial release.
- Added basic TWAIN scanning support.
- Added single-page PDF generation.
- Added localhost API endpoint.
