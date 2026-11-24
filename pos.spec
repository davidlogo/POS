# -*- mode: python ; coding: utf-8 -*-
"""
Especificación de PyInstaller para empaquetar el POS en modo carpeta (POS/POS.exe).
Incluye el esquema SQL, iconos SVG, plantilla Excel y los módulos ocultos de PySide6 y pyserial.
"""

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = [
    "PySide6.QtSvg",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "serial.tools.list_ports_common",
    "serial.tools.list_ports_windows",
    "serial.serialwin32",
] + collect_submodules("openpyxl")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("database/esquema.sql", "database"),
        ("recursos", "recursos"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="POS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="POS",
)
