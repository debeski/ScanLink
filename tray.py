import os
import threading
import time

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from utils import (
    APP_VERSION,
    get_logger,
    get_resource_path,
    is_ssl_available,
    is_startup_enabled,
    load_config,
    save_config,
    set_startup_enabled,
)

logger = get_logger()


def format_scanner_list_report(sources):
    if not sources:
        return "No TWAIN scanners were detected."

    lines = ["Detected TWAIN scanners:", ""]
    for index, source_name in enumerate(sources, start=1):
        lines.append(f"{index}. {source_name}")
    return "\n".join(lines)


def format_scanner_diagnostics_report(diagnostics):
    lines = [
        "ScanLink Scanner Diagnostics",
        "",
        f"TWAIN available: {'Yes' if diagnostics.get('twain_available') else 'No'}",
        f"Default scanner: {diagnostics.get('default_scanner') or 'Not set'}",
        f"Resolution: {diagnostics.get('resolution', 240)} DPI",
        f"Show scanner UI: {'Yes' if diagnostics.get('show_scanner_ui') else 'No'}",
        "",
    ]

    sources = diagnostics.get("sources") or []
    if not sources:
        lines.append("No source details available.")
        return "\n".join(lines)

    lines.append("Sources:")
    lines.append("")
    for source in sources:
        name = source.get("name") or "<unknown>"
        lines.append(f"Name: {name}")
        lines.append(f"Status: {source.get('status', 'unknown')}")
        identity = source.get("identity") or {}
        if identity:
            lines.append(f"Manufacturer: {identity.get('manufacturer') or 'Unknown'}")
            lines.append(f"Product family: {identity.get('product_family') or 'Unknown'}")
            lines.append(f"Product name: {identity.get('product_name') or name}")
            lines.append(f"Driver version: {identity.get('version') or 'Unknown'}")
            lines.append(f"TWAIN protocol: {identity.get('protocol') or 'Unknown'}")
        if source.get("message"):
            lines.append(f"Message: {source['message']}")
        lines.append("")

    return "\n".join(lines).rstrip()


