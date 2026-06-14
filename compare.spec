# compare.spec -- PyInstaller spec for the CU Compare GUI (output oracle).
# Build on a Windows machine (one-time):  pyinstaller compare.spec
# Produces dist\CUcompare_<version>.exe -- a single double-clickable file, no
# Python needed. Version is read from compare/__init__.py (single source of
# truth). See compare/BUILD.md.
#
# This spec is INDEPENDENT of cu.spec: building the oracle never touches the
# main tool's artifacts. The oracle imports nothing from cuupdate/.

import re, os, shutil

# Read __version__ from compare/__init__.py without importing the package
# (the freezer environment may not have it importable yet).
_init = os.path.join('compare', '__init__.py')
_m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', open(_init).read(), re.M)
VERSION = _m.group(1) if _m else '0.0'
EXE_NAME = 'CUcompare_%s' % VERSION

# Build-time banner: prints to the PyInstaller console the moment the spec is
# parsed, so it is OBVIOUS which spec/version is in effect. If you build and do
# NOT see this line, PyInstaller is using a different spec (e.g. a stale
# auto-generated compare_gui.spec) -- delete that and build with
# `pyinstaller compare.spec`.
print('=' * 60)
print('  compare.spec: building %s.exe  (version %s)' % (EXE_NAME, VERSION))
print('=' * 60)

# Clean dist/ so a rebuild never leaves a stale (previous-version) exe sitting
# next to the current one. dist/ is no longer tracked (version bumps handle
# distribution), but a clean build dir still avoids shipping the wrong file.
_dist = 'dist'
if os.path.isdir(_dist):
    for _f in os.listdir(_dist):
        _p = os.path.join(_dist, _f)
        try:
            shutil.rmtree(_p) if os.path.isdir(_p) else os.remove(_p)
        except OSError:
            pass

block_cipher = None

a = Analysis(
    ['compare/compare_gui.py'],
    pathex=['compare', '.'],
    binaries=[],
    datas=[],
    # The oracle is pure stdlib; list its own modules as hiddenimports so the
    # freezer bundles them even if it misses a dynamic import. No cuupdate/
    # modules here -- the oracle is fully isolated.
    hiddenimports=['compareengine'],
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
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,          # windowed app, no console window
)
