import PyInstaller.__main__
import os

# Ensure the scanner_app directory is the current context
# This script should be run from the parent directory or scanner_app folder

args = [
    'main.py',
    '--onefile',
    '--noconsole',
    '--name=ScanLink',
    '--hidden-import=gui',
]

if os.path.exists('README.md'):
    args.append('--add-data=README.md;.')

if os.path.exists('app_icon.ico'):
    args.append('--icon=app_icon.ico')

PyInstaller.__main__.run(args)
