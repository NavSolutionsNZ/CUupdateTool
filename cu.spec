# cu.spec -- PyInstaller spec for the CU update GUI launcher.
# Build on a Windows machine (one-time):  pyinstaller cu.spec
# Produces dist\CUupdate_<version>.exe -- a single double-clickable file, no
# Python needed. Version is read from cuupdate/__init__.py (single source of
# truth). See BUILD.md.

import re, os, shutil

# Read __version__ from cuupdate/__init__.py without importing the package
# (the freezer environment may not have it importable yet).
_init = os.path.join('cuupdate', '__init__.py')
_m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', open(_init).read(), re.M)
VERSION = _m.group(1) if _m else '0.0'
EXE_NAME = 'CUupdate_%s' % VERSION

# Build-time banner: this prints to the PyInstaller console the moment the spec
# is parsed, so it is OBVIOUS which spec/version is in effect. If you run a build
# and do NOT see this line, PyInstaller is using a different spec (e.g. a stale
# auto-generated CUupdate.spec from an old `--name CUupdate` run) - delete that
# and build with `pyinstaller cu.spec`.
print('=' * 60)
print('  cu.spec: building %s.exe  (version %s)' % (EXE_NAME, VERSION))
print('=' * 60)

# Clean dist/ so a rebuild never leaves a stale (e.g. unversioned or
# previous-version) exe sitting next to the current one - important for
# company-wide distribution where someone could otherwise grab the wrong file.
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
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,          # windowed app, no console window
)
