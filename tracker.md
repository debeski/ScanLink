# Project Tracker

## Part 1: Project
### Current Verified Snapshot and current project overview:
Workspace: `/home/debeski/depy/projects/scanlink-app`.
- Python desktop/tray app packaged with PyInstaller and Inno Setup.
- Scanner integration is in `scanner.py` using `pytwain`/`twain.SourceManager`.
- Scan jobs run through the same packaged executable as a subprocess via `worker.py` -> `--scan-worker-dir` -> `scan_runtime.py`.

### Current Project Official Standards:
- TWAIN scanning through `pytwain`; executable architecture is determined by the Python/PyInstaller environment used at build time.

### Standards' rules and policies:
Follow explicit user instruction: re-read and maintain this tracker at the start of every turn and after meaningful project state changes.

### Cross-Cutting Audits if any:
- Packaging audit: `ScanLink.spec` has `target_arch=None`. `build_exe.py` now exposes architecture-aware build orchestration, but each target still follows the architecture of the Python executable used for that target.

### Current Project's Known Bugs:
- Scanner detection issue reported by user: app works on Windows 11 with a modern Fujitsu/Ricoh fi-7420 over TWAIN, but fails to list an older Fujitsu fi-6230Z on the target client's Windows 11 PC. Third-party apps ScanAll PRO and PaperStream Capture can see and use the fi-6230Z on that upgraded Windows 11 installation.
- Likely root cause to validate: target installation may expose only a 32-bit TWAIN data source for fi-6230Z, while ScanLink is likely built/running as a 64-bit process. A 64-bit TWAIN application cannot enumerate/load 32-bit TWAIN data sources.
- Clarification from Ricoh/PFU references: scanner hardware is not inherently "32-bit" or "64-bit"; the installed TWAIN/PaperStream data source is. Ricoh FAQ says use PaperStream IP (TWAIN) for 32-bit applications and PaperStream IP (TWAIN x64) for 64-bit applications.
- User field observation: target client PC does not have `C:\Windows\twain_64` at all. This strongly supports the conclusion that no 64-bit TWAIN source is installed for the scanner on that PC.

### Tasks:
- Priority 1:
  - [x] Inspect project build/runtime architecture and scanner integration path.
  - [x] Determine whether the app currently ships/runs as 64-bit only or has a 32-bit option.
  - [x] Identify practical remediation options for 32-bit-only TWAIN sources on Windows.
  - [x] Update tracker with verified findings and recommended validation steps.

- Recommended follow-up:
  - [ ] On a Windows machine, verify the built `ScanLink.exe` architecture.
  - [x] On the target client PC, verify whether `C:\Windows\twain_64` contains a fi-6230Z/PaperStream x64 `.ds` source. User reports `C:\Windows\twain_64` does not exist.
  - [ ] Test a ScanLink build made with 32-bit Python if only `C:\Windows\twain_32` contains the scanner source.
  - [ ] If 32-bit build is validated, document separate x86/x64 release packaging strategy or build a 32-bit scan helper process.
  - [ ] If distributing both full-app builds, update installer packaging because `setup.iss` currently expects `dist\ScanLink-{version}.exe` and does not parameterize x86/x64 suffixes.

- Completed Recently:
  - [x] Updated `build_exe.py` to support `--arch both|x64|x86|current`.
  - [x] Updated build output names to `ScanLink_{version}_x64.exe` and `ScanLink_{version}_x86.exe`.
  - [x] Added `--python-x64` / `--python-x86` and `SCANLINK_PYTHON_X64` / `SCANLINK_PYTHON_X86` support so one build command can orchestrate both architectures when both interpreter paths are available.
  - [x] Added preflight validation that the selected Python executable matches the requested architecture before running PyInstaller.
  - [x] Updated `setup.iss` to accept `MyAppArch` (`x64` default, or `x86`) and consume `dist\ScanLink_{version}_{arch}.exe`.
  - [x] Updated installer output naming to `ScanLinkSetup_{version}_{arch}.exe`.

