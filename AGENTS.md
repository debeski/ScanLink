# ScanLink — project rules

ScanLink is the Windows workstation helper (tray app, TWAIN via `pytwain`, local
HTTPS server) that DjangoLux pages call through `window.DluxScan.scan()` in
`scan_button.js` — the file card and the PDF editor's Scan button.

Project state, tasks and known bugs: see `tracker.md`. These rules are
self-contained so a fresh clone, a cloud session or Codex can read them.

## Branches

- **One feature per branch, from current `main`.** Never develop on `main` or reuse
  another active feature's branch. Merge only after implementation, docs and tests
  pass.
- **Branch names are `<release line>/<work>`** in snake_case, using this repo's
  own release line: `0.8/scanner_profiles`. Its checkout directory is the last
  path segment.
- **Retire merged branches without asking.** Once a branch is merged into `main`
  and safe to discard, move its ignored leftovers (`.xclude/`, venv links, build
  output) into `.xclude/retired-worktrees/<date>/<checkout>/` of the primary
  checkout, `git worktree remove` the checkout, and delete the branch locally and
  on GitHub. Stop and ask only when something blocks it (unmerged commits, a
  conflict, uncommitted work). This overrides any personal rule asking for
  approval before each worktree removal.

## Keep in step with DjangoLux

The HTTP protocol ScanLink serves (health, scanner list, scan jobs, progress,
errors) is consumed by DjangoLux's shared ScanLink client. A change to either
side updates the other in the same release cycle: a new endpoint or field ships
in ScanLink before DjangoLux depends on it, and DjangoLux keeps handling the
previous ScanLink version until workstations have moved. Record the compatible
version pair in both trackers, and exercise the real client against the helper
(or its simulated endpoints) before a release.

## Releases

- Never tag or publish a release without the owner's OK.
- `VERSION` is the version source; the changelog and the Inno Setup installer
  follow it.

## Checks

- `python -m unittest discover -s tests -t . -v`
- `tests/windows_install_smoke.ps1` on Windows for installer changes.
