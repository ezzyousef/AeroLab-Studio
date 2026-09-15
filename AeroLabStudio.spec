# PyInstaller build script for AeroLab Studio.
#
#   pip install pyinstaller
#   pyinstaller AeroLabStudio.spec --noconfirm
#
# Produces dist/AeroLabStudio/AeroLabStudio.exe (a one-folder build, which starts far
# faster than a single file and lets the installer patch individual files later).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)                      # noqa: F821 - PyInstaller injects SPECPATH

datas = [
    (str(HERE / "aerolab" / "resources" / "samples"), "aerolab/resources/samples"),
    (str(HERE / "docs"), "docs"),
    (str(HERE / "README.md"), "."),
]
# The .ico ships as data too, so the About page and the window icon can load it at runtime.
if (HERE / "build_assets" / "aerolab.ico").exists():
    datas.append((str(HERE / "build_assets" / "aerolab.ico"), "build_assets"))
datas += collect_data_files("matplotlib", subdir="mpl-data")

hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "scipy.special._cdflib",
    "scipy._lib.array_api_compat.numpy.fft",
    "xlsxwriter",
    "openpyxl",
]
# originpro is optional: include it when it is installed so the built app can drive Origin.
try:
    import originpro                        # noqa: F401
    hiddenimports += collect_submodules("originpro") + ["win32com.client", "pythoncom",
                                                        "pywintypes"]
except ImportError:
    pass

excludes = [
    "tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "jupyter", "notebook",
    "pytest", "sphinx", "pandas.tests", "numpy.random._examples",
    "matplotlib.backends.backend_webagg", "matplotlib.backends.backend_tkagg",
]

a = Analysis(                               # noqa: F821
    ["main.py"],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)                           # noqa: F821

exe = EXE(                                  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AeroLabStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                          # a GUI app: no console window
    disable_windowed_traceback=False,
    icon=str(HERE / "build_assets" / "aerolab.ico")
         if (HERE / "build_assets" / "aerolab.ico").exists() else None,
    version=str(HERE / "build_assets" / "version_info.txt")
            if (HERE / "build_assets" / "version_info.txt").exists() else None,
)

coll = COLLECT(                             # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AeroLabStudio",
)
