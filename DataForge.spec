# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for 数据坊 / DataForge.

Build:
    conda run -n defect-tool python -m PyInstaller DataForge.spec --noconfirm

Produces ``dist/DataForge/DataForge.exe`` (onedir).

Why onedir and not onefile: onefile re-extracts the whole ~200 MB Qt
payload into a temp directory on *every* launch, which costs 5-15 s of
startup for a tool that gets opened many times a day, and the extract
step is also what trips antivirus heuristics. onedir starts in about a
second and the shortcut hides the folder either way.

Data files are laid out to match how the code finds them at runtime.
All three sites resolve relative to their own module, so the bundle only
has to reproduce the same relative paths:

    main.py:17        Path(__file__).parent / "assets" / "icon.ico"
    gui/theme.py:223  Path(__file__).parent / "styles" / "app.qss"
    core/config.py:13 Path(__file__).resolve().parent.parent
                          / "config" / "default_config.yaml"

Under PyInstaller ``__file__`` points into the extraction dir, so
``assets/``, ``gui/styles/`` and ``config/`` land where those
expressions already look. No code change needed.
"""
from PyInstaller.utils.hooks import collect_all

# qfluentwidgets loads its own .qss, fonts and images from inside its
# package at import time, so the package data has to come along or the
# app starts unstyled.
qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all("qfluentwidgets")

datas = qfw_datas + [
    ("assets/icon.ico", "assets"),
    ("assets/icon.png", "assets"),
    ("gui/styles/app.qss", "gui/styles"),
    ("config/default_config.yaml", "config"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=qfw_binaries,
    datas=datas,
    hiddenimports=qfw_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Dev-only and optional-backend weight. ultralytics/torch are imported
    # lazily inside core/predictor.py behind a try/except that self-disables
    # the backend, so excluding them costs the AI-prelabel feature and
    # nothing else — they are not installed in this env anyway.
    excludes=[
        "tkinter",
        "matplotlib",
        "pytest",
        "_pytest",
        "ultralytics",
        "torch",
        "torchvision",
        "PyQt5",
        "PySide2",
        "PySide6",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DataForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # GUI app; diagnostics go to ~/.dataforge/logs/
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DataForge",
)
