# PyInstaller-Konfiguration. Bauen mit: python packaging/build_exe.py
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("rampenschmiede", include_py_files=False)
hiddenimports = collect_submodules("glcontext") + ["moderngl"]

a = Analysis(
    ["entry.py"],
    pathex=["../src"],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQuick", "PySide6.Qt3DCore"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Rampenschmiede",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Rampenschmiede")
