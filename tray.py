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

    def build_menu(self):
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

        def on_quit(icon, item):
            self.shutdown_event.set()
            icon.stop()

        def clear_default_scanner(icon, item):
            config = load_config()
            if "default_scanner" in config:
                config.pop("default_scanner", None)
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
            MenuItem("Clear Default Scanner", clear_default_scanner, enabled=lambda item: not self.worker.is_busy()),
            Menu.SEPARATOR,
            MenuItem("Run on Startup", on_startup_toggle, checked=lambda item: is_startup_enabled()),
            MenuItem("Quit", on_quit),
        )
