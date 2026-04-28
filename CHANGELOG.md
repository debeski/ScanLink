# Changelog

This file owns the release history for `ScanLink`.

> Historical releases before `v0.5.0` remain documented in the version history table inside `README.md`.

## v0.5.0

- **REST-First Local API**: Standardized the helper around the `/health`, `/scan`, `/scan/<job_id>`, and `/scan/<job_id>/result` contract so browser clients can reliably poll for status and fetch finished PDFs.
- **Dual Loopback Transport**: Changed startup so ScanLink always serves HTTP on `127.0.0.1:5000` and enables HTTPS on `127.0.0.1:5443` only when trusted localhost certificates are available.
- **Single Active Job Enforcement**: Replaced silent queue stacking with explicit busy rejection, added structured terminal states (`failed`, `cancelled`, `timed_out`), and introduced result/job TTL cleanup after retrieval or expiry.
- **Single-Instance Protocol Forwarding**: Updated `scanlink://` handling so protocol launches are forwarded into the already-running tray app instead of spawning competing helper instances.
- **Tray and Installer Hardening**: Fixed tray menu boot reliability, moved the installer to per-user installation without requiring admin rights, and made trusted HTTPS generation optional instead of a critical-path requirement.
