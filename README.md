# 📸 ScanLink - Scanner Bridge for Web Apps

ScanLink is a robust, lightweight system-tray application that bridges the gap between local TWAIN-compatible scanners and secured web applications. It allows web apps running in containers or remote servers to interact with physical scanning hardware connected to the client machine via a secure local API.

---

## 🔐 Key Features

- **🌐 Local Web API**  
  Exposes a secure endpoint (`http://localhost:5000/scan`) to trigger scans from any web application.
- **📄 Instant PDF Generation**  
  Automatically converts physical documents into optimized, multi-page PDFs ready for upload.
- **⚙️ Configurable Quality**  
  Adjustable resolution settings (160, 200, 240, 300 DPI) to balance quality and file size.
- **🗜️ Smart Compression**  
  Built-in JPEG compression ensures file sizes remain small (<500KB/page) without sacrificing readability.
- **🔌 Plug-and-Play**  
  Works with any TWAIN-compatible scanner (Canon, HP, Fujitsu, Epson, etc.).
- **🚀 System Tray Integration**  
  Runs silently in the background with quick access to settings and startup management.
- **🛡️ Secure Isolation**  
  Restricted to localhost access only, ensuring no external network exposure.
- **💾 Configuration Persistence**  
  Remembers your default scanner and preferred resolution settings.

---

## ⚙️ Technology Stack

- **Python 3.10+**: Core logic and runtime.
- **Flask**: Lightweight local web server for API endpoints.
- **PyTwain**: Low-level interface for TWAIN driver communication.
- **Pillow (PIL)**: Advanced image processing and compression.
- **ReportLab**: Professional PDF generation engine.
- **PyStray**: System tray icon and menu integration.
- **Tkinter**: Native GUI dialogs for scanner selection.
- **PyInstaller**: Compilation into standalone Windows executable.
- **Inno Setup**: Professional Windows installer generation.

---

## 🚀 Installation & Usage

### Method 1: Windows Installer (Recommended)
1. Download and run `ScanLinkSetup.exe`.
2. Follow the installation wizard (installs to `%LOCALAPPDATA%\ScanLink`).
3. Launch **ScanLink** from your Start Menu or Desktop.
4. The app will appear in your system tray (near the clock).

### Method 2: Portable Executable
1. Unzip the release package.
2. Run `ScanLink.exe` directly.

### Method 3: Running from Source
1. Install Python 3.10+.
2. Install dependencies: `pip install -r requirements.txt`.
3. Run the app: `python scan_app.py`.

---

## 📖 How to Use

1. **Start the App:** Ensure the ScanLink icon is visible in your system tray.
2. **Select Resolution:** Right-click the tray icon → **Resolution** → Choose your preferred quality (Default: 240 DPI).
3. **Trigger Scan:**
   - Click the **"Scan"** button in your web application.
   - Or send a POST request to `http://localhost:5000/scan`.
4. **Scanner Selection:**
   - The first time you scan, a dialog will ask you to select your scanner.
   - Check **"Set as default"** to skip this step in the future.
   - To change scanners later, right-click the tray icon → **Clear Default Scanner**.

---

## 📜 Version History

| Version | Changes |
|---------|---------|
| **v0.1.0** | • Initial release<br>• Basic TWAIN scanning support<br>• Single-page PDF generation<br>• Localhost API endpoint |
| **v0.1.4** | • Added multi-page support<br>• Implemented system tray icon<br>• Added default scanner memory<br>• startup on boot option |
| **v0.1.7** | • Added "Select Scanner" GUI dialog<br>• Improved error handling for busy scanners<br>• Added logging system |
| **v0.1.11** | • **Major Optimization:** Implemented image compression (JPEG 85%)<br>• Added resolution controls (160/200/240/300 DPI)<br>• Reduced file size by 80% (avg page < 500KB)<br>• Added Inno Setup installer script |
