# Project Tracker (app-ScanLink) [Max 100 lines total]

## Part 1: Project Related [Max 55 lines]
### Current Verified Snapshot: [Max 5 lines]
- Workspace: `/Users/debeski/Desktop/depy/app-ScanLink`.
- Python Windows tray app packaged with PyInstaller/Inno Setup; TWAIN scan jobs run via `worker.py` -> child `main.py --scan-worker-dir` -> `scan_runtime.py`.
- Scanner integration is `scanner.py` using `pytwain`/`twain.SourceManager`; generated PDFs are built with ReportLab from Pillow images.
- Current version file: `0.7.2`; latest local git tag seen: `v0.7.1`.

### Current Project Adopted Standards: [Max 5 lines]
- TWAIN scanning through `pytwain`; executable architecture follows the Python/PyInstaller interpreter architecture.
- Per-user config is `%LOCALAPPDATA%\ScanLink\config.json`; logs are `%LOCALAPPDATA%\ScanLink\scanner.log`.
- Releases publish by version tags; check `git tag` before editing released changelog entries.

### Adopted Standards' rules and policies: [Max 5 lines]
- Re-read and maintain this tracker at the start of every turn and after meaningful state changes.
- Never delete files/directories; move obsolete paths under `./.xpose/` preserving relative paths.
- Update root `CHANGELOG.md` immediately after implemented features/fixes/config fixes; update docs when code changes alter behavior/config/API/deployment.

### Cross-Cutting Audits if any: [Max 3 lines]
- Packaging audit: `build_exe.py` supports x86/x64 orchestration, but each build still requires matching-bitness Python.
- Scanner profile audit: v0.7.2 owns TWAIN caps for ADF/flatbed, simplex/duplex, color mode, DPI, and paper protection; it still does not create/select named PaperStream profiles.

### Current Project's Unsolved Known Bugs: [Max 5 lines]
- Needs live Windows verification: v0.7.2 requests ADF/front/200/color/paper-off, but actual PaperStream IP driver compliance must be confirmed on client PCs.
- Back-only side mode and blank-page discard remain unsupported; standard tray side modes are `front` and `front_back`.
- Prior field issue: fi-6230Z may expose only 32-bit TWAIN source; target PC reportedly lacked `C:\Windows\twain_64`.
- Archive-side context: `../project-archive/documents/forms.py` validates PDFs at 40 MB max.

### Incomplete Tasks: [Max 20 lines]
- **Priority 1:**
  - [ ] Live-test v0.7.2 on Windows with target PaperStream IP scanners and verify logs show accepted `CAP_DUPLEXENABLED=False`, ADF, 200 DPI, and color.
  - [ ] Build and install v0.7.2 x64/x86 installers on a Windows test machine.
- **Priority 2:**
  - [ ] Design Archive-hosted ScanLink update path: server manifest/artifacts plus client localhost version check or ScanLink self-update endpoint.
  - [ ] Add diagnostics logging of supported key TWAIN capabilities for selected source.
  - [ ] Re-test Windows scanner behavior with PaperStream IP after changes.
  - [ ] Test x86 build on fi-6230Z if only `twain_32` source exists.
- **Completed Recently:**
  - [x] Added v0.7.2 archive-safe defaults/migration: ADF, front-only, 200 DPI, color, paper protection off.
  - [x] Added tray controls for Source, Side, Color, Resolution, and Paper Protection.
  - [x] Applied TWAIN capability requests for feeder/autofeed, duplex enable, pixel type, optional bit depth, paper protection, indicators, and transfer count.
  - [x] Updated `VERSION`, `CHANGELOG.md`, `README.md`, `docs/architecture.md`, `docs/developer-guide.md`, and `docs/api.md`.
  - [x] Investigated ScanLink profile/settings behavior after archive file-size report on 2026-07-08.

### One-line info about last verified Tests: [Max 5 lines]
- 2026-07-08: `python3 -m unittest discover -s tests` passed 16 tests, 5 skipped; `python3 -m compileall scanner.py tray.py utils.py tests/test_scanner_profile.py` passed.
- 2026-07-08: plain `python3 -m unittest discover` found 0 tests due repo layout; use `-s tests`.
- 2026-07-08 limitation: local environment lacks `twain` and Windows scanner hardware, so live PaperStream verification was not run.
- Prior checks: `python -m compileall build_exe.py`, `python build_exe.py --help`, and build dry-runs passed on 2026-04-29; Inno compile not available in local environment.

### One-line info about last time edited Docs: [Max 2 lines]
- 2026-07-08: Updated scanner profile docs in `README.md`, `docs/architecture.md`, `docs/developer-guide.md`, `docs/api.md`; changelog entry `v0.7.2`.

## Part 2: Global [Max 20 lines]
### Global Standard Helpers, Shortcuts, Info, etc.:
- Use `rg`/`rg --files` first for repository discovery.
- TWAIN paths on 64-bit Windows: 64-bit DSM `C:\Windows\System32\TWAINDSM.DLL`; 32-bit DSM `C:\Windows\SysWOW64\TWAINDSM.DLL`; data sources usually `C:\Windows\twain_32`/`twain_64`.

### Global Rulesets:
- Keep tracker facts grounded in verified code, verified runtime behavior, or explicit user correction.
- Do not mix reusable/global guidance into project-specific sections.

### Agent Handoff Rules:
- Re-read `tracker.md` at the start of every turn.
- Update `tracker.md` after meaningful changes to bugs, tasks, tests, docs, standards interpretation, or handoff guidance.

### References and Links:
- Related archive project: `/Users/debeski/Desktop/depy/project-archive`.
