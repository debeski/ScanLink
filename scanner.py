import ctypes
import io
import time

try:
    from reportlab.lib import utils as reportlab_utils
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except ImportError:
    reportlab_utils = None
    A4 = (595.2756, 841.8898)
    canvas = None

from utils import dib_to_pil, get_logger, load_config, save_config

try:
    import twain
except ImportError:
    twain = None

logger = get_logger()


class ScanError(Exception):
    def __init__(self, code, message, status="failed"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class ScannerManager:
    def __init__(self):
        self.config = load_config()

    def _get_configs(self):
        return load_config()

    def is_available(self):
        return twain is not None

    def list_sources(self):
        if not twain:
            logger.error("TWAIN module not found.")
            return []

        sm = None
        try:
            sm = twain.SourceManager(0)
            return sm.GetSourceList()
        except Exception as exc:
            logger.error(f"Failed to list sources: {exc}")
            return []
        finally:
            if sm:
                try:
                    sm.destroy()
                except Exception:
                    pass

    def scan_to_pdf(self, request_id, progress_callback=None, deadline=None):
        """
        Execute a full TWAIN scan and return a PDF buffer.
        This method is intended to run on the main GUI thread.
        """
        if not twain:
            raise ScanError("twain_unavailable", "TWAIN support is not available on this computer.")

        images = []
        sm = None
        source = None

        try:
            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out before the scanner could be opened.",
            )
            sm = twain.SourceManager(0)
            config = self._get_configs()
            source = self._open_source(sm, config, progress_callback, deadline)

            self._configure_source(source, config)

            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out before page acquisition could start.",
            )
            if progress_callback:
                progress_callback("acquiring")

            logger.info(f"Starting scan for request {request_id}")
            try:
                source.RequestAcquire(0, 1)
            except Exception as exc:
                raise ScanError(
                    "acquire_failed",
                    f"Scanner acquisition failed to start: {exc}",
                ) from exc

            while True:
                self._check_deadline(
                    deadline,
                    code="acquire_timeout",
                    message="Timed out while waiting for scanned pages.",
                )
                handle = None
                try:
                    handle, _count = source.XferImageNatively()
                except Exception:
                    break

                if not handle:
                    break

                try:
                    image = dib_to_pil(handle)
                    if image:
                        if image.mode != "RGB":
                            image = image.convert("RGB")
                        images.append(image)
                        logger.info("Captured page %s", len(images))
                        if progress_callback:
                            progress_callback("page_scanned", page_count=len(images))
                except Exception as exc:
                    logger.error(f"Image transfer error: {exc}")
                finally:
                    try:
                        ctypes.windll.gdi32.DeleteObject(handle)
                    except Exception:
                        pass

        finally:
            if source:
                try:
                    source.destroy()
                except Exception as exc:
                    logger.warning(f"Failed to close scanner source cleanly: {exc}")
            if sm:
                try:
                    sm.destroy()
                except Exception as exc:
                    logger.warning(f"Failed to destroy TWAIN source manager cleanly: {exc}")

        if not images:
            raise ScanError(
                "no_pages_scanned",
                "No pages were scanned. The scan may have been cancelled or no paper was available.",
                status="cancelled",
            )

        logger.info("Generating PDF with %s pages", len(images))
        if progress_callback:
            progress_callback("generating_pdf", page_count=len(images))

        if reportlab_utils is None or canvas is None:
            raise ScanError(
                "pdf_runtime_unavailable",
                "PDF generation dependencies are not installed on this computer.",
            )

        try:
            return self._create_pdf(images)
        except Exception as exc:
            raise ScanError("pdf_generation_failed", f"Failed to generate PDF: {exc}") from exc
        finally:
            for image in images:
                try:
                    image.close()
                except Exception:
                    pass

    def _open_source(self, sm, config, progress_callback=None, deadline=None):
        default_scanner = config.get("default_scanner")
        source = None

        if default_scanner:
            try:
                source = sm.OpenSource(default_scanner)
                logger.info(f"Opened default scanner: {default_scanner}")
                return source
            except Exception as exc:
                logger.warning(f"Could not open default scanner '{default_scanner}': {exc}")

        sources = sm.GetSourceList()
        if not sources:
            raise ScanError("no_scanners", "No TWAIN scanners are installed or available.")

        self._check_deadline(
            deadline,
            code="acquire_timeout",
            message="Timed out before scanner selection could complete.",
        )
        if progress_callback:
            progress_callback("selecting_scanner", sources=list(sources))

        selection = self._select_scanner_ui(sources)
        if not selection or not selection.get("name"):
            raise ScanError(
                "scanner_selection_cancelled",
                "Scanner selection was cancelled by the user.",
                status="cancelled",
            )

        if selection.get("default"):
            config["default_scanner"] = selection["name"]
            save_config(config)

        try:
            source = sm.OpenSource(selection["name"])
            logger.info(f"User selected scanner: {selection['name']}")
            return source
        except Exception as exc:
            raise ScanError(
                "open_source_failed",
                f"Failed to open the selected scanner '{selection['name']}': {exc}",
            ) from exc

    def _select_scanner_ui(self, sources):
        from gui.dialogs import select_scanner_dialog

        return select_scanner_dialog(sources)

    def _configure_source(self, source, config):
        try:
            resolution = float(config.get("resolution", 240))
            source.SetCapability(0x1118, twain.TWTY_FIX32, resolution)
            source.SetCapability(0x1119, twain.TWTY_FIX32, resolution)
            logger.info(f"Resolution set to {resolution}")
        except Exception as exc:
            logger.warning(f"Failed to set resolution: {exc}")

    def _check_deadline(self, deadline, code, message):
        if deadline and time.monotonic() > deadline:
            raise ScanError(code, message, status="timed_out")

    def _create_pdf(self, images):
        buffer = io.BytesIO()
        document = canvas.Canvas(buffer, pagesize=A4)
        a4_width, a4_height = A4

        for image in images:
            image_buffer = io.BytesIO()
            image.save(image_buffer, format="JPEG", quality=85, optimize=True)
            image_buffer.seek(0)

            rl_image = reportlab_utils.ImageReader(image_buffer)
            image_width, image_height = rl_image.getSize()
            aspect = image_height / float(image_width)

            draw_width = a4_width
            draw_height = a4_width * aspect

            if draw_height > a4_height:
                draw_height = a4_height
                draw_width = a4_height / aspect

            x = (a4_width - draw_width) / 2.0
            y = (a4_height - draw_height) / 2.0

            document.drawImage(rl_image, x, y, width=draw_width, height=draw_height)
            document.showPage()

        document.save()
        buffer.seek(0)
        return buffer
