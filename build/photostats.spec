# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Photo Stats.

Build with:  pyinstaller build/photostats.spec --noconfirm

Produces a one-directory bundle, because a one-file PySide6 build costs several
seconds to start every launch.

exiftool is *not* bundled: on macOS and Linux it is a Perl program (the macOS
distribution alone adds 20 MB of modules and still needs a system Perl), so the
app looks it up at runtime and offers to install it if it is missing.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
ENTRY = ROOT / "run_photostats.py"
# Each platform wants a different container: macOS takes .icns, Windows takes
# .ico and will not fall back to .png, everything else takes .png.
ICON_ICNS = ROOT / "build" / "assets" / "icon.icns"
ICON_ICO = ROOT / "build" / "assets" / "icon.ico"
ICON_PNG = ROOT / "build" / "assets" / "icon.png"
if sys.platform == "darwin" and ICON_ICNS.is_file():
    ICON = ICON_ICNS
elif sys.platform == "win32" and ICON_ICO.is_file():
    ICON = ICON_ICO
else:
    ICON = ICON_PNG

# Qt modules the app does not use; leaving them out keeps the bundle smaller.
EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtSerialPort",
    "tkinter", "unittest", "pydoc_data", "lib2to3", "numpy", "PIL",
]

datas = collect_data_files("photostats", include_py_files=False)

hiddenimports = ["photostats.ui.main_window", "photostats.app"]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Photo Stats",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no terminal window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Photo Stats",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Photo Stats.app",
        icon=str(ICON) if ICON.is_file() else None,
        bundle_identifier="com.picstome.photostats",
        info_plist={
            "CFBundleName": "Photo Stats",
            "CFBundleDisplayName": "Photo Stats",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            # Lets the app open a photo folder from Finder / the Dock.
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Folder",
                    "CFBundleTypeRole": "Viewer",
                    "LSItemContentTypes": ["public.folder"],
                }
            ],
        },
    )