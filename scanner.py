import io
import os
import tempfile
import time

try:
    from PIL import Image as PilImage
except ImportError:
    PilImage = None

try:
    from reportlab.lib import utils as reportlab_utils
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except ImportError:
    reportlab_utils = None
    A4 = (595.2756, 841.8898)
    canvas = None

from utils import get_logger, load_config, save_config

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
            sm = twain.SourceManager(self._get_parent_window())
            return sm.source_list
        except Exception as exc:
            logger.error(f"Failed to list sources: {exc}")
            return []
        finally:
            if sm:
                try:
                    sm.close()
                except Exception:
                    pass

    def get_source_diagnostics(self):
        config = self._get_configs()
        diagnostics = {
            "twain_available": self.is_available(),
            "default_scanner": config.get("default_scanner"),
            "resolution": config.get("resolution", 240),
            "show_scanner_ui": bool(config.get("show_scanner_ui", False)),
            "sources": [],
        }

        if not twain:
            return diagnostics

        sm = None
        try:
            sm = twain.SourceManager(self._get_parent_window())
            source_names = list(sm.source_list)
            if not source_names:
                diagnostics["sources"].append(
                    {
                        "name": None,
                        "status": "no_sources",
                        "message": "No TWAIN sources detected.",
                    }
                )
                return diagnostics

            for source_name in source_names:
                source_details = {
                    "name": source_name,
                    "status": "listed",
                }
                source = None
                try:
                    source = sm.open_source(source_name)
                    if not source:
                        source_details["status"] = "cancelled"
                        source_details["message"] = "Source did not open."
                    else:
                        identity = source.identity
                        source_details["status"] = "opened"
                        source_details["identity"] = {
                            "manufacturer": identity.get("Manufacturer"),
                            "product_family": identity.get("ProductFamily"),
                            "product_name": identity.get("ProductName"),
                            "version": self._format_source_version(identity),
                            "protocol": f"{identity.get('ProtocolMajor')}.{identity.get('ProtocolMinor')}",
                        }
                except Exception as exc:
                    source_details["status"] = "error"
                    source_details["message"] = str(exc)
                finally:
                    if source:
                        try:
                            source.close()
                        except Exception:
                            pass

                diagnostics["sources"].append(source_details)
        except Exception as exc:
            diagnostics["sources"].append(
                {
                    "name": None,
                    "status": "error",
                    "message": str(exc),
                }
            )
        finally:
            if sm:
                try:
                    sm.close()
                except Exception:
                    pass

        return diagnostics

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
            parent_window = self._get_parent_window()
            logger.info("Initializing TWAIN SourceManager with parent window %s", parent_window)
            sm = twain.SourceManager(parent_window)
            logger.info("TWAIN SourceManager initialized")
            config = self._get_configs()
            sm, source = self._open_source(sm, config, progress_callback, deadline)

            self._configure_source(source, config, show_ui=bool(config.get("show_scanner_ui", False)))
            show_scanner_ui = bool(config.get("show_scanner_ui", False))
            logger.info("Scanner source UI enabled: %s", show_scanner_ui)

            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out before page acquisition could start.",
            )
            if progress_callback:
                progress_callback("acquiring")

            logger.info(f"Starting scan for request {request_id}")
            try:
                transfer_mode = self._choose_transfer_mode(source)
                logger.info("Using TWAIN transfer mode: %s", transfer_mode)

                if transfer_mode == "file":
                    self._acquire_via_file_transfer(
                        source,
                        images,
                        progress_callback,
                        deadline,
                        show_ui=show_scanner_ui,
                    )
                else:
                    self._acquire_via_native_transfer(
                        source,
                        images,
                        progress_callback,
                        deadline,
                        show_ui=show_scanner_ui,
                    )
            except Exception as exc:
                exc_name = exc.__class__.__name__
                if exc_name == "DSTransferCancelled":
                    raise ScanError(
                        "scanner_selection_cancelled",
                        "The scan was cancelled by the user.",
                        status="cancelled",
                    ) from exc
                raise ScanError(
                    "acquire_failed",
                    f"Scanner acquisition failed: {exc}",
                ) from exc

        finally:
            if source:
                try:
                    source.close()
                except Exception as exc:
                    logger.warning(f"Failed to close scanner source cleanly: {exc}")
            if sm:
                try:
                    sm.close()
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
                logger.info("Opening configured default scanner: %s", default_scanner)
                source = sm.open_source(default_scanner)
                logger.info(f"Opened default scanner: {default_scanner}")
                return sm, source
            except Exception as exc:
                logger.warning(f"Could not open default scanner '{default_scanner}': {exc}")

        logger.info("No working default scanner found; listing TWAIN sources")
        try:
            sources = list(sm.source_list)
        except Exception as exc:
            logger.warning("Could not enumerate TWAIN sources: %s", exc)
            sources = []

        self._check_deadline(
            deadline,
            code="acquire_timeout",
            message="Timed out before scanner selection could complete.",
        )
        if progress_callback:
            progress_callback("selecting_scanner", sources=sources)

        if sources:
            logger.info("Showing custom scanner selection dialog with %s source(s)", len(sources))
            selection = self._select_scanner_ui(sources)
            if not selection or not selection.get("name"):
                raise ScanError(
                    "scanner_selection_cancelled",
                    "Scanner selection was cancelled by the user.",
                    status="cancelled",
                )

            selected_name = selection["name"]
            remember_default = bool(selection.get("default"))
            logger.info(
                "Scanner dialog returned selection: %s (remember_default=%s)",
                selected_name,
                remember_default,
            )

            self._settle_gui_after_dialog()
            try:
                sm.close()
            except Exception as exc:
                logger.warning("Failed to close pre-selection TWAIN SourceManager cleanly: %s", exc)

            logger.info("Reinitializing TWAIN SourceManager after scanner selection dialog")
            sm = twain.SourceManager(self._get_parent_window())
            logger.info("Fresh TWAIN SourceManager initialized for selected scanner")
            try:
                logger.info("Opening user-selected scanner: %s", selected_name)
                source = sm.open_source(selected_name)
                logger.info("User selected scanner opened successfully: %s", selected_name)
                if remember_default:
                    config["default_scanner"] = selected_name
                    save_config(config)
                return sm, source
            except Exception as exc:
                raise ScanError(
                    "open_source_failed",
                    f"Failed to open the selected scanner '{selected_name}': {exc}",
                ) from exc

        logger.info("No source list available; falling back to TWAIN source selection dialog")
        try:
            source = sm.open_source()
        except Exception as exc:
            raise ScanError(
                "open_source_failed",
                f"Failed to open the selected scanner: {exc}",
            ) from exc

        if not source:
            raise ScanError(
                "scanner_selection_cancelled",
                "Scanner selection was cancelled by the user.",
                status="cancelled",
            )

        logger.info("TWAIN source selection dialog returned scanner: %s", getattr(source, "name", "<unknown>"))
        return sm, source

    def _select_scanner_ui(self, sources):
        from gui.dialogs import select_scanner_dialog

        return select_scanner_dialog(sources)

    def _settle_gui_after_dialog(self):
        root = self._get_parent_window()
        if hasattr(root, "update_idletasks"):
            try:
                root.update_idletasks()
                root.update()
            except Exception as exc:
                logger.warning("Failed to settle GUI event loop after dialog close: %s", exc)

    def _get_parent_window(self):
        from gui.dialogs import get_gui_root

        root = get_gui_root()
        if root is None:
            logger.warning("GUI root is not initialized; falling back to TWAIN parent window 0")
            return 0
        return root

    def _format_source_version(self, identity):
        major = identity.get("MajorNum")
        minor = identity.get("MinorNum")
        info = identity.get("Info")
        version = None
        if major is not None and minor is not None:
            version = f"{major}.{minor}"
        if info:
            return f"{version} ({info})" if version else str(info)
        return version

    def _twain_image_to_pil(self, twain_image):
        if PilImage is None:
            raise ScanError(
                "image_runtime_unavailable",
                "Image processing dependencies are not installed on this computer.",
            )

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bmp") as temp_file:
                temp_path = temp_file.name
            twain_image.save(temp_path)
            with PilImage.open(temp_path) as pil_image:
                pil_image.load()
                return pil_image.copy()
        finally:
            try:
                twain_image.close()
            except Exception:
                pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _choose_transfer_mode(self, source):
        if not twain:
            return "native"

        try:
            capability = source.get_capability(twain.ICAP_XFERMECH)
        except Exception as exc:
            logger.warning("Could not inspect TWAIN transfer mechanisms: %s", exc)
            return "native"

        mechanisms = []
        if isinstance(capability, tuple) and len(capability) == 2:
            _item_type, values = capability
            if isinstance(values, tuple) and len(values) == 3:
                mechanisms = list(values[2])
            elif isinstance(values, (list, tuple)):
                mechanisms = list(values)
            elif isinstance(values, int):
                mechanisms = [values]

        if getattr(twain, "TWSX_FILE", None) in mechanisms:
            return "file"
        if getattr(twain, "TWSX_NATIVE", None) in mechanisms:
            return "native"
        return "native"

    def _acquire_via_native_transfer(self, source, images, progress_callback, deadline, show_ui):
        def before_transfer(_image_info):
            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out while waiting for scanned pages.",
            )

        def after_transfer(twain_image, _more):
            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out while processing the scanned page.",
            )
            image = self._twain_image_to_pil(twain_image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            images.append(image)
            logger.info("Captured page %s via native transfer", len(images))
            if progress_callback:
                progress_callback("page_scanned", page_count=len(images))

        logger.info("Calling acquire_natively on scanner source")
        source.acquire_natively(
            after=after_transfer,
            before=before_transfer,
            show_ui=show_ui,
            modal=show_ui,
        )
        logger.info("acquire_natively returned control to ScanLink")

    def _acquire_via_file_transfer(self, source, images, progress_callback, deadline, show_ui):
        if PilImage is None:
            raise ScanError(
                "image_runtime_unavailable",
                "Image processing dependencies are not installed on this computer.",
            )

        pending_paths = []

        def before_transfer(_image_info):
            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out while waiting for scanned pages.",
            )
            fd, temp_path = tempfile.mkstemp(suffix=".bmp")
            os.close(fd)
            pending_paths.append(temp_path)
            return temp_path

        def after_transfer(_more):
            self._check_deadline(
                deadline,
                code="acquire_timeout",
                message="Timed out while processing the scanned page.",
            )
            temp_path = pending_paths.pop(0)
            try:
                with PilImage.open(temp_path) as pil_image:
                    pil_image.load()
                    image = pil_image.convert("RGB") if pil_image.mode != "RGB" else pil_image.copy()
                images.append(image)
                logger.info("Captured page %s via file transfer", len(images))
                if progress_callback:
                    progress_callback("page_scanned", page_count=len(images))
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

        logger.info("Calling acquire_file on scanner source")
        source.acquire_file(
            before=before_transfer,
            after=after_transfer,
            show_ui=show_ui,
            modal=show_ui,
        )
        logger.info("acquire_file returned control to ScanLink")

    def _configure_source(self, source, config, show_ui):
        try:
            resolution = float(config.get("resolution", 240))
            source.set_capability(twain.ICAP_XRESOLUTION, twain.TWTY_FIX32, resolution)
            source.set_capability(twain.ICAP_YRESOLUTION, twain.TWTY_FIX32, resolution)
            logger.info(f"Resolution set to {resolution}")
        except Exception as exc:
            logger.warning(f"Failed to set resolution: {exc}")

        if show_ui or not twain:
            return

        silent_capabilities = [
            ("CAP_FEEDERENABLED", twain.CAP_FEEDERENABLED, twain.TWTY_BOOL, True),
            ("CAP_AUTOFEED", twain.CAP_AUTOFEED, twain.TWTY_BOOL, True),
            ("CAP_INDICATORS", twain.CAP_INDICATORS, twain.TWTY_BOOL, False),
            ("CAP_XFERCOUNT", twain.CAP_XFERCOUNT, twain.TWTY_INT16, -1),
        ]

        for label, capability, type_id, value in silent_capabilities:
            try:
                source.set_capability(capability, type_id, value)
                logger.info("Configured %s=%s for silent scan", label, value)
            except Exception as exc:
                logger.warning("Could not configure %s for silent scan: %s", label, exc)

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
