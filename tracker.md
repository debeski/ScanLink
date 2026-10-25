# ScanLink tracker

## Part 1: Project-specific
### Current Snapshot
- Published 0.7.5b1 on 2026-10-25: PR1 merged, tag/main release commit d74bf90, both Windows installers on GitHub prerelease. Stable Latest remains v0.7.4. Checkout: `app-scanlink/automatic_https`, branch `0.7/automatic_https`.
- Windows tray app uses TWAIN/pytwain; scan jobs run through child `main.py --scan-worker-dir` / `scan_runtime.py`.
- Normal startup serves HTTP :5000 while automatically provisioning trusted localhost HTTPS :5443; failed setup offers native Retry and a tray repair action.
- `certificates.py`: per-user localhost-only self-signed server identity, Windows CurrentUser Root trust, encrypted PKCS#8 key with DPAPI-protected password; hourly checks/30-day renewal and live TLS context selection.
- Paired with DjangoLux 1.15.1b1 (`1.15/scanlink_https`); REST remains compatible with older clients. New optional health field `https_setup` = preparing/ready/failed.

### Adopted Standards & Rules
- Owner decision 2026-10-25: the next ScanLink beta targets 0.8.0b1, incorporating any findings from further paired-beta/hardware stress testing. Keep published 0.7.5b1 unchanged; start follow-up implementation on a fresh 0.8 workstream from verified main.
- One patch/workstream per release-line branch; VERSION is the version source. Do not tag or publish without owner approval.
- App data/config/logs live under `%LOCALAPPDATA%\ScanLink`; identity pointer is `https/active.json`, immutable bundles `https/<id>/`, superseded identities `.xclude/https/<id>/`.
- Certificate covers only localhost/127.0.0.1/::1, CA=False/serverAuth/no certificate-signing usage; no downloaded/shared CA or machine-wide trust. Existing mkcert credentials stay untouched.
- HTTP remains supported; browser local-network permission, CSP, enterprise trust and an insecure application origin are independent restrictions.
- Never delete workspace files; relocate under `.xclude/` preserving relative paths. Match executable architecture to the TWAIN driver.

### Known Bugs & Unsolved Issues
- Windows x64/x86 unit/build/install gates passed, including real certificate consent, DPAPI/trust, 120 verified HTTPS requests per architecture and restart identity reuse. Real Windows browser/scanner and enterprise-policy acceptance remain manual.
- Target PaperStream fi-6230Z may expose only 32-bit TWAIN; live driver compliance/output quality remain unverified. Back-only and blank-page discard remain unsupported.
- Organization/browser policies may refuse user-installed trust. A denied setup is reported as failure and retried with the same identity, without repeated automatic dialogs.

### Active & Pending Tasks
- [x] Windows x64/x86 installed-app gates and normally verified HTTPS load passed before and during beta publication; stable Latest preserved.
- [ ] Verify 0.7.5b1 with target scanner hardware; preserve ADF/front/200 DPI/color/paper protection off defaults.
- [x] Paired DjangoLux 1.15.1b1 published (PR14, 3bda457); installed on testbed-dlux-ocr :8097 through Composer, rollback/reapply and published-file checks passed. Real installers are distributed there.
- [ ] Archive-hosted helper update path and detailed TWAIN capability diagnostics remain separate work.
### Completed Recently
- [x] Automatic setup/repair/renewal and plain native recovery; removed optional mkcert packaging requirement and retained `--generate-ssl` for support compatibility.
- [x] Extended installer smoke to normal Windows-trusted HTTPS and restart reuse; health timeout/fallback behavior matches the paired browser client.
- [x] Verified real TLS handshakes, hostname rejection and live identity renewal; setup failure preserves HTTP and Retry recovers HTTPS.

### Validation & Docs Log
- 2026-10-25: Windows unit/build/install CI and release40215951169 PASS; x64+x86 consent/120 HTTPS/restart PASS. Mac36 tests/1 Windows skip; published testbed UI 300 health/30 scans/20-way busy, Arabic/PDF/disconnect, installer digests and 100 manifest checks PASS. Physical TWAIN remains unverified.
- 2026-10-25: README, architecture, API, developer/build guides and CHANGELOG v0.7.5b1 describe automatic setup, protected identities, renewal, retry and compatibility.

## Part 2: Global & Handoff
### Global Helpers & Rules
- Use `rg` first. Unit wrapper: `python -m unittest discover -s tests -t . -v`; installer gate: `tests/windows_install_smoke.ps1` on Windows.
- Test stacks belong under `~/Desktop/depy/testbed-*`, use Composer `--dev` and application admin/db123123; preserve testbed-dlux.
### Agent Handoff
- Both patch checkouts are authorized by the owner from the app-mock-pdf chat; preserve that checkout's unrelated uncommitted changes.
- Beta publication/stress testing completed under owner authorization. Initial CI issues (native consent and x86 crypto source build) were fixed before tagging. No stable promotion; real scanner/browser-policy acceptance remains manual. Preserve testbed data and unrelated app-mock-pdf changes.
- Evidence: `.xclude/validation/`; paired Chrome evidence is in `pkg-django-lux/scanlink_https/.xclude/validation/chrome-loopback.log`.
