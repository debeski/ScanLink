import os
import sys
import threading
import io
import time
import logging
import json
import tkinter as tk
from tkinter import simpledialog, messagebox
from flask import Flask, send_file, jsonify
from flask_cors import CORS
from PIL import Image
try:
    import twain
except ImportError:
    twain = None
from reportlab.pdfgen import canvas
from reportlab.lib import utils
from reportlab.lib.pagesizes import A4
from pystray import Icon, Menu, MenuItem
from PIL import Image as PilImage, ImageDraw
import ctypes

# Configure logging
# Ensure we get the absolute path to avoid writing to system32
localappdata = os.getenv('LOCALAPPDATA')
if not localappdata:
    # Fallback if LOCALAPPDATA is not set
    localappdata = os.path.expanduser('~\\AppData\\Local')

app_dir = os.path.abspath(os.path.join(localappdata, 'ScanLink'))
os.makedirs(app_dir, exist_ok=True)
log_dir = app_dir
log_file = os.path.abspath(os.path.join(log_dir, 'scanner.log'))
config_file = os.path.join(app_dir, 'config.json')

# Configure logging with error handling
try:
    logging.basicConfig(
        filename=log_file,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info(f"Logging initialized to: {log_file}")
except Exception as e:
    # Fallback to console logging if file logging fails
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.error(f"Failed to initialize file logging to {log_file}: {e}")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

def load_config():
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load config: {e}")
    return {}

def save_config(config):
    try:
        with open(config_file, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")

def select_scanner_dialog(sources):
    """
    Shows a custom TopMost dialog to select a scanner.
    Returns (selected_source_name, is_default_checked) or (None, False)
    """
    selection = {'name': None, 'default': False}
    
    def on_select():
        try:
            cur = listbox.curselection()
            if cur:
                selection['name'] = sources[cur[0]]
                selection['default'] = var_default.get()
                root.quit()
            else:
                messagebox.showwarning("Warning", "Please select a scanner.", parent=root)
        except Exception as e:
            logging.error(f"Selection error: {e}")

    def on_cancel():
        root.quit()

    try:
        root = tk.Tk()
        root.title("Select Scanner")
        
        # Bring to front and force focus
        root.attributes('-topmost', True)
        root.focus_force()
        
        # Center the window
        width = 400
        height = 350
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        root.geometry(f'{width}x{height}+{x}+{y}')

        lbl = tk.Label(root, text="Choose your scanner:")
        lbl.pack(pady=10)

        listbox = tk.Listbox(root, selectmode=tk.SINGLE)
        for s in sources:
            listbox.insert(tk.END, s)
        listbox.pack(expand=True, fill=tk.BOTH, padx=20)
        
        # Select first item by default
        if sources:
            listbox.selection_set(0)

        var_default = tk.BooleanVar()
        chk = tk.Checkbutton(root, text="Set as default scanner", variable=var_default)
        chk.pack(pady=10)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="Select", command=on_select, width=10).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=on_cancel, width=10).pack(side=tk.LEFT, padx=10)

        root.mainloop()
        root.destroy()
        
        return selection['name'], selection['default']
    except Exception as e:
        logging.error(f"Dialog error: {e}")
        return None, False

def scan_to_pdf():
    """
    Actual TWAIN scanning logic.
    Returns: BytesIO object containing the PDF, or None on failure.
    """
    if not twain:
        logging.error("Twain module not imported")
        return None

    try:
        sm = twain.SourceManager(0)
        
        # Check for default scanner
        config = load_config()
        default_scanner = config.get('default_scanner')
        ss = None
        
        if default_scanner:
            try:
                # Attempt to open default
                logging.info(f"Opening default scanner: {default_scanner}")
                ss = sm.OpenSource(default_scanner)
            except Exception as e:
                logging.warning(f"Failed to open default scanner {default_scanner}: {e}")
                ss = None

        if not ss:
            # Get list of sources
            sources = sm.GetSourceList()
            if not sources:
                logging.error("No TWAIN sources found")
                return None
            
            # Show custom dialog
            selected_name, set_default = select_scanner_dialog(sources)
            
            if not selected_name:
                logging.info("User cancelled scanner selection")
                return None
            
            if set_default:
                config['default_scanner'] = selected_name
                save_config(config)
            
            ss = sm.OpenSource(selected_name)
        
        if not ss:
            logging.error("Could not open source")
            return None

        # Configure scanner settings for lower resolution and smaller file size
        try:
            # Set resolution based on config
            resolution = float(config.get('resolution', 240))
            
            # TWAIN capability codes: ICAP_XRESOLUTION = 0x1118, ICAP_YRESOLUTION = 0x1119
            ss.SetCapability(0x1118, twain.TWTY_FIX32, resolution)  # X Resolution
            ss.SetCapability(0x1119, twain.TWTY_FIX32, resolution)  # Y Resolution
            logging.info(f"Scanner resolution set to {resolution} DPI")
        except Exception as e:
            logging.warning(f"Could not set resolution: {e}. Using scanner defaults.")

        # Request Acquire
        ss.RequestAcquire(0, 1) 
        
        images = []
        
        while True:
            handle = None
            try:
                (handle, count) = ss.XferImageNatively()
            except Exception as e:
                # Break if no more images or user cancelled
                break
            
            if handle:
                try:
                    # Convert DIB handle to BMP in memory
                    import ctypes
                    import tempfile
                    
                    with tempfile.NamedTemporaryFile(suffix='.bmp', delete=False) as tmp:
                        tmp_name = tmp.name
                    
                    try:
                        twain.DIBToBMFile(handle, tmp_name)
                        img = PilImage.open(tmp_name)
                        img.load() # Force load so we can close file
                        
                        # Convert to RGB for better compression
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        images.append(img)
                    except Exception as e:
                        logging.error(f"DIB conversion failed: {e}")
                    finally:
                        if os.path.exists(tmp_name):
                            os.remove(tmp_name)
                    
                    # You MUST free the handle
                    ctypes.windll.gdi32.DeleteObject(handle)
                    
                except Exception as img_e:
                    logging.error(f"Error processing image handle: {img_e}")
            
    
    except Exception as e:
        logging.error(f"TWAIN Error: {e}")
        return None
    finally:
        # Cleanup
        pass

    if not images:
        return None

    # Save logic with compression
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for img in images:
        # Compress image before adding to PDF
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='JPEG', quality=85, optimize=True)
        img_buffer.seek(0)
        
        # Draw compressed image on PDF canvas
        c.drawImage(utils.ImageReader(img_buffer), 0, 0, width=A4[0], height=A4[1]) 
        c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "Scanner app is running"})