### Tests:
Verified checks:
- Read `scanner.py`: `ScannerManager.list_sources()` and diagnostics instantiate `twain.SourceManager`; no custom cross-bitness bridge exists.
- Read `worker.py` and `scan_runtime.py`: scan subprocess is the same Python executable/app, so it has the same bitness as the packaged app.
- Read `ScanLink.spec` and `build_exe.py`: `ScanLink.spec` remains architecture-neutral; `build_exe.py` now chooses x86/x64 build names and interpreter paths, while PyInstaller output still follows the selected interpreter architecture.
- Checked official/public references on 2026-04-29: TWAIN DSM has separate 32-bit/64-bit DLLs and source directories; Ricoh pages list fi-6230Z TWAIN/PaperStream support pages mostly as archived and up to Windows 10 for PaperStream IP.
- 2026-04-29: Ran `python -m compileall build_exe.py`.
- 2026-04-29: Ran `python build_exe.py --help`.
- 2026-04-29: Ran `python build_exe.py --arch current --dry-run`; generated `ScanLink_0.6.1_x64` command on the current x64 interpreter.
- 2026-04-29: Ran `python build_exe.py --arch x86 --dry-run` without an x86 Python path; verified it fails clearly and asks for `--python-x86` or `SCANLINK_PYTHON_X86`.
- 2026-04-29: Checked for `iscc`; Inno Setup compiler is not installed in this Linux environment, so `setup.iss` compile validation must be done on Windows.

Suggested future checks:
- Verify app bitness on target machine.
- Verify whether the fi-6230Z exposes a 32-bit TWAIN source only.
- Verify whether a 32-bit build of the app can enumerate the scanner on the target PC.

### Docs:
- User supplied operational scanner context in chat on 2026-04-29.
- Useful TWAIN paths on 64-bit Windows:
  - `C:\Windows\System32\TWAINDSM.DLL` is the 64-bit DSM location.
  - `C:\Windows\SysWOW64\TWAINDSM.DLL` is the 32-bit DSM location.
  - TWAIN data sources are typically under `C:\Windows\twain_32` or `C:\Windows\twain_64` as `.ds` files.
- Ricoh/PFU official pages found:
  - fi-6230Z TWAIN32 driver page: `https://www.pfu.ricoh.com/global/scanners/fi/support/software/v1021310-sca.html`
  - PaperStream IP TWAIN x64 page: `https://www.pfu.ricoh.com/global/scanners/fi/support/software/fi6x30-fi6x40-ps-ip-twain64.html`
  - PaperStream IP TWAIN page: `https://www.pfu.ricoh.com/global/scanners/fi/support/software/fi6x30-fi6x40-ps-ip-twain32.html`
  - Ricoh FAQ: `https://fi-faq.pfu.ricoh.com/hc/en-us/articles/13322763972121`
  - fi-7240 product page lists Software/Drivers as `PaperStream IP Driver (TWAIN/TWAIN x64/ISIS)`: `https://www.pfu.ricoh.com/global/scanners/fi/fi7240/`
- Build compatibility note: PyInstaller cannot turn a 64-bit Python environment into a 32-bit Windows executable for this app. Build x64 from a 64-bit Python venv and x86 from a 32-bit Python venv. `build_exe.py` names outputs like `ScanLink_{version}_x64.exe` and `ScanLink_{version}_x86.exe`; `setup.iss` still needs adjustment for those suffixed installer inputs.
- Build script usage after 2026-04-29 update:
  - `python build_exe.py` defaults to `--arch both`.
  - `python build_exe.py --arch x64` builds only x64.
  - `python build_exe.py --arch x86 --python-x86 C:\Path\To\32bit\python.exe` builds only x86.
  - `python build_exe.py --arch both --python-x64 C:\Path\To\64bit\python.exe --python-x86 C:\Path\To\32bit\python.exe` builds both.
- Installer script usage after 2026-04-29 update:
  - `iscc setup.iss` defaults to x64 and expects `dist\ScanLink_{version}_x64.exe`.
  - `iscc /DMyAppArch=x64 setup.iss` builds `ScanLinkSetup_{version}_x64.exe`.
  - `iscc /DMyAppArch=x86 setup.iss` builds `ScanLinkSetup_{version}_x86.exe`.

## Part 2: Global
### Global Standard Helpers, Shortcuts, Info, etc.:
- Use `rg`/`rg --files` first for repository discovery when available.

### Global Ruleset:
- Keep tracker grounded in verified code, verified runtime behavior, or explicit user instruction.
- Do not mix project-specific facts into the global section unless broadly reusable.

### Agent Handoff Rules:
- Re-read `tracker.md` at the start of every turn.
- Update `tracker.md` after meaningful changes to project state, tasks, tests, docs, standards interpretation, or handoff guidance.

### Links To Possibly Helpful Tools and Projects if any:
- `/home/debeski/depy/tools/DNgine/tracker.md`
- `/home/debeski/depy/projects/archive/tracker.md`

### References:
- None yet.
