import os

import PyInstaller.__main__

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(ROOT_DIR, "VERSION")


def read_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip()
            if version:
                return version
    except OSError as exc:
        print(f"WARNING: Failed to read VERSION file at {VERSION_FILE}: {exc}")
    return "0.5.0"


APP_VERSION = read_version()

"""
ScanLink build script.

Prerequisite:
1. Download mkcert.exe from https://github.com/FiloSottile/mkcert/releases
   and place it in the project root before building if you want optional
   trusted localhost HTTPS support.

Usage:
    python build_exe.py

Output:
    dist/ScanLink-<version>.exe
"""

build_suffix = os.getenv("SCANLINK_BUILD_SUFFIX", "").strip()
if build_suffix:
    safe_suffix = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in build_suffix)
    BUILD_NAME = f"ScanLink-{APP_VERSION}-{safe_suffix}"
else:
    BUILD_NAME = f"ScanLink-{APP_VERSION}"

if not os.path.exists("mkcert.exe"):
    print("WARNING: mkcert.exe not found!")
    print("Download from: https://github.com/FiloSottile/mkcert/releases")
    print("Place mkcert-vX.X.X-windows-amd64.exe as 'mkcert.exe' in this folder.")
    print("Continuing without mkcert (HTTP scanning will still work; trusted HTTPS will be unavailable).")
    print()

args = [
    "main.py",
    "--onefile",
    "--noconsole",
    f"--name={BUILD_NAME}",
    "--clean",
    "--hidden-import=gui",
    "--hidden-import=gui.dialogs",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=PIL.ImageDraw",
    "--hidden-import=protocol_handler",
    "--hidden-import=flask",
    "--hidden-import=flask_cors",
    "--hidden-import=flask_socketio",
    "--hidden-import=socketio",
    "--hidden-import=engineio",
    "--hidden-import=engineio.async_drivers.threading",
    "--hidden-import=werkzeug",
    "--hidden-import=jinja2",
    "--hidden-import=itsdangerous",
    "--hidden-import=click",
    "--hidden-import=blinker",
    "--hidden-import=simple_websocket",
    "--hidden-import=wsproto",
    "--collect-all=flask",
    "--collect-all=flask_cors",
    "--collect-all=flask_socketio",
    "--collect-all=socketio",
    "--collect-all=engineio",
    "--collect-all=werkzeug",
    "--collect-all=jinja2",
]

if os.path.exists("README.md"):
    args.append("--add-data=README.md;.")

if os.path.exists("VERSION"):
    args.append("--add-data=VERSION;.")

if os.path.exists("app_icon.ico"):
    args.append("--icon=app_icon.ico")
    args.append("--add-data=app_icon.ico;.")

if os.path.exists("mkcert.exe"):
    args.append("--add-data=mkcert.exe;.")
    print("mkcert.exe will be bundled for optional HTTPS certificate generation")

print(f"Building {BUILD_NAME}.exe...")
print(f"Arguments: {' '.join(args)}")
print()

PyInstaller.__main__.run(args)

print()
print(f"Build complete! Output: dist/{BUILD_NAME}.exe")
print()
print("Next steps:")
print("1. Compile setup.iss with Inno Setup")
print("2. Run the installer on a Windows machine")
print("3. Copy static/scanlink.js to your Django project's static folder if you are not using the shared Microsys helper")
