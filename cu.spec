# cu.spec -- PyInstaller spec for the CU update GUI launcher.
# Build on a Windows machine (one-time):  pyinstaller cu.spec
# Produces dist\CUupdate_<version>.exe -- a single double-clickable file, no
# Python needed. Version is read from cuupdate/__init__.py (single source of
# truth). See BUILD.md.

import re, os

# Read __version__ from cuupdate/__init__.py without importing the package
# (the freezer environment may not have it importable yet).
_init = os.path.join('cuupdate', '__init__.py')
_m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', open(_init).read(), re.M)
VERSION = _m.group(1) if _m else '0.0'

block_cipher = None

a = Analysis(
    ['cuupdate/cu_gui.py'],
    pathex=['cuupdate', '.'],
    binaries=[],
    datas=[],
    # Engine modules are imported normally; list as hiddenimports so the
    # freezer definitely bundles them even if it misses a dynamic import.
    hiddenimports=[
        'census', 'run_batch', 'execute', 'diffengine', 'scorer',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CUupdate_%s' % VERSION,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,          # windowed app, no console window
)
