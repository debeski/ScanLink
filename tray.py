from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw
import threading
import os
import sys
from utils import load_config, save_config, get_logger, get_version_from_readme, get_resource_path

logger = get_logger()

class TrayApp:
    def __init__(self, worker, shutdown_event):
        self.worker = worker
        self.shutdown_event = shutdown_event
        self.icon = None

    def create_image(self):
        icon_path = get_resource_path('app_icon.ico')
        if os.path.exists(icon_path):
            return Image.open(icon_path)
        else:
            logger.warning(f"Icon not found at {icon_path}, using default.")
            width = 64
            height = 64
            image = Image.new('RGB', (width, height), color=(255, 255, 255))
            dc = ImageDraw.Draw(image)
            dc.rectangle((width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=(0, 0, 255))
            return image

    def start(self):
        self.icon = Icon("ScanLink", self.create_image(), "ScanLink", self.build_menu)
        self.icon.run()

    def stop(self):
        if self.icon:
            self.icon.stop()

    def build_menu(self, icon):
        config = load_config()
        current_res = float(config.get('resolution', 240))
        default_scanner = config.get('default_scanner', 'None')
        version = get_version_from_readme(get_resource_path('README.md'))
        is_busy = self.worker.is_busy()

        status_text = "Status: Scanning..." if is_busy else "Status: Idle"
        scanner_text = f"Scanner: {default_scanner}"

        # Resolution setters
        def set_res(r):
            def inner(icon, item):
                c = load_config()
                c['resolution'] = r
                save_config(c)
            return inner

        def is_res(r):
            def inner(item):
                 return float(load_config().get('resolution', 240)) == r
            return inner

        # Disable resolution if busy
        res_enabled = not is_busy

        resolution_menu = Menu(
            MenuItem('160 DPI', set_res(160), checked=is_res(160), radio=True, enabled=res_enabled),
            MenuItem('200 DPI', set_res(200), checked=is_res(200), radio=True, enabled=res_enabled),
            MenuItem('240 DPI', set_res(240), checked=is_res(240), radio=True, enabled=res_enabled),
            MenuItem('300 DPI', set_res(300), checked=is_res(300), radio=True, enabled=res_enabled)
        )

        def on_test_scan(icon, item):
            self.worker.submit_job()

        def on_quit(icon, item):
            self.shutdown_event.set()
            icon.stop()

        def clear_default(icon, item):
             c = load_config()
             if 'default_scanner' in c:
                 del c['default_scanner']
                 save_config(c)

        return Menu(
            MenuItem(f"ScanLink v{version}", None, enabled=False),
            MenuItem(status_text, None, enabled=False),
            MenuItem(scanner_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem('Test Scan (1 Page)', on_test_scan, enabled=not is_busy),
            MenuItem('Resolution', resolution_menu),
            MenuItem('Clear Default Scanner', clear_default, enabled=not is_busy),
            Menu.SEPARATOR,
            MenuItem('Quit', on_quit)
        )
