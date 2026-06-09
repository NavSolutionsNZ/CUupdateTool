# cu.spec -- PyInstaller spec for the CU update GUI launcher.
# Build on a Windows machine (one-time):  pyinstaller cu.spec
# Produces dist\CUupdate.exe -- a single double-clickable file, no Python needed.
# See BUILD.md.

block_cipher = None

a = Analysis(
    ['cu_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    # Engine modules are imported normally; list as hiddenimports so the
    # freezer definitely bundles them even if it misses a dynamic import.
    hiddenimports=[
        'census', 'run_batch', 'execute', 'diffengine', 'scorer', 'structdiff',
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
    name='CUupdate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,          # windowed app, no console window
)
