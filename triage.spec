# triage.spec -- PyInstaller spec for the CU Triage GUI (vendor-delta triage).
# Build on Windows:  python -m PyInstaller triage.spec
# Produces dist\CUtriage_<version>.exe -- a single double-clickable file.
# Version is read from triage/__init__.py. See triage/BUILD.md.
#
# Independent of cu.spec and compare.spec; scopes its dist/ clean to its own
# 'CUtriage' prefix so all three exes coexist in a shared dist/. The triage GUI
# imports triageengine, which imports compareengine -- both bundled below.

import re, os, shutil

_init = os.path.join('triage', '__init__.py')
_m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', open(_init).read(), re.M)
VERSION = _m.group(1) if _m else '0.0'
EXE_NAME = 'CUtriage_%s' % VERSION

print('=' * 60)
print('  triage.spec: building %s.exe  (version %s)' % (EXE_NAME, VERSION))
print('=' * 60)

# Clean only THIS tool's own previous exe(s) from dist/.
_dist = 'dist'
_prefix = 'CUtriage'
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
    ['triage/triage_gui.py'],
    # compare/ on pathex so compareengine is importable; both engines listed as
    # hiddenimports so the freezer bundles them regardless of dynamic import.
    pathex=['triage', 'compare', '.'],
    binaries=[],
    datas=[],
    hiddenimports=['triageengine', 'compareengine'],
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
    console=False,
)
