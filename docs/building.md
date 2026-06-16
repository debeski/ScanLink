# Building and Releasing ScanLink

This guide covers local development, executable builds, and installer builds.

## Requirements

- Windows
- Python 3.10+
- TWAIN-compatible scanner and driver for real scan testing
- Inno Setup for installer builds
- Optional: `mkcert.exe` in the project root for trusted localhost HTTPS support

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Run from source:

```powershell
python main.py
```

Generate trusted localhost certificates and exit:

```powershell
python main.py --generate-ssl
```

## Tests

Run the test suite:

```powershell
python -m unittest discover
```

The unit tests focus on server, worker, and protocol behavior. Real scanner behavior still needs manual Windows/TWAIN verification.

## Icon Generation

Regenerate the icon assets:

```powershell
python generate_icon.py
```

This creates:

- `app_icon.png`
- `app_icon.ico`

## Executable Builds

Use `build_exe.py` to create PyInstaller one-file executables.

Build both x86 and x64 when matching Python interpreters are configured:

```powershell
python build_exe.py --arch both --python-x64 C:\Python310\python.exe --python-x86 C:\Python310-32\python.exe
```

Build only the current Python architecture:

```powershell
python build_exe.py --arch current
```

Build x86 only:

```powershell
python build_exe.py --arch x86 --python-x86 C:\Python310-32\python.exe
```

Dry run:

```powershell
python build_exe.py --arch current --dry-run
```

Outputs are written to `dist/`:

```text
dist/ScanLink_<version>_<arch>.exe
```

The version comes from the `VERSION` file.

## Optional HTTPS Support

If `mkcert.exe` exists in the project root, `build_exe.py` bundles it into the PyInstaller executable.

Without `mkcert.exe`:

- HTTP scanning still works.
- HTTPS is unavailable until certificates are provided another way.

## Installer Builds

The installer is defined in `setup.iss`.

Compile with Inno Setup:

```powershell
ISCC /DMyAppArch=x64 setup.iss
ISCC /DMyAppArch=x86 setup.iss
```

Installer outputs:

```text
ScanLinkSetup_<version>_<arch>.exe
```

The installer:

- Installs per user under `%LOCALAPPDATA%\Programs\ScanLink`.
- Registers the `scanlink://` protocol under `HKCU`.
- Optionally registers ScanLink at Windows startup under `HKCU`.
- Installs `static/scanlink.js`.
- Removes local config/log/certificate files on uninstall.

## Release Checklist

1. Update `VERSION`.
2. Update `CHANGELOG.md`.
3. Run tests.
4. Build x86 and x64 executables.
5. Compile x86 and x64 installers.
6. Install on a Windows test machine.
7. Verify tray launch, `/health`, scanner selection, scan result download, protocol launch, and uninstall cleanup.
8. Test both HTTP and HTTPS behavior when certificates are present.

## Continuous Integration and Automated Releases

GitHub Actions handles steps 3–5 automatically:

- **`.github/workflows/ci.yml`** runs on every push/PR to `main` or `beta`: it
  runs the unit tests (`python -m unittest discover -s tests`) and verifies that
  both the x86 and x64 executable **and** installer build via `build_exe.py` and
  `setup.iss`. Inno Setup is provisioned on the runner with `choco install
  innosetup`; the 32/64-bit split comes from `actions/setup-python`'s
  `architecture` matrix.
- **`.github/workflows/release.yml`** runs on a pushed `v*` tag: it verifies the
  tag equals the `VERSION` file, builds both installers, and publishes a GitHub
  Release with notes from the matching `## vX.Y.Z` `CHANGELOG.md` section. No
  secrets are required — it uses the built-in `GITHUB_TOKEN`.

To cut a release: set `VERSION` to `X.Y.Z`, add the matching `## vX.Y.Z`
`CHANGELOG.md` section, commit, then:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
```

Steps 6–8 above (real scanner / install verification) remain manual.

## Manual Verification Commands

Check health:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health
```

Start a scan:

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:5000/scan `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"doc_id":"DOC-123"}'
```

Poll status:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/scan/<job_id>
```

Download result:

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:5000/scan/<job_id>/result `
  -OutFile scan.pdf
```

Open a protocol link:

```powershell
Start-Process "scanlink://scan?docId=DOC-123"
```
