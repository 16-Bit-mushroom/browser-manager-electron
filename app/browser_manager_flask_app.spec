# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[], # Ensure pathex is either removed or explicitly empty if not needed, as discussed earlier
    binaries=[],
    datas=[ # <--- Your datas are now defined directly here
        ('static', 'static'),
        ('templates', 'templates'),
        ('data', 'data') # This includes profiles.db, browser_binaries, and profiles folders
    ],
    hiddenimports=['jinja2'], # <--- Added 'jinja2' as recommended previously
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# The 'a.datas +=' section below is now removed/commented out
# as datas are defined directly in Analysis.

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas, # This still correctly refers to the datas defined in Analysis
    [],
    name='browser_manager_flask_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas, # This still correctly refers to the datas defined in Analysis
    strip=False,
    upx=True,
    upx_exclude=[],
    name='browser_manager_flask_app',
)