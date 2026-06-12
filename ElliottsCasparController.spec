# -*- mode: python ; coding: utf-8 -*-
import os
import sys

try:
    from PyInstaller.building.build_main import Analysis
    from PyInstaller.building.api import EXE, PYZ, COLLECT
except ImportError:
    from PyInstaller.building.api import Analysis, EXE, PYZ, COLLECT

sys.path.insert(0, os.path.abspath('.'))
try:
    from elliotts_casper_controller import __version__
    VERSION = __version__
except Exception:
    VERSION = "0.1.0"

datas = []
if os.path.exists('static'):
    datas.append(('static', 'static'))
if os.path.exists('README.md'):
    datas.append(('README.md', '.'))

a = Analysis(
    ['elliotts_casper_controller/__main__.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # uvicorn — core
        'uvicorn',
        'uvicorn.main',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn._subprocess',
        # uvicorn — HTTP protocols
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        # uvicorn — WebSocket protocols
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        # uvicorn — lifespan
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # uvicorn — config/middleware
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.supervisors',
        'uvicorn.middleware',
        'uvicorn.middleware.proxy_headers',
        'uvicorn.middleware.wsgi',
        # HTTP/async
        'h11',
        'anyio',
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        'anyio.abc',
        'anyio.streams',
        'anyio.streams.memory',
        # starlette (FastAPI runtime)
        'starlette',
        'starlette.routing',
        'starlette.requests',
        'starlette.responses',
        'starlette.middleware',
        'starlette.middleware.base',
        'starlette.middleware.cors',
        'starlette.staticfiles',
        'starlette.templating',
        'starlette.background',
        'starlette.concurrency',
        'starlette.datastructures',
        'starlette.exceptions',
        'starlette.formparsers',
        'starlette.types',
        'starlette.websockets',
        # FastAPI
        'fastapi',
        'fastapi.responses',
        'fastapi.routing',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        # pydantic
        'pydantic',
        'pydantic.v1',
        # GUI / tray
        'tkinter',
        'tkinter.scrolledtext',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageTk',
        # system
        'psutil',
        'psutil._pswindows',
        'xml.etree.ElementTree',
        'urllib.request',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='ElliottsCasparController',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='static/esc_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ElliottsCasparController',
)
