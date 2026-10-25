# ScanLink tracker

## Part 1: Project-specific
### Current Snapshot
- Published 0.8.0b1 on `0.8/stress_fixes` (2026-10-25): real worker completion/deadline, public/internal input validation, single POST transport behavior and result-race fixes. Published0.7.5b1 (tagd74bf90) and stable Latest0.7.4 unchanged; owner authorized publication2026-10-25; PR2 merged as a82aab7; v0.8.0b1 published, release40233617433 PASS, x64/x86 asset digests verified; stable Latest stays0.7.4.
- Windows tray app uses TWAIN/pytwain; scan jobs run through child `main.py --scan-worker-dir` / `scan_runtime.py`.
- Normal startup serves HTTP :5000 while automatically provisioning trusted localhost HTTPS :5443; failed setup offers native Retry and a tray repair action.
- `certificates.py`: per-user localhost-only self-signed server identity, Windows CurrentUser Root trust, encrypted PKCS#8 key with DPAPI-protected password; hourly checks/30-day renewal and live TLS context selection.
- Paired DjangoLux1.15.1b2 published/accepted2026-10-26 (PR15 explicit owner bypass, fa729074/release40240597894 PASS).8097 web/celery use published b2;694-file checks, published UI/Arabic single-POST recovery and installer distribution PASS. Existing REST APIs remain compatible.

### Adopted Standards & Rules
- Owner selected the0.8.0 line;0.8.0b1 published2026-10-25. Preserve immutable0.7.5b1/0.8.0b1 artifacts; further fixes need a fresh workstream/version.
- One patch/workstream per release-line branch; VERSION is the version source. Do not tag or publish without owner approval.
- App data/config/logs live under `%LOCALAPPDATA%\ScanLink`; identity pointer is `https/active.json`, immutable bundles `https/<id>/`, superseded identities `.xclude/https/<id>/`.
- Certificate covers only localhost/127.0.0.1/::1, CA=False/serverAuth/no certificate-signing usage; no downloaded/shared CA or machine-wide trust. Existing mkcert credentials stay untouched.
- HTTP remains supported; browser local-network permission, CSP, enterprise trust and an insecure application origin are independent restrictions.
- Never delete workspace files; relocate under `.xclude/` preserving relative paths. Match executable architecture to the TWAIN driver.

### Known Bugs & Unsolved Issues
- Six stress defects fixed in the published pair: premature completion/PDF unavailable, parent deadline ignored, malformed public payload500/callback parsing, non-JSON protocol requests queueing, ambiguous POST retries, consumed results returning404. Native Windows CI/release gates PASS; physical hardware remains pending.
- Windows x64/x86 unit/build/install gates passed, including real certificate consent, DPAPI/trust, 120 verified HTTPS requests per architecture and restart identity reuse. Real Windows browser/scanner and enterprise-policy acceptance remain manual.
- Target PaperStream fi-6230Z may expose only 32-bit TWAIN; live driver compliance/output quality remain unverified. Back-only and blank-page discard remain unsupported.
- Organization/browser policies may refuse user-installed trust. A denied setup is reported as failure and retried with the same identity, without repeated automatic dialogs.

### Active & Pending Tasks
- [x] Paired deeper stress and real-worker regressions pass; candidate0.8.0b1 prepared locally. Owner authorized next beta; PR2 merged after x86/x64 native CI PASS, release gates PASS, both installers published.
- [x] Windows x64/x86 installed-app gates and normally verified HTTPS load passed before and during beta publication; stable Latest preserved.
- [ ] Verify0.8.0b1 with target scanner hardware; preserve ADF/front/200 DPI/color/paper protection off defaults.
- [x] Paired1.15.1b2 published/Composer-installed on8097 with full backup IB-esVxV;694 files verified in web/celery. Both0.8.0b1 installers advertised; hashes/auth/100 manifests PASS.
- [ ] Archive-hosted helper update path and detailed TWAIN capability diagnostics remain separate work.
### Completed Recently
- [x] Automatic setup/repair/renewal and plain native recovery; removed optional mkcert packaging requirement and retained `--generate-ssl` for support compatibility.
- [x] Extended installer smoke to normal Windows-trusted HTTPS and restart reuse; health timeout/fallback behavior matches the paired browser client.
- [x] Verified real TLS handshakes, hostname rejection and live identity renewal; setup failure preserves HTTP and Retry recovers HTTPS.

### Validation & Docs Log
- 2026-10-25: 40 local unit tests OK/1 Windows skip; Windows CI/release PASS x64+x86 including consent/120 HTTPS/restart; pairedJS24 PASS; real worker1000 health (500 verified TLS)/100 hashed PDFs/50 busy/40 result races PASS; timeouts/crash/cancel/callback/shutdown recovery PASS.8097 UI300 health/30 scans/20 simultaneous, PDF save/Arabic lost-response guidance/one POST PASS. Dlux3064 OK/6skips +79 focused; doctor0error. Native candidate gates now PASS; physical hardware/Windows browser policies unverified.
- 2026-10-25: API/architecture/developer guide, VERSION0.8.0b1 and CHANGELOG document parent-owned completion, hard deadline, strict payloads, retained metadata and scan_request_uncertain. Local report `.xclude/validation/paired-stress-2026-10-25.md`.

## Part 2: Global & Handoff
### Global Helpers & Rules
- Use `rg` first. Unit wrapper: `python -m unittest discover -s tests -t . -v`; installer gate: `tests/windows_install_smoke.ps1` on Windows.
- Test stacks belong under `~/Desktop/depy/testbed-*`, use Composer `--dev` and application admin/db123123; preserve testbed-dlux.
### Agent Handoff
- Both patch checkouts are authorized by the owner from the app-mock-pdf chat; preserve that checkout's unrelated uncommitted changes.
- 2026-10-26: PR15 bypass explicitly authorized;1.15.1b2 published/accepted with0.8.0b1.8097 keeps60 records, full backup IB-esVxV and fixture60 now9 pages/8 history versions. Helper stopped;8088/8096 and app-mock-pdf preserved. Physical TWAIN/native browser-policy acceptance remains manual. Report `.xclude/validation/beta-release-080-1151b2.md`.
- Evidence: `.xclude/validation/`; paired Chrome evidence is in `pkg-django-lux/scanlink_https/.xclude/validation/chrome-loopback.log`.
