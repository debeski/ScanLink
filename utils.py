import os
import sys
import json
import logging
import re
import ctypes
import io
import tempfile
from logging.handlers import RotatingFileHandler
from PIL import Image as PilImage

# Constants
LOCALAPPDATA = os.getenv('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
APP_DIR = os.path.abspath(os.path.join(LOCALAPPDATA, 'ScanLink'))
LOG_FILE = os.path.join(APP_DIR, 'scanner.log')
CONFIG_FILE = os.path.join(APP_DIR, 'config.json')

# Ensure app directory exists
os.makedirs(APP_DIR, exist_ok=True)

# Windows API Constants for DIB
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

class BITMAPFILEHEADER(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bfType", ctypes.c_uint16),
        ("bfSize", ctypes.c_uint32),
        ("bfReserved1", ctypes.c_uint16),
        ("bfReserved2", ctypes.c_uint16),
        ("bfOffBits", ctypes.c_uint32),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

def setup_logging():
    """Configures rotating logging."""
    logger = logging.getLogger('ScanLink')
    logger.setLevel(logging.DEBUG)
    
    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    try:
        # Rotate logs: 5MB max, keep 5 backups
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to set up file logging: {e}")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("Logging initialized")
    return logger

def get_logger():
    return logging.getLogger('ScanLink')

def load_config():
    """Loads configuration with defaults."""
    defaults = {
        "resolution": 240,
        "default_scanner": None,
        "cors_origins": ["*"],
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
                defaults.update(user_config)
    except Exception as e:
        get_logger().error(f"Failed to load config: {e}")
    return defaults

def save_config(config):
    """Saves configuration."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        get_logger().info("Configuration saved")
    except Exception as e:
        get_logger().error(f"Failed to save config: {e}")

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


# ============================================================================
# SSL/HTTPS Certificate Management
# ============================================================================
SSL_CERT_FILE = os.path.join(APP_DIR, 'localhost.pem')
SSL_KEY_FILE = os.path.join(APP_DIR, 'localhost-key.pem')
MKCERT_EXE = 'mkcert.exe'

def get_ssl_context():
    """
    Returns SSL context if certificates exist, otherwise None.
    """
    if os.path.exists(SSL_CERT_FILE) and os.path.exists(SSL_KEY_FILE):
        try:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(SSL_CERT_FILE, SSL_KEY_FILE)
            get_logger().info("SSL context loaded successfully")
            return ctx
        except Exception as e:
            get_logger().error(f"Failed to load SSL context: {e}")
            return None
    return None

def is_ssl_available():
    """Check if SSL certificates are available."""
    return os.path.exists(SSL_CERT_FILE) and os.path.exists(SSL_KEY_FILE)

def generate_ssl_certificates():
    """
    Generates localhost SSL certificates using bundled mkcert.
    Returns True on success, False on failure.
    """
    import subprocess
    
    logger = get_logger()
    mkcert_path = get_resource_path(MKCERT_EXE)
    
    if not os.path.exists(mkcert_path):
        logger.error(f"mkcert not found at {mkcert_path}")
        return False
    
    try:
        # Install local CA (one-time, requires admin on first run)
        result = subprocess.run(
            [mkcert_path, '-install'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            logger.warning(f"mkcert -install warning: {result.stderr}")
        else:
            logger.info("mkcert CA installed successfully")
        
        # Generate certificates for localhost
        result = subprocess.run(
            [mkcert_path, '-cert-file', SSL_CERT_FILE, '-key-file', SSL_KEY_FILE,
             'localhost', '127.0.0.1', '::1'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            logger.error(f"mkcert certificate generation failed: {result.stderr}")
            return False
        
        logger.info(f"SSL certificates generated: {SSL_CERT_FILE}")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("mkcert timed out")
        return False
    except Exception as e:
        logger.error(f"SSL certificate generation failed: {e}")
        return False

def ensure_ssl_certificates():
    """
    Ensures SSL certificates exist, generating them if needed.
    Returns True if certificates are available.
    """
    if is_ssl_available():
        return True
    return generate_ssl_certificates()


# ============================================================================
# Windows Startup Registry Management
# ============================================================================
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_VALUE = "ScanLink"

def is_startup_enabled():
    """Check if ScanLink is registered to run at Windows startup."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, STARTUP_REG_VALUE)
            return True
    except FileNotFoundError:
        return False
    except Exception as e:
        get_logger().warning(f"Failed to check startup status: {e}")
        return False

def set_startup_enabled(enabled):
    """Enable or disable ScanLink startup registration."""
    try:
        import winreg
        if enabled:
            # Get the executable path
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                exe_path = os.path.abspath(sys.argv[0])
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, STARTUP_REG_VALUE, 0, winreg.REG_SZ, f'"{exe_path}"')
            get_logger().info("Startup enabled")
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, STARTUP_REG_VALUE)
                    get_logger().info("Startup disabled")
                except FileNotFoundError:
                    pass  # Already not present
        return True
    except Exception as e:
        get_logger().error(f"Failed to set startup: {e}")
        return False


def dib_to_pil(dib_handle):
    """
    Converts a TWAIN DIB handle (global memory) to a PIL Image without writing to disk.
    Constructs a BMP in memory.
    """
    if not dib_handle:
        return None

    kernel32 = ctypes.windll.kernel32
    
    # Lock global memory
    ptr = kernel32.GlobalLock(dib_handle)
    if not ptr:
        return None
        
    try:
        size = kernel32.GlobalSize(dib_handle)
        
        # Read the BITMAPINFOHEADER to calculate offsets
        bih = BITMAPINFOHEADER.from_address(ptr)
        
        # Calculate header size and palette size
        # biSize is usually 40
        header_size = bih.biSize
        
        # Determine palette size
        # If biBitCount <= 8, we likely have a palette
        palette_colors = 0
        if bih.biBitCount <= 8:
            palette_colors = (1 << bih.biBitCount) if bih.biClrUsed == 0 else bih.biClrUsed
        
        # Palette size is 4 bytes per color (RGBQUAD)
        palette_size = palette_colors * 4
        
        # Determine offset to bits
        # BMP File Header (14 bytes) + DIB Header (biSize) + Palette
        bfOffBits = 14 + header_size + palette_size
        
        # Create BITMAPFILEHEADER
        bfh = BITMAPFILEHEADER()
        bfh.bfType = 0x4D42  # 'BM'
        bfh.bfSize = 14 + size
        bfh.bfReserved1 = 0
        bfh.bfReserved2 = 0
        bfh.bfOffBits = bfOffBits
        
        # Copy DIB data from global memory
        dib_data = (ctypes.c_byte * size).from_address(ptr)
        
        # Construct full BMP in memory
        bmp_buffer = io.BytesIO()
        bmp_buffer.write(bytearray(bfh))
        bmp_buffer.write(dib_data)
        bmp_buffer.seek(0)
        
        # Load with PIL
        img = PilImage.open(bmp_buffer)
        img.load()  # Force load pixel data
        
        return img

    except Exception as e:
        get_logger().error(f"DIB conversion error: {e}")
        return None
    finally:
        kernel32.GlobalUnlock(dib_handle)
