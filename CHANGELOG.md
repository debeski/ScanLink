# Changelog

This file owns the release history for `ScanLink`.

## v0.8.1

- **Stable 0.8.1 For DjangoLux 1.17.0 (security)**: Promote the published and accepted 0.8.1b2, which includes 0.8.1b1. Scan callbacks are delivered to linked websites only, and only to public HTTPS targets: the host is checked again at delivery with no second lookup, no proxy is used and ScanLink's own endpoints refuse delivery requests (R2-010). Widening a linked list asks again, approval windows are rationed and show every site in full, callbacks and requests are bounded in time and number, and the scan result handling is hardened. No changes from the beta.

## v0.8.1b2

- **Callbacks Reach Public HTTPS Websites Only (security, R2-010)**: a linked website could list `http://127.0.0.1:…`, `localhost`, private, link-local or metadata addresses, or ScanLink itself, and every scan was then posted there from the operator's computer without `Origin` or `Sec-Fetch-*`; a callback to `http://localhost:5000/shutdown` stopped ScanLink. New `callback_transport` module: `check_callback_url` requires `https` and refuses `localhost`, `*.localhost` and non-public address literals in any spelling (`127.1`, `2130706433`, `[::ffff:127.0.0.1]`) at submission (`400 callback_not_allowed`); `post_scan` resolves the host itself, refuses the delivery if any address is loopback, private, CGNAT, link-local, unique-local, multicast, reserved, unspecified, an embedded IPv4 of those (mapped, NAT64, 6to4, Teredo) or one of this computer's own, connects to the checked address with TLS verified for the host name and re-checks the peer, so DNS rebinding cannot reach this computer (`callback.state: refused`, `reason: blocked_address`). Deliveries carry `X-ScanLink-Delivery`, and every endpoint answers such a request with `403 local_only`. Callbacks use the standard library instead of `requests` and never a proxy.
- **Widening A Linked List Asks Again (security, R2-054)**: `SiteRegistry.link` replaced a linked website's list without a window, so one approval let XSS on that site grant the scanner to any origin. A list that gains a site now opens the approval window again, naming the added sites (`confirm(..., added_sites=…)`); until the operator allows them the website stays linked with its approved list, and a declined widening answers `403 link_declined`. Shortening a list stays silent.
- **Bounded Callback Responses (R2-055)**: the callback answer was read in full with a per-read timeout, so a 1 GB body or a gzip bomb was buffered and a body dripping a byte every 20 s held a thread and the PDF forever. `post_scan` sends `Accept-Encoding: identity`, reads only the status line and headers, and a watchdog closes the connection 120 s (`DELIVERY_DEADLINE_SECONDS`) after the delivery started; at most two callbacks are in flight (`MAX_CALLBACKS_IN_FLIGHT`), a third is `failed` with `reason: busy`.
- **Rationed Approval Windows (security, R2-056)**: any website could reopen ScanLink's approval window at once from a sibling subdomain or another port, or forever after leaving it unanswered. Cooldowns now apply to the registrable domain (`sites.cooldown_key`): 10 minutes after **Don't allow** (`403 link_declined`), 5 minutes after an unanswered window (`429 link_rate_limited`). After an unknown website's window closes without **Allow**, other unknown websites wait 2 minutes (`429 link_rate_limited`). A website ScanLink already knows is exempt from that wait and closes an unknown website's open window to ask its own (that request answers `409 link_pending`). The window no longer takes keyboard focus or a grab.
- **Approval Window Shows Every Site In Full (security, R2-115)**: the other-sites list showed 6 rows of 56 characters, so long or numerous sites were approved unseen, and hosts with bidi overrides, zero-width characters or look-alike letters were shown verbatim. `gui.dialogs.confirm_site_link` lists every site (up to 20 rows, as wide as the longest, with scrollbars beyond that) and `utils.normalize_origin` refuses hosts with control, format or separator characters or a trailing dot and stores non-ASCII hosts in their `xn--` form, as browsers send them.
- **Correct Page Count (R2-118)**: the parent polled `state.json` every 250 ms and the child's final `completed` state had no `page_count`, so 5-page scans reported 1 or 2. `scan_runtime.run_scan_job` writes `page_count` into the final state and `ScanWorker._run_scan_subprocess` applies the final state after the child exits.
- **No Orphaned Scans (R2-119)**: killing ScanLink mid-scan left the child scanning, holding the scanner, and its `scanlink-job-*` folder with the PDF in `%TEMP%`. On Windows each child joins a kill-on-close job object; `request.json` carries `parent_pid` and the child (`scan_runtime.watch_parent`) removes its folder and exits when that process ends; `worker.sweep_stale_directories` removes `scanlink-job-*`/`scanlink-pages-*` folders older than 30 s at worker start and every 10 minutes while idle.
- **HEAD And Cut-Off Downloads Keep The Result (R2-120)**: `HEAD /scan/<id>/result` ran the download view and spent the single-use PDF, and a dropped download lost the scan. `HEAD` now answers from `ScanWorker.peek_result` without counting; `consume_result` answers one retry within 30 s of the first download (`RESULT_RETRY_GRACE_SECONDS`) before freeing the bytes.
- **Monotonic Result Lifetimes (R2-121)**: job and result TTLs used `time.time()`, so a clock jump forward deleted an unread result and one backwards kept the PDF in memory for days. `_cleanup_expired_jobs_locked` measures from `time.monotonic()` stamps; wall-clock fields remain for display.
- **Safe `doc_id` (R2-122)**: a CR/LF in `doc_id` (also through `scanlink://scan?docId=…%0a…`) forged `scanner.log` lines, and any JSON type was accepted. `worker.clean_doc_id` accepts text of at most 200 characters without control, format or line-separator characters, or a whole number; anything else is `400 invalid_doc_id` on `/scan` and `/internal/protocol/scan`. Job log lines use `%r`.
- **Standard JSON Only (R2-123)**: `{"doc_id": NaN}` was stored and every status poll echoed invalid JSON. The app's `StrictJSONProvider` rejects `NaN`, `Infinity` and `-Infinity` as `400 invalid_json`.
- **Mid-Acquisition Deadline Is A Timeout (R2-124)**: a scan deadline reached while pages were still arriving was re-wrapped as `acquire_failed`/`failed`. `ScannerManager.scan_to_pdf` re-raises `ScanError` unchanged, so it stays `acquire_timeout`/`timed_out`.
- **Whole-Request Deadline And Connection Cap (R2-125)**: the 30 s socket timeout restarted on every byte, so a client sending one byte every 20 s held its thread for good and about 200 such sockets filled the listen queue. `LoopbackRequestHandler` reads through a deadline reader: line, headers and body must arrive within 30 s (`REQUEST_DEADLINE_SECONDS`), and the TLS handshake within the same time; `BoundedThreadedWSGIServer` serves at most 64 connections (`MAX_CONCURRENT_CONNECTIONS`) and closes the rest at accept.

## v0.8.1b1

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
