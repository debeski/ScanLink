# Changelog

This file owns the release history for `ScanLink`.

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
