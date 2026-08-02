# 📸 ScanLink - Scanner Bridge for Web Apps

ScanLink is a robust, lightweight system-tray application that bridges the gap between local TWAIN-compatible scanners and secured web applications. It allows web apps running in containers or remote servers to interact with physical scanning hardware connected to the client machine via a secure local API.

---

## 🔐 Key Features

- **🔒 Secure HTTPS API**  
  Exposes a secure endpoint (`https://localhost:5443/scan`) with auto-generated SSL certificates.
- **🔗 Deep Link Support**  
  Trigger scans directly from browser links using `scanlink://scan?docId=123`.
- **📡 Polling-Friendly Status API**  
  Track scan status, page count, completion, and errors through REST endpoints.
- **📄 Instant PDF Generation**  
  Automatically converts physical documents into optimized, multi-page PDFs ready for upload.
- **⚙️ Configurable Quality**  
  Adjustable source, side, color, and resolution settings to balance quality and file size.
- **🗜️ Smart Compression**  
  Built-in JPEG compression ensures file sizes remain small (<500KB/page) without sacrificing readability.
- **🔌 Plug-and-Play**  
  Works with any TWAIN-compatible scanner (Canon, HP, Fujitsu, Epson, etc.).
- **🚀 System Tray Integration**  
  Runs silently in the background with quick access to settings and startup management.
- **🛡️ Secure Isolation**  
  Restricted to localhost access only, ensuring no external network exposure.
- **💾 Configuration Persistence**  
  Remembers your default scanner and scan profile settings.

---

## ⚙️ Technology Stack

- **Python 3.10+**: Core logic and runtime.
- **Flask**: Local REST API server for scan requests, status polling, and PDF retrieval.
- **PyTwain**: Low-level interface for TWAIN driver communication.
- **Pillow (PIL)**: Advanced image processing and compression.
- **ReportLab**: Professional PDF generation engine.
- **PyStray**: System tray icon and menu integration.
- **Tkinter**: Native GUI dialogs for scanner selection.
- **mkcert**: Auto-generates trusted localhost SSL certificates.
- **PyInstaller**: Compilation into standalone Windows executable.
- **Inno Setup**: Professional Windows installer generation.

---

## 🚀 Installation & Usage

### Method 1: Windows Installer (Recommended)
1. Download and run `ScanLinkSetup.exe`.
2. Follow the installation wizard (installs to `Program Files (x86)\ScanLink`).
3. Launch **ScanLink** from your Start Menu or Desktop.
4. The app will appear in your system tray (near the clock).

### Method 2: Portable Executable
1. Unzip the release package.
2. Run `ScanLink.exe` directly.

### Method 3: Running from Source
1. Install Python 3.10+.
2. Install dependencies: `pip install -r requirements.txt`.
3. Run the app: `python main.py`.

---

## 📖 How to Use

1. **Start the App:** Ensure the ScanLink icon is visible in your system tray.
2. **Confirm Scan Profile:** Right-click the tray icon and confirm the archive-safe defaults: **Source → ADF**, **Side → Front**, **Color → Color**, **Resolution → 200 DPI**, and **Paper Protection** unchecked.
3. **Trigger Scan:**
   - Click the **"Scan"** button in your web application.
   - Or send a POST request to `https://localhost:5443/scan`.
   - Or use a deep link: `<a href="scanlink://scan?docId=123">Scan</a>`
4. **Scanner Selection:**
   - The first time you scan, a dialog will ask you to select your scanner.
   - Check **"Set as default"** to skip this step in the future.
   - To change scanners later, right-click the tray icon → **Clear Default Scanner**.
5. **Status Updates:**
   - Poll the job status endpoint or use `static/scanlink.js` for status tracking.
   - Microsys already ships the shared ScanLink helper.

---

## 👩‍💻 Developer Integration

ScanLink exposes a local REST API for browser apps:

- `GET http://127.0.0.1:5000/health`
- `POST http://127.0.0.1:5000/scan`
- `GET http://127.0.0.1:5000/scan/<job_id>`
- `GET http://127.0.0.1:5000/scan/<job_id>/result`

HTTPS is also available at `https://127.0.0.1:5443` when trusted localhost certificates exist.

Minimal browser flow:

```js
const scanLink = new ScanLink();
const job = await scanLink.startScan({ docId: "DOC-123" });
const pdfBlob = await scanLink.waitForResult(job.job_id);
```

Developer docs:

- [Developer Guide](docs/developer-guide.md): frontend flow, deep links, callbacks, and operational notes.
- [API Reference](docs/api.md): endpoint contracts, status payloads, and error codes.
- [Architecture](docs/architecture.md): how the app is wired internally.
- [Building and Release](docs/building.md): local development, PyInstaller builds, and installer packaging.

---

## 📜 Version History

See [`CHANGELOG.md`](CHANGELOG.md) for the full release history.
