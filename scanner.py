import io
import os
import ctypes
import datetime
from PIL import Image as PilImage
from reportlab.pdfgen import canvas
from reportlab.lib import utils
from reportlab.lib.pagesizes import A4

from utils import get_logger, load_config, save_config, dib_to_pil

try:
    import twain
except ImportError:
    twain = None

logger = get_logger()

class ScannerManager:
    def __init__(self):
        self.config = load_config()

    def _get_configs(self):
        """Reloads config to ensure freshness."""
        return load_config()

    def list_sources(self):
        if not twain:
            logger.error("TWAIN module not found.")
            return []
        
        sm = None
        try:
            sm = twain.SourceManager(0)
            return sm.GetSourceList()
        except Exception as e:
            logger.error(f"Failed to list sources: {e}")
            return []
        finally:
            if sm:
                sm.destroy()

    def scan_to_pdf(self, request_id, gui_executor=None):
        """
        Main scanning logic.
        gui_executor: function(callable) -> result
             Executes the callable on the Main Thread (for UI).
        """
        if not twain:
            logger.error("TWAIN module not found.")
            return None

        images = []
        
        # 1. Initialize Source Manager
        try:
            sm = twain.SourceManager(0)
        except Exception as e:
            logger.error(f"Failed to open SourceManager: {e}")
            return None

        source = None
        try:
            # 2. Open Source
            config = self._get_configs()
            default_scanner = config.get('default_scanner')
            
            if default_scanner:
                try:
                    source = sm.OpenSource(default_scanner)
                    logger.info(f"Opened default scanner: {default_scanner}")
                except Exception:
                    logger.warning(f"Could not open default scanner: {default_scanner}")
            
            # If no source yet, ask user
            if not source and gui_executor:
                sources = sm.GetSourceList()
                if sources:
                    # Request UI selection via callback
                    selection = gui_executor(lambda: self._select_scanner_ui(sources))
                    if selection and selection['name']:
                        if selection['default']:
                            config['default_scanner'] = selection['name']
                            save_config(config)
                        try:
                            source = sm.OpenSource(selection['name'])
                            logger.info(f"User selected scanner: {selection['name']}")
                        except Exception as e:
                            logger.error(f"Failed to open selected scanner: {e}")
            
            if not source:
                logger.error("No scanner source opened.")
                return None

            # 3. Configure Scanner
            self._configure_source(source, config)
            
            # 4. Acquire
            logger.info(f"Starting scan for Request ID: {request_id}")
            source.RequestAcquire(0, 1) # Hide UI (0), Show UI (1).
            
            # 5. Transfer Loop
            while True:
                handle = None
                try:
                    (handle, count) = source.XferImageNatively()
                except Exception:
                    break
                
                if handle:
                    try:
                        img = dib_to_pil(handle)
                        if img:
                            # Convert to RGB to ensure compatibility
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                            images.append(img)
                            logger.debug(f"Page captured. Total: {len(images)}")
                        
                        # IMPORTANT: Free the handle
                        ctypes.windll.gdi32.DeleteObject(handle)
                    except Exception as e:
                        logger.error(f"Image transfer error: {e}")

        except Exception as e:
            logger.error(f"Scan process error: {e}")
        finally:
            # Cleanup Source and SM
            if source:
                source.destroy()
            if sm:
                sm.destroy()

        if not images:
            return None

        # 6. Generate PDF
        logger.info(f"Generating PDF with {len(images)} pages.")
        return self._create_pdf(images)

    def _select_scanner_ui(self, sources):
        """
        This function IS NEVER CALLED DIRECTLY by ScannerManager.
        It is passed to gui_executor to be run on Main Thread.
        Imports GUI here to avoid early dependency.
        """
        from gui.dialogs import select_scanner_dialog
        return select_scanner_dialog(sources)

    def _configure_source(self, source, config):
        try:
            resolution = float(config.get('resolution', 240))
            # ICAP_XRESOLUTION, ICAP_YRESOLUTION
            source.SetCapability(0x1118, twain.TWTY_FIX32, resolution)
            source.SetCapability(0x1119, twain.TWTY_FIX32, resolution)
            logger.info(f"Resolution set to {resolution}")
        except Exception as e:
            logger.warning(f"Failed to set resolution: {e}")

    def _create_pdf(self, images):
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        a4_w, a4_h = A4

        for img in images:
            # Compress logic: Save as JPEG to memory first
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=85, optimize=True)
            img_buffer.seek(0)
            
            # ReportLab ImageReader
            rl_img = utils.ImageReader(img_buffer)
            img_w, img_h = rl_img.getSize()
            
            # Calculate aspect ratio
            aspect = img_h / float(img_w)
            
            # Determine dimensions to fit A4
            # Try fitting to width
            draw_w = a4_w
            draw_h = a4_w * aspect
            
            if draw_h > a4_h:
                # Too tall, fit to height
                draw_h = a4_h
                draw_w = a4_h / aspect
            
            # Center logic
            x = (a4_w - draw_w) / 2.0
            y = (a4_h - draw_h) / 2.0
            
            c.drawImage(rl_img, x, y, width=draw_w, height=draw_h)
            c.showPage()
            
        c.save()
        buffer.seek(0)
        return buffer
