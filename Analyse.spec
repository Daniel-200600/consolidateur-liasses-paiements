# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
APP = ROOT / "consolidateur"

# Streamlit utilise plusieurs imports et fichiers de données dynamiques.
st_datas, st_binaries, st_hidden = collect_all("streamlit")

# Ces bibliothèques peuvent également utiliser des imports dynamiques.
plotly_hidden = collect_submodules("plotly")
pandas_hidden = collect_submodules("pandas")
openpyxl_hidden = collect_submodules("openpyxl")

datas = [
    # Application Streamlit et code métier.
    (str(APP / "app.py"), "app/consolidateur"),
    (str(APP / "core"), "app/consolidateur/core"),

    # Ressources utilisées à l'exécution.
    (str(APP / "assets"), "app/consolidateur/assets"),
    (str(APP / ".streamlit"), "app/consolidateur/.streamlit"),
    (str(APP / "data"), "app/consolidateur/data"),

    # Données Streamlit.
    *st_datas,
]

binaries = [*st_binaries]
hiddenimports = [
    *st_hidden,
    *plotly_hidden,
    *pandas_hidden,
    *openpyxl_hidden,
]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT), str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Analyse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=True,
)