class TrayApp:
    def __init__(self, worker, shutdown_event):
        self.worker = worker
        self.shutdown_event = shutdown_event
        self.icon = None

    def create_image(self):
        icon_path = get_resource_path("app_icon.ico")
        if icon_path and Image:
            try:
                return Image.open(icon_path)
            except Exception:
                logger.warning("Could not load app icon at %s, using fallback icon", icon_path)

        width = 64
        height = 64
        image = Image.new("RGB", (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=(0, 102, 204))
        return image

    def start(self):
        self.icon = Icon(
            "ScanLink",
            self.create_image(),
            f"ScanLink v{APP_VERSION}",
            self.build_menu(),
        )
        self.icon.run()

    def stop(self):
        if self.icon:
            self.icon.stop()

    def _force_exit_after_delay(self, delay_seconds=5):
        time.sleep(delay_seconds)
        if self.shutdown_event.is_set():
            logger.warning("Graceful shutdown timed out; forcing ScanLink process exit")
            os._exit(0)

    def build_menu(self):
        def show_report_dialog(title, body):
            from gui.dialogs import show_text_dialog

            return show_text_dialog(title, body)

        def set_resolution(dpi):
            def handler(icon, item):
                config = load_config()
                config["resolution"] = dpi
                save_config(config)
                if self.icon:
                    self.icon.update_menu()

            return handler

        def resolution_checked(dpi):
            return lambda item: float(load_config().get("resolution", 240)) == dpi

        def resolution_enabled(item):
            return not self.worker.is_busy()

        def on_test_scan(icon, item):
            try:
                self.worker.submit_job(source="tray")
            except Exception as exc:
                logger.warning(f"Could not start test scan from tray: {exc}")
            finally:
                if self.icon:
                    self.icon.update_menu()

        def on_list_detected_scanners(icon, item):
            try:
                sources = self.worker.run_gui_task(
                    lambda: self.worker.scanner_manager.list_sources(),
                    timeout=20,
                )
                report = format_scanner_list_report(sources)
                logger.info("Tray diagnostics - detected scanners:\n%s", report)
                self.worker.run_gui_task(
                    lambda: show_report_dialog("Detected TWAIN Scanners", report),
                    timeout=300,
                )
            except Exception as exc:
                logger.warning("Could not list detected scanners: %s", exc)

        def on_show_driver_details(icon, item):
            try:
                diagnostics = self.worker.run_gui_task(
                    lambda: self.worker.scanner_manager.get_source_diagnostics(),
                    timeout=30,
                )
                report = format_scanner_diagnostics_report(diagnostics)
                logger.info("Tray diagnostics - scanner details:\n%s", report)
                self.worker.run_gui_task(
                    lambda: show_report_dialog("Scanner Driver Details", report),
                    timeout=300,
                )
            except Exception as exc:
                logger.warning("Could not show scanner driver details: %s", exc)

        def on_quit(icon, item):
            self.shutdown_event.set()
            icon.stop()
            threading.Thread(
                target=self._force_exit_after_delay,
                daemon=True,
                name="ForceExitWatchdog",
            ).start()

        def clear_default_scanner(icon, item):
            config = load_config()
            if "default_scanner" in config:
                config.pop("default_scanner", None)
                save_config(config)
            if self.icon:
                self.icon.update_menu()

        def on_scanner_ui_toggle(icon, item):
            config = load_config()
            config["show_scanner_ui"] = not bool(config.get("show_scanner_ui", False))
            save_config(config)
            if self.icon:
                self.icon.update_menu()

        def on_startup_toggle(icon, item):
            set_startup_enabled(not is_startup_enabled())
            if self.icon:
                self.icon.update_menu()

        resolution_menu = Menu(
            MenuItem("160 DPI", set_resolution(160), checked=resolution_checked(160), radio=True, enabled=resolution_enabled),
            MenuItem("200 DPI", set_resolution(200), checked=resolution_checked(200), radio=True, enabled=resolution_enabled),
            MenuItem("240 DPI", set_resolution(240), checked=resolution_checked(240), radio=True, enabled=resolution_enabled),
            MenuItem("300 DPI", set_resolution(300), checked=resolution_checked(300), radio=True, enabled=resolution_enabled),
        )

        diagnostics_menu = Menu(
            MenuItem("List Detected Scanners", on_list_detected_scanners, enabled=lambda item: not self.worker.is_busy()),
            MenuItem("Show Driver Details", on_show_driver_details, enabled=lambda item: not self.worker.is_busy()),
        )

        return Menu(
            MenuItem(lambda item: f"ScanLink v{APP_VERSION}", None, enabled=False),
            MenuItem(lambda item: "Status: Scanning..." if self.worker.is_busy() else "Status: Idle", None, enabled=False),
            MenuItem(
                lambda item: f"Scanner: {load_config().get('default_scanner') or 'Prompt each time'}",
                None,
                enabled=False,
            ),
            MenuItem(
                lambda item: "HTTPS: Enabled" if is_ssl_available() else "HTTPS: Disabled",
                None,
                enabled=False,
            ),
            Menu.SEPARATOR,
            MenuItem("Test Scan", on_test_scan, enabled=lambda item: not self.worker.is_busy()),
            MenuItem("Resolution", resolution_menu),
            MenuItem(
                "Show Scanner UI",
                on_scanner_ui_toggle,
                checked=lambda item: bool(load_config().get("show_scanner_ui", False)),
                enabled=lambda item: not self.worker.is_busy(),
            ),
            MenuItem("Clear Default Scanner", clear_default_scanner, enabled=lambda item: not self.worker.is_busy()),
            MenuItem("Diagnostics", diagnostics_menu),
            Menu.SEPARATOR,
            MenuItem("Run on Startup", on_startup_toggle, checked=lambda item: is_startup_enabled()),
            MenuItem("Quit", on_quit),
        )
