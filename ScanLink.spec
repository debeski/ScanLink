# -*- mode: python ; coding: utf-8 -*-

import os

# Check for mkcert.exe
mkcert_path = 'mkcert.exe'
mkcert_exists = os.path.exists(mkcert_path)

# Data files to bundle
datas = [
    ('README.md', '.'),
    ('app_icon.ico', '.'),
]

# Add mkcert if it exists
if mkcert_exists:
    datas.append((mkcert_path, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'gui',
        'gui.dialogs',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'flask_socketio',
        'engineio.async_drivers.threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScanLink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
