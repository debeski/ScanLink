import PyInstaller.__main__
import os
import sys

"""
ScanLink Build Script

Prerequisites:
1. Download mkcert.exe from https://github.com/FiloSottile/mkcert/releases
   and place it in the project root before building.

Usage:
    python build_exe.py

Output:
    dist/ScanLink.exe
"""

# Check for required files
if not os.path.exists('mkcert.exe'):
    print("WARNING: mkcert.exe not found!")
    print("Download from: https://github.com/FiloSottile/mkcert/releases")
    print("Place mkcert-vX.X.X-windows-amd64.exe as 'mkcert.exe' in this folder.")
    print("Continuing without mkcert (SSL will not work)...")
    print()

args = [
    'main.py',
    '--onefile',
    '--noconsole',
    '--name=ScanLink',
    # Hidden imports for modules not detected by import analysis
    '--hidden-import=gui',
    '--hidden-import=gui.dialogs',
    '--hidden-import=PIL',
    '--hidden-import=PIL.Image',
    '--hidden-import=PIL.ImageDraw',
    '--hidden-import=flask_socketio',
    '--hidden-import=engineio.async_drivers.threading',
    '--hidden-import=protocol_handler',
]

# Add data files
if os.path.exists('README.md'):
    args.append('--add-data=README.md;.')

if os.path.exists('app_icon.ico'):
    args.append('--icon=app_icon.ico')
    args.append('--add-data=app_icon.ico;.')

if os.path.exists('mkcert.exe'):
    args.append('--add-data=mkcert.exe;.')
    print("✓ mkcert.exe will be bundled")

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
print("3. Copy static/scanlink.js to your Django project's static folder")