@app.route('/scan', methods=['POST', 'GET'])
def trigger_scan():
    try:
        # Attempt scan
        pdf_buffer = scan_to_pdf()
        
        # Strict Check: If no buffer, it failed or cancelled.
        if not pdf_buffer:
             return jsonify({"error": "Scan cancelled or failed"}), 500
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name='scanned_document.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logging.error(f"Scan route error: {e}")
        return jsonify({"error": str(e)}), 500

def run_flask():
    app.run(port=5000, debug=False, use_reloader=False)

def create_tray_icon():
    icon_path = 'app_icon.ico'
    if os.path.exists(icon_path):
         image = PilImage.open(icon_path)
    else:
         width = 64
         height = 64
         image = PilImage.new('RGB', (width, height), color=(255, 255, 255))
         dc = ImageDraw.Draw(image)
         dc.rectangle((width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=(0, 0, 255))
    
    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    import winreg

    def is_startup_enabled(item):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "ScanLink")
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    def toggle_startup(icon, item):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
            if is_startup_enabled(item):
                try:
                    winreg.DeleteValue(key, "ScanLink")
                except FileNotFoundError:
                    pass
            else:
                exe_path = sys.executable
                if not getattr(sys, 'frozen', False):
                    # If running as script, use python.exe and script path
                    # But for reliable startup, we usually expect frozen exe.
                    # We will try best effort for script.
                    exe_path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
                
                winreg.SetValueEx(key, "ScanLink", 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
        except Exception as e:
            logging.error(f"Startup toggle failed: {e}")

    def show_about(icon, item):
        def run_box():
            title = "ScanLink"
            message = (
                "برنامج لتشغيل الماسح الضوئي مع تطبيق الارشيف الالكتروني\n"
                "الإصدار 0.1.11\n\n"
                "© 2026 مركز المعلومات والتوثيق الاقتصادي"
            )
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x00080000)
        threading.Thread(target=run_box, daemon=True).start()

    def clear_default_scanner(icon, item):
        def run_confirm():
            # MB_YESNO | MB_ICONQUESTION | MB_RTL
            resp = ctypes.windll.user32.MessageBoxW(0, "Are you sure you want to clear the default scanner?", "Clear Default", 0x04 | 0x20 | 0x00080000)
            if resp == 6: # IDYES
                config = load_config()
                if 'default_scanner' in config:
                    del config['default_scanner']
                    save_config(config)
                    ctypes.windll.user32.MessageBoxW(0, "Default scanner cleared.", "ScanLink", 0x40)
        
        threading.Thread(target=run_confirm, daemon=True).start()

    def set_resolution(res):
        def wrapper(icon, item):
            config = load_config()
            config['resolution'] = res
            save_config(config)
        return wrapper

    def is_resolution_checked(res):
        def wrapper(item):
            config = load_config()
            current = config.get('resolution', 240)
            return current == res
        return wrapper

    res_menu = Menu(
        MenuItem('160 DPI', set_resolution(160), checked=is_resolution_checked(160), radio=True),
        MenuItem('200 DPI', set_resolution(200), checked=is_resolution_checked(200), radio=True),
        MenuItem('240 DPI (Default)', set_resolution(240), checked=is_resolution_checked(240), radio=True),
        MenuItem('300 DPI', set_resolution(300), checked=is_resolution_checked(300), radio=True)
    )

    menu = Menu(
        MenuItem('Run on startup', toggle_startup, checked=is_startup_enabled),
        MenuItem('Resolution', res_menu),
        MenuItem('Clear Default Scanner', clear_default_scanner),
        MenuItem('About', show_about),
        MenuItem('Quit', quit_app)
    )

    icon = Icon("ScanLink", image, "ScanLink", menu)
    return icon

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    icon = create_tray_icon()
    icon.run()
