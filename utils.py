import os
import sys
import json
import logging
import re
import ctypes
import io
import tempfile
from logging.handlers import RotatingFileHandler

try:
    from PIL import Image as PilImage
except ImportError:
    PilImage = None

# Constants
def get_base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")


def load_app_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip()
            if version:
                return version
    except OSError:
        pass
    return "0.5.0"


APP_VERSION = load_app_version()
# Architecture of THIS ScanLink build (process pointer size), so the Archive
# update page can pick the matching x64/x86 installer to offer.
APP_ARCH = "x64" if sys.maxsize > 2 ** 32 else "x86"
LOCALAPPDATA = os.getenv('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
APP_DIR = os.path.abspath(os.path.join(LOCALAPPDATA, 'ScanLink'))
LOG_FILE = os.path.join(APP_DIR, 'scanner.log')
CONFIG_FILE = os.path.join(APP_DIR, 'config.json')
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 5000
HTTPS_PORT = 5443
DEFAULT_JOB_TTL_SECONDS = 900
DEFAULT_RESULT_TTL_SECONDS = 300
DEFAULT_SCAN_TIMEOUT_SECONDS = 600
DEFAULT_GUI_TASK_TIMEOUT_SECONDS = 900
DEFAULT_SCAN_IDLE_TIMEOUT_SECONDS = 45
DEFAULT_RESOLUTION = 200
DEFAULT_SCAN_SOURCE = "adf"
DEFAULT_SCAN_SIDE = "front"
DEFAULT_COLOR_MODE = "color"
SCAN_PROFILE_VERSION = 1
SCAN_SOURCE_OPTIONS = ("adf", "flatbed")
SCAN_SIDE_OPTIONS = ("front", "front_back")
COLOR_MODE_OPTIONS = ("color", "grayscale", "black_white")

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

def _coerce_choice(value, allowed_values, default):
    value = str(value or default).strip().lower()
    return value if value in allowed_values else default

def _apply_scan_profile_migration(config):
    config["scan_profile_version"] = SCAN_PROFILE_VERSION
    config["resolution"] = DEFAULT_RESOLUTION
    config["scan_source"] = DEFAULT_SCAN_SOURCE
    config["scan_side"] = DEFAULT_SCAN_SIDE
    config["color_mode"] = DEFAULT_COLOR_MODE
    config["paper_protection"] = False

def _normalize_config(config):
    config["scan_profile_version"] = int(config.get("scan_profile_version") or SCAN_PROFILE_VERSION)
    config["scan_source"] = _coerce_choice(config.get("scan_source"), SCAN_SOURCE_OPTIONS, DEFAULT_SCAN_SOURCE)
    config["scan_side"] = _coerce_choice(config.get("scan_side"), SCAN_SIDE_OPTIONS, DEFAULT_SCAN_SIDE)
    config["color_mode"] = _coerce_choice(config.get("color_mode"), COLOR_MODE_OPTIONS, DEFAULT_COLOR_MODE)
    config["paper_protection"] = bool(config.get("paper_protection", False))
    try:
        resolution = int(float(config.get("resolution", DEFAULT_RESOLUTION)))
        config["resolution"] = resolution if resolution > 0 else DEFAULT_RESOLUTION
    except (TypeError, ValueError):
        config["resolution"] = DEFAULT_RESOLUTION
    return config

def load_config():
    """Loads configuration with defaults."""
    defaults = {
        "scan_profile_version": SCAN_PROFILE_VERSION,
        "resolution": DEFAULT_RESOLUTION,
        "scan_source": DEFAULT_SCAN_SOURCE,
        "scan_side": DEFAULT_SCAN_SIDE,
        "color_mode": DEFAULT_COLOR_MODE,
        "default_scanner": None,
        "show_scanner_ui": False,
        "paper_protection": False,
        "cors_origins": ["*"],
        "job_ttl_seconds": DEFAULT_JOB_TTL_SECONDS,
        "result_ttl_seconds": DEFAULT_RESULT_TTL_SECONDS,
        "scan_timeout_seconds": DEFAULT_SCAN_TIMEOUT_SECONDS,
        "gui_task_timeout_seconds": DEFAULT_GUI_TASK_TIMEOUT_SECONDS,
        "scan_idle_timeout_seconds": DEFAULT_SCAN_IDLE_TIMEOUT_SECONDS,
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
                defaults.update(user_config)
                if "scan_profile_version" not in user_config:
                    _apply_scan_profile_migration(defaults)
    except Exception as e:
        get_logger().error(f"Failed to load config: {e}")
    return _normalize_config(defaults)

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
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)


# ============================================================================
# SSL/HTTPS Certificate Management
# ============================================================================
def get_ssl_context(log_errors=True):
    from certificates import LocalIdentity

    try:
        return LocalIdentity(APP_DIR).context()
    except Exception:
        if log_errors:
            get_logger().exception("ScanLink HTTPS identity is unavailable")
        return None


def is_ssl_available():
    return get_ssl_context(log_errors=False) is not None


def ensure_ssl_certificates(generate_if_missing=False):
    from certificates import LocalIdentity

    try:
        if generate_if_missing:
            LocalIdentity(APP_DIR).ensure()
        else:
            LocalIdentity(APP_DIR).context()
        return True
    except Exception:
        get_logger().exception("ScanLink could not prepare its trusted HTTPS connection")
        return False


def generate_ssl_certificates():
    return ensure_ssl_certificates(generate_if_missing=True)


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
        if PilImage is None:
            get_logger().error("Pillow is not installed; cannot convert TWAIN image data")
            return None
        img = PilImage.open(bmp_buffer)
        img.load()  # Force load pixel data
        
        return img

    except Exception as e:
        get_logger().error(f"DIB conversion error: {e}")
        return None
    finally:
        kernel32.GlobalUnlock(dib_handle)
