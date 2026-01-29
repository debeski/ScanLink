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
