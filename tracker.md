# ScanLink tracker

## Part 1: Project-specific
### Current Snapshot
- Patch candidate 0.7.5b1 on `0.7/automatic_https`, checkout `app-scanlink/automatic_https`; base main 4bf0c05. Latest verified tag v0.7.4. Owner authorized beta publication and testbed stress acceptance on 2026-10-25; PR/Windows gates pending.
- Windows tray app uses TWAIN/pytwain; scan jobs run through child `main.py --scan-worker-dir` / `scan_runtime.py`.
- Normal startup serves HTTP :5000 while automatically provisioning trusted localhost HTTPS :5443; failed setup offers native Retry and a tray repair action.
- `certificates.py`: per-user localhost-only self-signed server identity, Windows CurrentUser Root trust, encrypted PKCS#8 key with DPAPI-protected password; hourly checks/30-day renewal and live TLS context selection.
- Paired with DjangoLux 1.15.1b1 (`1.15/scanlink_https`); REST remains compatible with older clients. New optional health field `https_setup` = preparing/ready/failed.

### Adopted Standards & Rules
- One patch/workstream per release-line branch; VERSION is the version source. Do not tag or publish without owner approval.
- App data/config/logs live under `%LOCALAPPDATA%\ScanLink`; identity pointer is `https/active.json`, immutable bundles `https/<id>/`, superseded identities `.xclude/https/<id>/`.
- Certificate covers only localhost/127.0.0.1/::1, CA=False/serverAuth/no certificate-signing usage; no downloaded/shared CA or machine-wide trust. Existing mkcert credentials stay untouched.
- HTTP remains supported; browser local-network permission, CSP, enterprise trust and an insecure application origin are independent restrictions.
- Never delete workspace files; relocate under `.xclude/` preserving relative paths. Match executable architecture to the TWAIN driver.

### Known Bugs & Unsolved Issues
- Windows CryptoAPI/DPAPI, x86/x64 packaged startup and browser trust require real Windows acceptance; local host is macOS. CI installed-app smoke now requires normal verified HTTPS and identity reuse after restart.
- Target PaperStream fi-6230Z may expose only 32-bit TWAIN; live driver compliance/output quality remain unverified. Back-only and blank-page discard remain unsupported.
- Organization/browser policies may refuse user-installed trust. A denied setup is reported as failure and retried with the same identity, without repeated automatic dialogs.

### Active & Pending Tasks
- [ ] Run x86/x64 Windows installer smoke for 0.7.5b1; verify first launch, CurrentUser-only trust, DPAPI key, restart, policy denial and Retry with the real DjangoLux client.
- [ ] Verify 0.7.5b1 with target scanner hardware; preserve ADF/front/200 DPI/color/paper protection off defaults.
- [ ] Rebase/integrate the paired DjangoLux patch around the open 1.15 release; owner approval required for publication.
- [ ] Archive-hosted helper update path and detailed TWAIN capability diagnostics remain separate work.
### Completed Recently
- [x] Automatic setup/repair/renewal and plain native recovery; removed optional mkcert packaging requirement and retained `--generate-ssl` for support compatibility.
- [x] Extended installer smoke to normal Windows-trusted HTTPS and restart reuse; health timeout/fallback behavior matches the paired browser client.
- [x] Verified real TLS handshakes, hostname rejection and live identity renewal; setup failure preserves HTTP and Retry recovers HTTPS.

### Validation & Docs Log
- 2026-10-25: exact unittest discovery 36 tests OK/1 Windows DPAPI skip; paired JS 12 scenarios; Chrome155 HTTPS/local-HTTP fallback and insecure-LAN guidance pass; Win32 cryptography wheel resolves. Windows installer build/smoke pending (Mac build wrapper cannot use Windows Scripts/python.exe).
- 2026-10-25: README, architecture, API, developer/build guides and CHANGELOG v0.7.5b1 describe automatic setup, protected identities, renewal, retry and compatibility.

## Part 2: Global & Handoff
### Global Helpers & Rules
- Use `rg` first. Unit wrapper: `python -m unittest discover -s tests -t . -v`; installer gate: `tests/windows_install_smoke.ps1` on Windows.
- Test stacks belong under `~/Desktop/depy/testbed-*`, use Composer `--dev` and application admin/db123123; preserve testbed-dlux.
### Agent Handoff
- Both patch checkouts are authorized by the owner from the app-mock-pdf chat; preserve that checkout's unrelated uncommitted changes.
- PR1 Windows binaries built; initial installed-app gates stalled at first-launch trust. Added scoped native Yes-prompt handling and 120 verified HTTPS stress requests; rerun pending. Do not claim native/browser trust was verified on this Mac. Beta publication and testbed stress testing authorized on 2026-10-25; preserve stable releases and existing testbed data.
- Evidence: `.xclude/validation/`; paired Chrome evidence is in `pkg-django-lux/scanlink_https/.xclude/validation/chrome-loopback.log`.
