# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['entry_timer.py'],
    pathex=[],
    binaries=[],
    datas=[('ghost_icon.ico', '.')],
    hiddenimports=['pystray._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'ssl', 'hashlib', 'decimal', 'xml', 'asyncio', 'multiprocessing'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='timer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ghost_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='timer',
)
