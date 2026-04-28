import os

import PyInstaller.__main__

"""
ScanLink build script.

Prerequisite:
1. Download mkcert.exe from https://github.com/FiloSottile/mkcert/releases
   and place it in the project root before building if you want optional
   trusted localhost HTTPS support.

Usage:
    python build_exe.py

Output:
    dist/ScanLink.exe
"""

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
    "--name=ScanLink",
    "--hidden-import=gui",
    "--hidden-import=gui.dialogs",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=PIL.ImageDraw",
    "--hidden-import=protocol_handler",
]

if os.path.exists("README.md"):
    args.append("--add-data=README.md;.")

if os.path.exists("app_icon.ico"):
    args.append("--icon=app_icon.ico")
    args.append("--add-data=app_icon.ico;.")

if os.path.exists("mkcert.exe"):
    args.append("--add-data=mkcert.exe;.")
    print("mkcert.exe will be bundled for optional HTTPS certificate generation")

print("Building ScanLink.exe...")
print(f"Arguments: {' '.join(args)}")
print()

PyInstaller.__main__.run(args)

print()
print("Build complete! Output: dist/ScanLink.exe")
print()
print("Next steps:")
print("1. Compile setup.iss with Inno Setup")
print("2. Run the installer on a Windows machine")
print("3. Copy static/scanlink.js to your Django project's static folder if you are not using the shared Microsys helper")
