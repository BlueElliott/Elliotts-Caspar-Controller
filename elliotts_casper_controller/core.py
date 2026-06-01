"""FastAPI application — web UI and REST API for Elliott's Casper Controller."""
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from elliotts_casper_controller import __version__
from elliotts_casper_controller.amcp_client import AMCPClient
from elliotts_casper_controller.config_manager import (
    load as load_config, save as save_config,
    regenerate_caspar_config, import_from_caspar_config,
)
from elliotts_casper_controller.process_manager import CasparProcessManager

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_config = load_config()
_client: Optional[AMCPClient] = None
_manager: Optional[CasparProcessManager] = None
_log: list[str] = []
_log_lock = threading.Lock()

MAX_LOG = 200


def _log_event(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _log_lock:
        _log.append(f"[{ts}] {msg}")
        if len(_log) > MAX_LOG:
            _log.pop(0)


def _get_manager() -> CasparProcessManager:
    global _manager, _client, _config
    _config = load_config()
    _client = AMCPClient(port=_config["amcp_port"])
    _manager = CasparProcessManager(
        exe_path=_config["caspar_exe_path"],
        amcp_port=_config["amcp_port"],
        startup_delay=_config["startup_delay"],
    )
    return _manager


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _get_manager()
    yield


app = FastAPI(title="Elliott's Casper Controller", version=__version__, lifespan=lifespan)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

FONTS = """
@font-face { font-family: 'ITVReem'; src: url('/static/ITV Reem-Regular.ttf'); font-weight: 400; }
@font-face { font-family: 'ITVReem'; src: url('/static/ITV Reem-Light.ttf');   font-weight: 300; }
@font-face { font-family: 'ITVReem'; src: url('/static/ITV Reem-Medium.ttf');  font-weight: 500; }
@font-face { font-family: 'ITVReem'; src: url('/static/ITV Reem-Bold.ttf');    font-weight: 700; }
"""

BASE_CSS = FONTS + """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:       #1a1a1a;
  --card:     #2d2d2d;
  --input-bg: #252525;
  --border:   #3d3d3d;
  --accent:   #00bcd4;
  --accent-h: #0097a7;
  --text:     #ffffff;
  --muted:    #888888;
  --success:  #22c55e;
  --error:    #ef4444;
  --warning:  #f59e0b;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'ITVReem', 'Segoe UI', sans-serif;
  font-size: 14px;
  min-height: 100vh;
}
a { color: var(--accent); text-decoration: none; }
h1 { font-size: 24px; font-weight: 700; }
h2 { font-size: 18px; font-weight: 600; }
h3 { font-size: 15px; font-weight: 500; }

/* NAV */
.nav {
  position: fixed; top: 16px; left: 16px; z-index: 100;
  display: flex; gap: 6px; flex-wrap: wrap;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 8px 12px;
}
.nav a {
  padding: 6px 14px; border-radius: 6px; font-weight: 500;
  color: var(--muted); transition: all 0.2s;
}
.nav a:hover { background: rgba(0,188,212,0.15); color: var(--accent); }
.nav a.active { background: var(--accent); color: #fff; }

/* MAIN */
.main { max-width: 960px; margin: 0 auto; padding: 90px 20px 40px; }

/* CARDS */
.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px; margin-bottom: 16px;
}
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }

/* BUTTONS */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  height: 40px; padding: 0 18px; border: none; border-radius: 8px;
  font-family: 'ITVReem', sans-serif; font-size: 14px; font-weight: 500;
  cursor: pointer; transition: all 0.2s; white-space: nowrap;
}
.btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
.btn-primary  { background: var(--accent);  color: #fff; }
.btn-primary:hover { background: var(--accent-h); }
.btn-danger   { background: var(--error);   color: #fff; }
.btn-danger:hover { background: #dc2626; }
.btn-success  { background: var(--success); color: #fff; }
.btn-secondary{ background: var(--border);  color: var(--text); }
.btn-warning  { background: var(--warning); color: #000; }
.btn-sm { height: 32px; padding: 0 12px; font-size: 13px; }

/* BADGES */
.badge {
  display: inline-block; padding: 3px 10px; border-radius: 20px;
  font-size: 12px; font-weight: 600;
}
.badge-success { background: rgba(34,197,94,0.15);  color: var(--success); border: 1px solid rgba(34,197,94,0.3); }
.badge-error   { background: rgba(239,68,68,0.15);   color: var(--error);   border: 1px solid rgba(239,68,68,0.3); }
.badge-warning { background: rgba(245,158,11,0.15);  color: var(--warning); border: 1px solid rgba(245,158,11,0.3); }
.badge-neutral { background: rgba(136,136,136,0.15); color: var(--muted);   border: 1px solid rgba(136,136,136,0.3); }

/* GRID */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.grid-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
@media (max-width: 700px) {
  .grid-2, .grid-3, .grid-5 { grid-template-columns: 1fr; }
}

/* INPUTS */
input, select, textarea {
  background: var(--input-bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 14px; font-family: 'ITVReem', sans-serif; font-size: 14px;
  width: 100%; transition: border-color 0.2s, box-shadow 0.2s;
}
input:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(0,188,212,0.2);
}
label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 13px; }
.form-group { margin-bottom: 14px; }

/* LOG */
.log-box {
  background: #111; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px; height: 160px; overflow-y: auto;
  font-family: 'Consolas', monospace; font-size: 12px; color: #aaa;
}
.log-box p { margin: 2px 0; }
.log-box p.error { color: var(--error); }
.log-box p.ok    { color: var(--success); }

/* TOAST */
#toast-container {
  position: fixed; top: 80px; right: 20px; z-index: 9999;
  display: flex; flex-direction: column; gap: 8px;
}
.toast {
  background: var(--card); border-radius: 8px; padding: 12px 16px;
  border-left: 4px solid; min-width: 260px; max-width: 380px;
  animation: slide-in 0.3s ease;
}
.toast-success { border-color: var(--success); }
.toast-error   { border-color: var(--error);   }
.toast-warning { border-color: var(--warning); }
.toast-info    { border-color: var(--accent);  }
@keyframes slide-in { from { transform: translateX(110%); } to { transform: translateX(0); } }

/* CHANNEL EDIT CARD (settings page) */
.ch-edit-card {
  background: var(--input-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 10px 12px; margin-bottom: 8px;
}
.ch-edit-card .ch-edit-top {
  display: flex; gap: 8px; align-items: center; flex-wrap: nowrap;
}
.ch-edit-card .ch-edit-source {
  margin-top: 6px; padding-left: 78px;
}
.ch-edit-card input, .ch-edit-card select {
  padding: 7px 10px; font-size: 13px;
}

/* CHANNEL CARD (dashboard) */
.channel-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px; display: flex;
  flex-direction: column; gap: 10px;
}
.channel-card .ch-num {
  font-size: 11px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
}
.channel-card .ch-name { font-size: 18px; font-weight: 700; }
.channel-card .ch-ndi  { font-size: 12px; color: var(--muted); }

/* PULSE */
.pulse { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
.pulse-green { background: var(--success); box-shadow: 0 0 0 0 rgba(34,197,94,0.4);
  animation: pulse-anim 1.5s infinite; }
.pulse-red   { background: var(--error); }
@keyframes pulse-anim {
  0%   { box-shadow: 0 0 0 0 rgba(34,197,94,0.4); }
  70%  { box-shadow: 0 0 0 8px rgba(34,197,94,0); }
  100% { box-shadow: 0 0 0 0 rgba(34,197,94,0);   }
}

/* MULTIVIEWER */
.mv-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
@media (max-width: 800px) { .mv-grid { grid-template-columns: 1fr 1fr; } }
.mv-frame { background: #111; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.mv-frame iframe { display: block; width: 100%; height: 180px; border: none; background: #000; }
.mv-label { padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; }
.mv-label span { font-size: 13px; font-weight: 600; }

/* TABLE */
table { width: 100%; border-collapse: collapse; }
thead { background: var(--accent); }
thead th { color: #fff; padding: 10px 14px; text-align: left; font-weight: 600; }
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover { background: rgba(255,255,255,0.03); }
tbody td { padding: 10px 14px; }
"""

JS_SHARED = """
function toast(msg, type='info') {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function api(url, method='GET', body=null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  return fetch(url, opts).then(r => r.json());
}
"""


def nav(active: str) -> str:
    links = [("Dashboard", "/", "dashboard"), ("Multiviewer", "/multiviewer", "multiviewer"), ("Settings", "/settings", "settings")]
    items = "".join(f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>' for label, href, key in links)
    return f'<nav class="nav">{items}</nav>'


def page(title: str, active: str, body: str, extra_js: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Elliott's Casper Controller</title>
<style>{BASE_CSS}</style>
</head>
<body>
{nav(active)}
<div id="toast-container"></div>
<main class="main">
<h1 style="margin-bottom:24px">{title}</h1>
{body}
</main>
<script>{JS_SHARED}{extra_js}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Static font serving
# ---------------------------------------------------------------------------

import os
import sys
from fastapi.responses import FileResponse


def _app_root() -> str:
    """Return the root directory containing static/ — works both frozen and from source."""
    if getattr(sys, "frozen", False):
        # PyInstaller extracts everything to sys._MEIPASS
        return sys._MEIPASS
    # Running from source: go up one level from elliotts_casper_controller/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


STATIC_DIR = os.path.join(_app_root(), "static")


@app.get("/static/{filename:path}")
def static_file(filename: str):
    path = os.path.join(STATIC_DIR, filename)
    if os.path.isfile(path):
        return FileResponse(path)
    raise HTTPException(status_code=404)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ConfigUpdate(BaseModel):
    caspar_exe_path: Optional[str] = None
    amcp_port: Optional[int] = None
    web_port: Optional[int] = None
    startup_delay: Optional[int] = None
    video_mode: Optional[str] = None
    autostart_caspar: Optional[bool] = None
    channels: Optional[list] = None


@app.get("/api/status")
def api_status():
    cfg = load_config()
    client = AMCPClient(port=cfg["amcp_port"])
    running = client.ping()
    channels = []
    for ch in cfg["channels"]:
        info = client.info_channel(ch["number"]) if running else ""
        channels.append({
            "number": ch["number"],
            "name": ch["name"],
            "ndi_name": ch["ndi_name"],
            "type": ch.get("type", "html"),
            "url": ch.get("url", ""),
            "startup_command": ch.get("startup_command", ""),
            "status": "live" if (running and not info.startswith("ERROR")) else "stopped",
        })
    return {"running": running, "version": __version__, "channels": channels}


def _load_channel(ch: dict, client: AMCPClient) -> str:
    """Send the correct startup command for a channel based on its type."""
    ch_type = ch.get("type", "html")
    n = ch["number"]
    if ch_type == "html":
        return client.play_html(n, ch.get("url", ""))
    cmd = ch.get("startup_command", "").strip()
    return client.send(cmd) if cmd else client.send(f"CLEAR {n}")


@app.post("/api/server/start")
def api_server_start():
    m = _get_manager()
    _log_event("Starting CasparCG...")
    ok = m.start()
    if ok:
        cfg = load_config()
        client = AMCPClient(port=cfg["amcp_port"])
        for ch in cfg["channels"]:
            res = _load_channel(ch, client)
            _log_event(f"CH{ch['number']} ({ch['name']}) load -> {res[:60]}")
        _log_event("CasparCG started and channels loaded.")
        return {"ok": True, "message": "CasparCG started"}
    _log_event("CasparCG failed to start.")
    raise HTTPException(status_code=500, detail="Failed to start CasparCG")


@app.post("/api/server/stop")
def api_server_stop():
    m = _get_manager()
    m.stop()
    _log_event("CasparCG stopped.")
    return {"ok": True}


@app.post("/api/channel/{number}/restart")
def api_channel_restart(number: int):
    cfg = load_config()
    channels = {ch["number"]: ch for ch in cfg["channels"]}
    if number not in channels:
        raise HTTPException(status_code=404, detail=f"Channel {number} not found")
    ch = channels[number]
    client = AMCPClient(port=cfg["amcp_port"])
    client.stop_channel(number)
    time.sleep(0.5)
    res = _load_channel(ch, client)
    _log_event(f"CH{number} ({ch['name']}) restarted -> {res[:60]}")
    return {"ok": True, "response": res}


@app.post("/api/channel/all/restart")
def api_channel_restart_all():
    cfg = load_config()
    client = AMCPClient(port=cfg["amcp_port"])
    results = []
    for ch in cfg["channels"]:
        client.stop_channel(ch["number"])
        time.sleep(0.3)
        res = _load_channel(ch, client)
        _log_event(f"CH{ch['number']} restarted -> {res[:60]}")
        results.append({"number": ch["number"], "response": res})
    return {"ok": True, "results": results}


class AMCPCommandRequest(BaseModel):
    command: str


@app.post("/api/channel/{number}/amcp")
def api_channel_amcp(number: int, req: AMCPCommandRequest):
    cfg = load_config()
    client = AMCPClient(port=cfg["amcp_port"])
    res = client.send(req.command.strip())
    _log_event(f"CH{number} AMCP: {req.command[:60]} -> {res[:60]}")
    return {"ok": True, "response": res}


@app.get("/api/channel/{number}/stream")
def api_channel_stream(number: int):
    """Live MJPEG stream of a CasparCG NDI output via ndi-python."""
    from fastapi.responses import StreamingResponse as _SR
    try:
        import NDIlib as ndi
        import numpy as np
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="ndi-python not installed. Run: pip install ndi-python numpy"
        )

    cfg = load_config()
    channels = {ch["number"]: ch for ch in cfg["channels"]}
    if number not in channels:
        raise HTTPException(status_code=404, detail=f"Channel {number} not found")
    ndi_name = channels[number].get("ndi_name", "")

    def _generate():
        from PIL import Image
        import io as _io

        if not ndi.initialize():
            return

        find = ndi.find_create_v3()
        if not find:
            ndi.destroy()
            return

        # Locate the NDI source by name (up to 3 s)
        source = None
        for _ in range(30):
            ndi.find_wait_for_sources(find, 100)
            for s in ndi.find_get_current_sources(find):
                if ndi_name.lower() in s.ndi_name.lower():
                    source = s
                    break
            if source:
                break

        if not source:
            ndi.find_destroy(find)
            ndi.destroy()
            return

        recv_create = ndi.RecvCreateV3()
        recv_create.color_format = ndi.RECV_COLOR_FORMAT_RGBX_RGBA
        recv_create.bandwidth = ndi.RECV_BANDWIDTH_HIGHEST
        recv = ndi.recv_create_v3(recv_create)
        if not recv:
            ndi.find_destroy(find)
            ndi.destroy()
            return

        ndi.recv_connect(recv, source)
        ndi.find_destroy(find)

        try:
            while True:
                t, v, a, m = ndi.recv_capture_v3(recv, 1000)
                if t == ndi.FRAME_TYPE_VIDEO and v is not None:
                    try:
                        arr = np.copy(v.data)
                        ndi.recv_free_video_v3(recv, v)
                        img = Image.fromarray(arr[:, :, :3])  # RGBA → RGB
                        buf = _io.BytesIO()
                        img.save(buf, format="JPEG", quality=80)
                        jpg = buf.getvalue()
                        yield (b"--mjpegframe\r\n"
                               b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
                    except Exception:
                        pass
                elif t == ndi.FRAME_TYPE_AUDIO and a is not None:
                    ndi.recv_free_audio_v3(recv, a)
                elif t == ndi.FRAME_TYPE_METADATA and m is not None:
                    ndi.recv_free_metadata(recv, m)
        finally:
            ndi.recv_destroy(recv)
            ndi.destroy()

    return _SR(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=mjpegframe",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@app.get("/api/media")
def api_media():
    """List clip names from CasparCG's media folder (relative paths, no extension)."""
    cfg = load_config()
    exe = cfg.get("caspar_exe_path", "")
    if not exe or not os.path.isfile(exe):
        return {"clips": [], "error": "CasparCG exe path not set"}
    media_dir = os.path.join(os.path.dirname(exe), "media")
    if not os.path.isdir(media_dir):
        return {"clips": [], "error": f"Media folder not found: {media_dir}"}
    MEDIA_EXTS = {".mp4", ".mov", ".avi", ".mxf", ".mkv", ".wmv", ".flv",
                  ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif"}
    clips = []
    for root, _, files in os.walk(media_dir):
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext in MEDIA_EXTS:
                rel = os.path.relpath(os.path.join(root, fname), media_dir)
                clip_name = os.path.splitext(rel)[0].replace(os.sep, "/").upper()
                clips.append(clip_name)
    return {"clips": sorted(clips), "media_dir": media_dir}


@app.get("/api/config")
def api_config_get():
    return load_config()


@app.post("/api/config")
def api_config_post(update: ConfigUpdate):
    cfg = load_config()
    data = update.model_dump(exclude_none=True)
    # Renumber channels by array order so the web UI can reorder freely
    if "channels" in data:
        for i, ch in enumerate(data["channels"], start=1):
            ch["number"] = i
    cfg.update(data)
    save_config(cfg)
    regenerate_caspar_config(cfg)
    _log_event("Config saved and casparcg.config regenerated.")
    return {"ok": True}


@app.get("/api/log")
def api_log():
    with _log_lock:
        return {"log": list(_log)}


class ImportConfigRequest(BaseModel):
    path: str


@app.post("/api/config/import")
def api_config_import(req: ImportConfigRequest):
    import os
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.path}")
    try:
        cfg = load_config()
        merged = import_from_caspar_config(req.path, cfg)
        save_config(merged)
        regenerate_caspar_config(merged)
        _log_event(f"Imported casparcg.config from {req.path}")
        return {"ok": True, "video_mode": merged["video_mode"], "amcp_port": merged["amcp_port"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def page_dashboard():
    body = """
<div class="card">
  <div class="card-header">
    <div style="display:flex;align-items:center">
      <span class="pulse" id="pulse"></span>
      <span id="server-status-label">Checking...</span>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-success" onclick="serverAction('start')">Start CasparCG</button>
      <button class="btn btn-danger" onclick="serverAction('stop')">Stop CasparCG</button>
      <button class="btn btn-warning" onclick="restartAll()">Restart All Channels</button>
    </div>
  </div>
</div>

<div id="channel-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:16px"></div>

<div class="card">
  <h3 style="margin-bottom:10px">Event Log</h3>
  <div class="log-box" id="log-box"></div>
</div>
"""
    js = """
let lastRunning = null;

let _mediaClips = [];

function loadMediaClips() {
  api('/api/media').then(data => {
    _mediaClips = data.clips || [];
    document.querySelectorAll('[id^="media_"]').forEach(sel => {
      const ch = sel.id.split('_')[1];
      const current = sel.value;
      sel.innerHTML = '<option value="">— pick a clip —</option>' +
        _mediaClips.map(c => `<option value="${c}"${c===current?' selected':''}>${c}</option>`).join('');
    });
  });
}

function onMediaSelect(n) {
  const sel = document.getElementById('media_' + n);
  const clip = sel.value;
  if (!clip) return;
  document.getElementById('amcp_' + n).value = `PLAY ${n}-1 "${clip}" LOOP`;
}

function renderChannels(channels) {
  const g = document.getElementById('channel-grid');
  g.innerHTML = channels.map(ch => {
    const isHtml  = ch.type === 'html' || !ch.type;
    const typeBadge = isHtml
      ? '<span class="badge badge-neutral" style="font-size:10px">HTML5</span>'
      : '<span class="badge badge-warning" style="font-size:10px">Media</span>';
    const sourceInfo = isHtml
      ? `<div class="ch-ndi" title="${ch.url}" style="word-break:break-all;font-size:11px">${ch.url ? ch.url.replace(/^https?:\\/\\//, '').substring(0,45)+(ch.url.length>52?'...':'') : '(no url)'}</div>`
      : `<div class="ch-ndi" style="color:var(--warning);font-size:11px">${ch.startup_command || '(no startup command)'}</div>`;
    const amcpRow = !isHtml ? `
      <div style="display:flex;gap:4px;margin-top:4px">
        <select id="media_${ch.number}"
                style="flex:1;font-size:11px;padding:5px 8px;min-width:0;background:var(--input-bg);color:var(--muted);border:1px solid var(--border);border-radius:6px"
                onchange="onMediaSelect(${ch.number})">
          <option value="">— pick a clip —</option>
        </select>
      </div>
      <div style="display:flex;gap:4px;margin-top:4px">
        <input type="text" id="amcp_${ch.number}" placeholder="PLAY ${ch.number}-1 CLIP LOOP"
               style="flex:1;font-size:11px;padding:5px 8px;min-width:0">
        <button class="btn btn-secondary btn-sm" style="padding:0 10px;flex-shrink:0"
                onclick="sendAmcp(${ch.number})">Send</button>
      </div>` : '';
    return `
    <div class="channel-card">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div class="ch-num">Channel ${ch.number}</div>
        ${typeBadge}
      </div>
      <div class="ch-name">${ch.name}</div>
      <div class="ch-ndi">NDI: ${ch.ndi_name}</div>
      ${sourceInfo}
      <span class="badge ${ch.status === 'live' ? 'badge-success' : 'badge-error'}">${ch.status}</span>
      <button class="btn btn-danger btn-sm" onclick="restartChannel(${ch.number}, '${ch.name}')">Restart</button>
      ${amcpRow}
    </div>`;
  }).join('');
}

function updateStatus() {
  api('/api/status').then(data => {
    const running = data.running;
    document.getElementById('pulse').className = 'pulse ' + (running ? 'pulse-green' : 'pulse-red');
    document.getElementById('server-status-label').textContent = running ? 'CasparCG Running' : 'CasparCG Stopped';
    renderChannels(data.channels);
    loadMediaClips();
    if (lastRunning !== null && lastRunning !== running)
      toast(running ? 'CasparCG is now running' : 'CasparCG stopped', running ? 'success' : 'warning');
    lastRunning = running;
  });
  api('/api/log').then(data => {
    document.getElementById('log-box').innerHTML = data.log.slice().reverse().map(l => `<p>${l}</p>`).join('');
  });
}

function serverAction(action) {
  toast('Sending ' + action + '...', 'info');
  api('/api/server/' + action, 'POST').then(d => {
    toast(d.message || (action + ' OK'), 'success');
    updateStatus();
  }).catch(() => toast('Failed to ' + action, 'error'));
}

function restartChannel(n, name) {
  toast('Restarting ' + name + '...', 'warning');
  api('/api/channel/' + n + '/restart', 'POST').then(() => {
    toast(name + ' restarted', 'success');
    updateStatus();
  }).catch(() => toast('Failed to restart ' + name, 'error'));
}

function restartAll() {
  toast('Restarting all channels...', 'warning');
  api('/api/channel/all/restart', 'POST').then(() => {
    toast('All channels restarted', 'success');
    updateStatus();
  }).catch(() => toast('Failed', 'error'));
}

function sendAmcp(n) {
  const input = document.getElementById('amcp_' + n);
  const cmd = input.value.trim();
  if (!cmd) { toast('Enter an AMCP command first', 'warning'); return; }
  api('/api/channel/' + n + '/amcp', 'POST', { command: cmd }).then(d => {
    toast('CH' + n + ': ' + (d.response || 'OK'), 'success');
  }).catch(() => toast('Failed to send AMCP', 'error'));
}

updateStatus();
setInterval(updateStatus, 4000);
"""
    return HTMLResponse(page("Dashboard", "dashboard", body, js))


@app.get("/multiviewer", response_class=HTMLResponse)
def page_multiviewer():
    cfg = load_config()
    channels = cfg["channels"]
    frames = ""
    for ch in channels:
        type_badge = (
            '<span class="badge badge-neutral" style="font-size:10px">HTML5</span>'
            if ch.get("type", "html") == "html"
            else '<span class="badge badge-warning" style="font-size:10px">Media</span>'
        )
        frames += f"""
<div class="mv-frame">
  <div style="position:relative;background:#000;height:180px;display:flex;align-items:center;justify-content:center">
    <img id="stream-{ch['number']}" src="/api/channel/{ch['number']}/stream"
         style="max-width:100%;max-height:180px;object-fit:contain;display:block"
         onerror="this.style.display='none';document.getElementById('err-{ch['number']}').style.display='flex'"
         onload="document.getElementById('err-{ch['number']}').style.display='none'">
    <div id="err-{ch['number']}" style="display:none;position:absolute;inset:0;align-items:center;
         justify-content:center;flex-direction:column;gap:6px;color:var(--muted);font-size:12px">
      <span style="font-size:28px;opacity:.4">▶</span>
      <span>No signal — is CasparCG running?</span>
      <button class="btn btn-secondary btn-sm" onclick="reconnect({ch['number']})">Reconnect</button>
    </div>
  </div>
  <div class="mv-label">
    <span>CH{ch['number']} — {ch['name']} &nbsp;{type_badge}</span>
    <span style="color:var(--muted);font-size:11px">{ch.get('ndi_name','')}</span>
  </div>
</div>"""

    body = f"""
<p style="color:var(--muted);margin-bottom:16px">
  Live NDI output preview via MJPEG — all channel types. Requires <code>ndi-python</code> and CasparCG running.
</p>
<div class="mv-grid">
{frames}
</div>
"""
    js = """
function reconnect(n) {
  const img = document.getElementById('stream-' + n);
  const err = document.getElementById('err-' + n);
  if (!img) return;
  err.style.display = 'none';
  img.style.display = 'block';
  img.src = '/api/channel/' + n + '/stream?' + Date.now();
}
"""
    return HTMLResponse(page("Multiviewer", "multiviewer", body, js))


@app.get("/settings", response_class=HTMLResponse)
def page_settings():
    body = """
<!-- CasparCG Executable -->
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-bottom:16px">CasparCG Executable</h2>
  <div style="display:flex;gap:10px;align-items:flex-end">
    <div class="form-group" style="flex:1;margin:0">
      <label>Path to casparcg.exe</label>
      <input type="text" id="caspar_exe_path" placeholder="C:\\CasparCG\\casparcg.exe">
    </div>
    <button class="btn btn-primary" onclick="saveExePath()" style="flex-shrink:0">Save Path</button>
  </div>
  <p style="color:var(--muted);font-size:12px;margin-top:8px">
    <code>casparcg.config</code> is written to the same folder as the exe each time CasparCG is started.
  </p>
</div>

<!-- Import existing casparcg.config -->
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-bottom:12px">Import Existing casparcg.config</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:12px">
    Pull video mode, AMCP port and NDI names from an existing <code>casparcg.config</code>.
  </p>
  <div style="display:flex;gap:10px;align-items:flex-end">
    <div class="form-group" style="flex:1;margin:0">
      <label>Path to casparcg.config</label>
      <input type="text" id="import-path" placeholder="C:\\CasparCG\\casparcg.config">
    </div>
    <button class="btn btn-warning" onclick="importConfig()" style="flex-shrink:0">Import Config</button>
  </div>
  <div id="import-result" style="margin-top:10px;display:none" class="badge badge-success"></div>
</div>

<!-- Output settings + channel editor -->
<div class="card" id="settings-form">
  <h2 style="margin-bottom:16px">Output Settings</h2>
  <div class="grid-2">
    <div class="form-group">
      <label>Video Mode</label>
      <select id="video_mode">
        <option value="1080p2500">1080p 25fps</option>
        <option value="1080p5000">1080p 50fps</option>
        <option value="1080i5000">1080i 50i</option>
        <option value="720p5000">720p 50fps</option>
        <option value="720p2500">720p 25fps</option>
      </select>
    </div>
    <div class="form-group">
      <label>AMCP Port</label>
      <input type="number" id="amcp_port" value="5250">
    </div>
    <div class="form-group">
      <label>Web UI Port</label>
      <input type="number" id="web_port" value="5280">
    </div>
    <div class="form-group">
      <label>Startup Delay (seconds)</label>
      <input type="number" id="startup_delay" value="8" min="2" max="30">
    </div>
    <div class="form-group" style="display:flex;align-items:center;gap:10px;padding-top:4px">
      <input type="checkbox" id="autostart_caspar"
             style="width:18px;height:18px;flex-shrink:0;accent-color:var(--accent);cursor:pointer">
      <label for="autostart_caspar" style="margin:0;color:var(--text);cursor:pointer">
        Auto-start CasparCG when the app launches
      </label>
    </div>
  </div>

  <h2 style="margin:20px 0 8px">Channels</h2>

  <!-- Column header row -->
  <div style="display:flex;gap:8px;padding:0 12px 6px;color:var(--muted);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.5px">
    <span style="width:48px;flex-shrink:0"></span>
    <span style="width:18px;flex-shrink:0;text-align:center">#</span>
    <span style="width:86px;flex-shrink:0">Type</span>
    <span style="flex:0 0 110px">Name</span>
    <span style="flex:0 0 160px">NDI Name</span>
    <span style="flex:1">URL / Startup Command</span>
  </div>

  <div id="channels-tbody"></div>

  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:20px">
    <div style="display:flex;gap:10px">
      <button class="btn btn-primary" onclick="saveSettings()">Save & Regenerate Config</button>
      <button class="btn btn-secondary" onclick="loadSettings()">Reset</button>
    </div>
    <button class="btn btn-primary btn-sm" onclick="addChannel()">+ Add Channel</button>
  </div>
  <p style="color:var(--muted);font-size:12px;margin-top:10px">
    Channel order determines CasparCG channel numbers (top = CH1). Restart CasparCG after saving to apply changes.
  </p>
</div>
"""
    js = """
let currentChannels = [];

function loadSettings() {
  api('/api/config').then(cfg => {
    document.getElementById('caspar_exe_path').value = cfg.caspar_exe_path || '';
    document.getElementById('video_mode').value = cfg.video_mode || '1080p2500';
    document.getElementById('amcp_port').value = cfg.amcp_port || 5250;
    document.getElementById('web_port').value = cfg.web_port || 5280;
    document.getElementById('startup_delay').value = cfg.startup_delay || 8;
    document.getElementById('autostart_caspar').checked = !!cfg.autostart_caspar;
    currentChannels = (cfg.channels || []).map(ch => ({
      ...ch,
      type: ch.type || 'html',
      startup_command: ch.startup_command || '',
      url: ch.url || '',
    }));
    renderChannelTable(currentChannels);
  });
}

function renderChannelTable(chs) {
  const last = chs.length - 1;
  document.getElementById('channels-tbody').innerHTML = chs.map((ch, i) => {
    const isHtml = (ch.type || 'html') === 'html';
    const urlVal = (ch.url || '').replace(/"/g, '&quot;');
    const cmdVal = (ch.startup_command || '').replace(/"/g, '&quot;');
    const nameVal = (ch.name || '').replace(/"/g, '&quot;');
    const ndiVal  = (ch.ndi_name || '').replace(/"/g, '&quot;');
    return `
    <div class="ch-edit-card">
      <div class="ch-edit-top">
        <div style="flex-shrink:0;width:48px;display:flex;flex-direction:column;gap:3px">
          <button class="btn btn-secondary btn-sm" style="height:22px;padding:0 8px;font-size:11px"
                  ${i===0?'disabled':''} onclick="moveUp(${i})">▲</button>
          <button class="btn btn-secondary btn-sm" style="height:22px;padding:0 8px;font-size:11px"
                  ${i===last?'disabled':''} onclick="moveDown(${i})">▼</button>
        </div>
        <span style="flex-shrink:0;width:18px;text-align:center;color:var(--muted);font-size:12px">${i+1}</span>
        <select id="ch_type_${i}" onchange="toggleType(${i})" style="flex-shrink:0;width:86px">
          <option value="html" ${isHtml?'selected':''}>HTML5</option>
          <option value="media" ${!isHtml?'selected':''}>Media</option>
        </select>
        <input type="text" id="ch_name_${i}" value="${nameVal}" placeholder="Name"
               style="flex:0 0 110px;min-width:0">
        <input type="text" id="ch_ndi_${i}" value="${ndiVal}" placeholder="NDI Name"
               style="flex:0 0 160px;min-width:0">
        <button class="btn btn-danger btn-sm" style="flex-shrink:0;padding:0 10px;margin-left:auto"
                onclick="deleteChannel(${i})" title="Delete channel">×</button>
      </div>
      <div class="ch-edit-source">
        <input type="text" id="ch_url_${i}" value="${urlVal}" placeholder="https://..."
               style="width:100%;${isHtml?'':'display:none'}">
        <input type="text" id="ch_cmd_${i}" value="${cmdVal}"
               placeholder="PLAY ${i+1}-1 CLIP LOOP — leave blank to just CLEAR the channel"
               style="width:100%;${!isHtml?'':'display:none'}">
      </div>
    </div>`;
  }).join('');
}

function toggleType(i) {
  const isHtml = document.getElementById('ch_type_' + i).value === 'html';
  document.getElementById('ch_url_' + i).style.display = isHtml ? '' : 'none';
  document.getElementById('ch_cmd_' + i).style.display = isHtml ? 'none' : '';
}

function getFormChannels() {
  return currentChannels.map((ch, i) => ({
    ...ch,
    name:            document.getElementById('ch_name_' + i)?.value ?? ch.name,
    ndi_name:        document.getElementById('ch_ndi_' + i)?.value ?? ch.ndi_name,
    type:            document.getElementById('ch_type_' + i)?.value ?? ch.type,
    url:             document.getElementById('ch_url_' + i)?.value ?? ch.url,
    startup_command: document.getElementById('ch_cmd_' + i)?.value ?? ch.startup_command,
  }));
}

function moveUp(i) {
  if (i === 0) return;
  currentChannels = getFormChannels();
  [currentChannels[i-1], currentChannels[i]] = [currentChannels[i], currentChannels[i-1]];
  renderChannelTable(currentChannels);
}

function moveDown(i) {
  if (i >= currentChannels.length - 1) return;
  currentChannels = getFormChannels();
  [currentChannels[i], currentChannels[i+1]] = [currentChannels[i+1], currentChannels[i]];
  renderChannelTable(currentChannels);
}

function addChannel() {
  currentChannels = getFormChannels();
  const n = currentChannels.length + 1;
  currentChannels.push({ number: n, name: 'CH' + n, ndi_name: 'PCR3 CH' + n,
                          type: 'html', url: '', startup_command: '' });
  renderChannelTable(currentChannels);
  toast('Channel added', 'success');
}

function deleteChannel(i) {
  const name = currentChannels[i]?.name || ('CH' + (i+1));
  if (!confirm('Delete channel "' + name + '"?')) return;
  currentChannels = getFormChannels();
  currentChannels.splice(i, 1);
  renderChannelTable(currentChannels);
  toast(name + ' deleted', 'warning');
}

function saveExePath() {
  const path = document.getElementById('caspar_exe_path').value.trim();
  api('/api/config', 'POST', { caspar_exe_path: path })
    .then(() => toast('CasparCG path saved', 'success'))
    .catch(() => toast('Failed to save path', 'error'));
}

function saveSettings() {
  const channels = getFormChannels();
  const payload = {
    video_mode:       document.getElementById('video_mode').value,
    amcp_port:        parseInt(document.getElementById('amcp_port').value),
    web_port:         parseInt(document.getElementById('web_port').value),
    startup_delay:    parseInt(document.getElementById('startup_delay').value),
    autostart_caspar: document.getElementById('autostart_caspar').checked,
    channels,
  };
  api('/api/config', 'POST', payload).then(() => {
    currentChannels = channels;
    toast('Settings saved — restart CasparCG to apply', 'success');
  }).catch(() => toast('Failed to save settings', 'error'));
}

function importConfig() {
  const path = document.getElementById('import-path').value.trim();
  if (!path) { toast('Enter a path to casparcg.config first', 'warning'); return; }
  toast('Importing...', 'info');
  api('/api/config/import', 'POST', { path }).then(d => {
    const res = document.getElementById('import-result');
    res.textContent = 'Imported — video mode: ' + d.video_mode + ', AMCP port: ' + d.amcp_port;
    res.style.display = 'inline-block';
    toast('Config imported', 'success');
    loadSettings();
  }).catch(e => toast('Import failed: ' + (e.detail || e), 'error'));
}

loadSettings();
"""
    return HTMLResponse(page("Settings", "settings", body, js))


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

_server_thread: Optional[threading.Thread] = None
_uvicorn_server: Optional[uvicorn.Server] = None


def start_server(port: int = 5280, open_browser: bool = True) -> None:
    global _server_thread, _uvicorn_server
    cfg_obj = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    _uvicorn_server = uvicorn.Server(cfg_obj)

    def run():
        _uvicorn_server.run()

    _server_thread = threading.Thread(target=run, daemon=True)
    _server_thread.start()

    if open_browser:
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")


def stop_server() -> None:
    if _uvicorn_server:
        _uvicorn_server.should_exit = True


def main() -> None:
    from elliotts_casper_controller.gui_launcher import launch
    launch()
