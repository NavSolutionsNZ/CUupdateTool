# cu_batch.spec -- PyInstaller spec for the HEADLESS batch merge CLI.
# Build on Windows:  python -m PyInstaller cu_batch.spec
# Produces dist\CUbatch_<version>.exe -- a console exe that runs run_batch.py's
# CLI with no Python and no GUI. This is what the triage tool's step 4 points at
# on servers that have no Python installed.
#
# Version is read from cuupdate/__init__.py (same single source as the GUI exe,
# so the batch and GUI builds always share a version). Distinct 'CUbatch' exe
# prefix so its dist/ clean never collides with CUupdate_* / CUcompare_* /
# CUtriage_*.

import re, os, shutil

_init = os.path.join('cuupdate', '__init__.py')
_m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', open(_init).read(), re.M)
VERSION = _m.group(1) if _m else '0.0'
EXE_NAME = 'CUbatch_%s' % VERSION

print('=' * 60)
print('  cu_batch.spec: building %s.exe  (version %s)' % (EXE_NAME, VERSION))
print('=' * 60)

# Clean only THIS exe's own previous builds (prefix 'CUbatch'), so it coexists
# with every other tool's exe in a shared dist/.
_dist = 'dist'
_prefix = 'CUbatch'
if os.path.isdir(_dist):
    for _f in os.listdir(_dist):
        if not _f.startswith(_prefix):
            continue
        _p = os.path.join(_dist, _f)
        try:
            shutil.rmtree(_p) if os.path.isdir(_p) else os.remove(_p)
        except OSError:
            pass

block_cipher = None

a = Analysis(
    ['cuupdate/run_batch.py'],
    # run_batch.py uses flat imports (import execute, from diffengine import ...),
    # so cuupdate/ must be on pathex and the engine modules listed as
    # hiddenimports so the freezer bundles them all.
    pathex=['cuupdate', '.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'execute', 'diffengine', 'scorer', 'census',
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
    console=True,           # headless CLI -- console, no GUI window
)
