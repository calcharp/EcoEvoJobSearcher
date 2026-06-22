# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Keep the bundle lean — avoid pulling optional desktop/scientific stacks from the host env.
excludes = [
    "IPython",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "tkinter",
    "PIL",
    "jedi",
    "parso",
    "notebook",
    "pytest",
]

hiddenimports = [
    "flask",
    "werkzeug",
    "werkzeug.routing",
    "jinja2",
    "markupsafe",
    "click",
    "itsdangerous",
    "blinker",
    "requests",
    "urllib3",
    "certifi",
    "charset_normalizer",
    "idna",
    "sqlite3",
    "html.parser",
    "xml.etree.ElementTree",
    "concurrent.futures",
    "jobboards.scrape.ecoevo",
    "jobboards.scrape.evoldir",
    "jobboards.scrape.sciencecareers",
    "jobboards.subjects",
    "jobboards.geocode",
    "jobboards.user_data",
    "jobboards.embed",
    "jobboards.notes",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("static", "static"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name="JobBoards",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
