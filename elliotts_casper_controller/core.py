"""FastAPI application — web UI and REST API for Elliott's Caspar Controller."""
import secrets
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Optional

import requests as _requests

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from elliotts_casper_controller import __version__
from elliotts_casper_controller.amcp_client import AMCPClient
from elliotts_casper_controller.config_manager import (
    load as load_config, save as save_config,
    instance_amcp_port, regenerate_instance_config, regenerate_all_instance_configs,
    ensure_test_pattern_images,
)
from elliotts_casper_controller.process_manager import CasparProcessManager
from elliotts_casper_controller import ndi_tally

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_config = load_config()
_managers: dict = {}   # inst_id -> CasparProcessManager
_log: list = []
_log_lock = threading.Lock()
_sessions: set = set()  # active session tokens for web UI auth
_remote_name_cache: dict = {}  # url -> last known server_name for offline display

MAX_LOG = 200


def _log_event(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _log_lock:
        _log.append(f"[{ts}] {msg}")
        if len(_log) > MAX_LOG:
            _log.pop(0)


def _make_manager(inst: dict, cfg: dict) -> CasparProcessManager:
    port = instance_amcp_port(cfg, inst)
    return CasparProcessManager(
        exe_path=cfg["caspar_exe_path"],
        amcp_port=port,
        startup_delay=cfg["startup_delay"],
        window_title=f"PCR3 CasparCG — {inst['name']}",
        config_filename=f"casparcg_inst_{inst['id']}.config",
    )


def _load_instance(inst: dict, client: AMCPClient) -> str:
    """Send the startup command for an instance (always channel 1 in each CasparCG process)."""
    if inst.get("type", "html") == "html":
        url = inst.get("url", "").strip()
        return client.play_html(1, url) if url else client.send("CLEAR 1")
    cmd = inst.get("startup_command", "").strip()
    return client.send(cmd) if cmd else client.send("CLEAR 1")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _refresh_tally_monitors():
    """Start/stop tally monitors to match current instance config."""
    cfg = load_config()
    ndi_names = [i["ndi_name"] for i in cfg.get("instances", []) if i.get("ndi_name")]
    ndi_tally.start_monitoring(ndi_names)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config
    _config = load_config()
    _refresh_tally_monitors()
    yield
    ndi_tally.stop_all()


app = FastAPI(title="Elliott's Caspar Controller", version=__version__, lifespan=lifespan)


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cfg = load_config()
        if not cfg.get("web_password_enabled") or not cfg.get("web_password", "").strip():
            return await call_next(request)
        path = request.url.path
        if path.startswith("/login") or path.startswith("/static") or path.startswith("/api/"):
            return await call_next(request)
        host = (request.client.host if request.client else "") or ""
        if host in ("127.0.0.1", "::1", "localhost"):
            return await call_next(request)
        if request.cookies.get("session", "") in _sessions:
            return await call_next(request)
        return RedirectResponse(url="/login")


app.add_middleware(_AuthMiddleware)


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

/* INSTANCE EDIT CARD (settings page) */
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

/* INSTANCE CARD (dashboard) */
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

/* TALLY */
.tally-program {
  border-color: var(--error) !important;
  box-shadow: 0 0 0 3px rgba(239,68,68,0.25), 0 0 16px rgba(239,68,68,0.15) !important;
}
.tally-preview {
  border-color: var(--warning) !important;
  box-shadow: 0 0 0 3px rgba(245,158,11,0.25) !important;
}
.tally-badge-program {
  display:inline-flex; align-items:center; gap:4px;
  background:var(--error); color:#fff; border-radius:20px;
  padding:2px 8px; font-size:10px; font-weight:700; letter-spacing:.5px;
  animation: tally-pulse 1s infinite;
}
.tally-badge-preview {
  display:inline-flex; align-items:center; gap:4px;
  background:var(--warning); color:#000; border-radius:20px;
  padding:2px 8px; font-size:10px; font-weight:700;
}
@keyframes tally-pulse {
  0%,100% { opacity:1; } 50% { opacity:0.6; }
}

/* REMOTE CONTROLLER SECTIONS */
.remote-section { margin-bottom: 12px; }
.remote-header {
  display: flex; align-items: center; gap: 10px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 18px; cursor: pointer;
  user-select: none; transition: border-color 0.2s;
}
.remote-header:hover { border-color: var(--accent); }
.remote-chevron {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 6px; flex-shrink: 0;
  background: var(--border); border: 1px solid #555;
  color: #fff; font-size: 12px; transition: transform 0.2s, background 0.2s;
}
.remote-header:hover .remote-chevron { background: #555; }
.remote-header.collapsed .remote-chevron { transform: rotate(-90deg); }
.remote-body {
  padding: 12px 0 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.remote-body.hidden { display: none; }
.remote-offline-msg {
  grid-column: 1 / -1; color: var(--muted); font-size: 13px; padding: 8px 0;
}

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


def nav(active: str, server_name: str = "") -> str:
    links = [("Dashboard", "/", "dashboard"), ("HTTP Generator", "/http-generator", "http-generator"), ("Settings", "/settings", "settings")]
    items = "".join(f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>' for label, href, key in links)
    name_chip = (f'<span style="font-weight:700;color:var(--accent);padding:4px 10px;'
                 f'border-right:1px solid var(--border);margin-right:4px;font-size:13px">'
                 f'{server_name}</span>') if server_name else ""
    return f'<nav class="nav">{name_chip}{items}</nav>'


def page(title: str, active: str, body: str, extra_js: str = "") -> str:
    cfg = load_config()
    server_name = cfg.get("server_name", "").strip()
    tab_title = f"{title} — {server_name}" if server_name else f"{title} — Elliott's Caspar Controller"
    name_inline = (f' — <span style="color:var(--accent);font-weight:600">{server_name}</span>') if server_name else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{tab_title}</title>
<style>{BASE_CSS}</style>
</head>
<body>
{nav(active, server_name)}
<div id="toast-container"></div>
<main class="main">
<h1 style="margin-bottom:24px;color:#fff">{title}{name_inline}</h1>
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
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
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
    amcp_base_port: Optional[int] = None
    web_port: Optional[int] = None
    startup_delay: Optional[int] = None
    video_mode: Optional[str] = None
    autostart_caspar: Optional[bool] = None
    media_path: Optional[str] = None
    server_name: Optional[str] = None
    web_password: Optional[str] = None
    web_password_enabled: Optional[bool] = None
    instances: Optional[list] = None
    remote_controllers: Optional[list] = None


class _LoginRequest(BaseModel):
    password: str


@app.get("/api/status")
def api_status():
    cfg = load_config()
    instances = cfg.get("instances", [])

    # Ping all instances in parallel so response time = slowest single ping, not sum
    live = {}
    def _ping(inst):
        live[inst["id"]] = AMCPClient(port=instance_amcp_port(cfg, inst)).ping()
    threads = [threading.Thread(target=_ping, args=(inst,), daemon=True) for inst in instances]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)

    instances_out = []
    for inst in instances:
        port = instance_amcp_port(cfg, inst)
        running = live.get(inst["id"], False)
        instances_out.append({
            "id": inst["id"],
            "name": inst["name"],
            "ndi_name": inst["ndi_name"],
            "type": inst.get("type", "html"),
            "url": inst.get("url", ""),
            "startup_command": inst.get("startup_command", ""),
            "amcp_port": port,
            "status": "live" if running else "stopped",
        })
    # Merge tally state into each instance
    tally = ndi_tally.get_tally()
    for inst in instances_out:
        t = tally.get(inst["ndi_name"], {})
        inst["on_program"] = t.get("program", False)
        inst["on_preview"] = t.get("preview", False)

    any_running = any(i["status"] == "live" for i in instances_out)
    needs_setup = not cfg.get("caspar_exe_path") or not instances
    return {
        "running": any_running,
        "version": __version__,
        "instances": instances_out,
        "needs_setup": needs_setup,
        "server_name": cfg.get("server_name", ""),
        "tally_available": ndi_tally.is_available(),
    }


@app.post("/api/server/start")
def api_server_start():
    global _managers
    cfg = load_config()
    instances = cfg.get("instances", [])
    if not instances:
        raise HTTPException(status_code=400, detail="No instances configured")

    # Write all config files and test pattern images before launching
    regenerate_all_instance_configs(cfg)
    ensure_test_pattern_images(cfg)

    # Always kill every running CasparCG before launching fresh.
    # Conditional kill (only when AMCP responds) misses instances on stale ports
    # and causes processes to accumulate across multiple Start clicks.
    CasparProcessManager._kill_all_caspar_instances()

    started = []
    errors = []

    # Sequential startup with 5s gap — ensures NDI sources appear one at a time
    # in config order so Tricaster/receivers lock onto the correct source.
    for i, inst in enumerate(instances):
        m = _make_manager(inst, cfg)
        _managers[inst["id"]] = m
        ok = m.start()
        if ok:
            res = _load_instance(inst, AMCPClient(port=instance_amcp_port(cfg, inst)))
            _log_event(f"Inst {inst['id']} ({inst['name']}) started → {res[:60]}")
            started.append(inst["id"])
            if i < len(instances) - 1:
                time.sleep(5)  # let NDI source settle before announcing the next one
        else:
            _log_event(f"Inst {inst['id']} ({inst['name']}) FAILED to start")
            errors.append(inst["id"])

    if not started:
        raise HTTPException(status_code=500, detail="All instances failed to start")
    msg = f"Started {len(started)}/{len(instances)} instances"
    if errors:
        msg += f" (failed: {errors})"
    _log_event(msg)
    return {"ok": True, "message": msg}


@app.post("/api/server/stop")
def api_server_stop():
    global _managers
    # Stop any managed instances
    threads = [threading.Thread(target=m.stop, daemon=True) for m in list(_managers.values())]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)
    _managers = {}
    # Kill any remaining CasparCG processes (e.g. started via the desktop GUI)
    CasparProcessManager._kill_all_caspar_instances()
    _log_event("All CasparCG instances stopped.")
    return {"ok": True}


def _restart_instance_bg(inst_id: int):
    """Stop the CasparCG process for one instance and relaunch it. Runs in a thread."""
    global _managers
    cfg = load_config()
    inst_map = {i["id"]: i for i in cfg.get("instances", [])}
    inst = inst_map.get(inst_id)
    if not inst:
        return
    port = instance_amcp_port(cfg, inst)
    # Kill whatever is on this port — works whether started from GUI or web
    if inst_id in _managers:
        _managers[inst_id].stop()
        _managers.pop(inst_id, None)
    else:
        CasparProcessManager._kill_caspar_on_port(port)
    regenerate_instance_config(cfg, inst)
    m = _make_manager(inst, cfg)
    _managers[inst_id] = m
    ok = m.start()
    if ok:
        res = _load_instance(inst, AMCPClient(port=port))
        _log_event(f"Inst {inst_id} ({inst['name']}) restarted → {res[:60]}")
    else:
        _log_event(f"Inst {inst_id} ({inst['name']}) failed to restart")
        _managers.pop(inst_id, None)


@app.post("/api/instance/{inst_id}/restart")
def api_instance_restart(inst_id: int):
    cfg = load_config()
    inst_map = {i["id"]: i for i in cfg.get("instances", [])}
    if inst_id not in inst_map:
        raise HTTPException(status_code=404, detail=f"Instance {inst_id} not found")
    name = inst_map[inst_id]["name"]
    _log_event(f"Restarting inst {inst_id} ({name})...")
    threading.Thread(target=_restart_instance_bg, args=(inst_id,), daemon=True).start()
    return {"ok": True, "message": f"Restarting {name}..."}


@app.post("/api/instance/all/restart")
def api_instance_restart_all():
    global _managers
    cfg = load_config()
    instances = cfg.get("instances", [])

    def _do_all():
        global _managers
        # Stop all managed instances in parallel
        threads = [threading.Thread(target=m.stop, daemon=True) for m in list(_managers.values())]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        # Kill any remaining (e.g. started from GUI)
        CasparProcessManager._kill_all_caspar_instances()
        _managers = {}
        regenerate_all_instance_configs(cfg)
        # Start sequentially with 5s gap for NDI ordering
        for i, inst in enumerate(instances):
            m = _make_manager(inst, cfg)
            _managers[inst["id"]] = m
            ok = m.start()
            if ok:
                res = _load_instance(inst, AMCPClient(port=instance_amcp_port(cfg, inst)))
                _log_event(f"Inst {inst['id']} ({inst['name']}) restarted → {res[:60]}")
                if i < len(instances) - 1:
                    time.sleep(5)
            else:
                _log_event(f"Inst {inst['id']} ({inst['name']}) failed to restart")
                _managers.pop(inst["id"], None)

    _log_event("Restarting all instances...")
    threading.Thread(target=_do_all, daemon=True).start()
    return {"ok": True, "message": "Restarting all instances..."}


@app.post("/api/instance/{inst_id}/stop")
def api_instance_stop(inst_id: int):
    global _managers
    cfg = load_config()
    inst_map = {i["id"]: i for i in cfg.get("instances", [])}
    if inst_id not in inst_map:
        raise HTTPException(status_code=404, detail=f"Instance {inst_id} not found")
    inst = inst_map[inst_id]
    port = instance_amcp_port(cfg, inst)

    def _do_stop():
        if inst_id in _managers:
            _managers[inst_id].stop()
            _managers.pop(inst_id, None)
        else:
            CasparProcessManager._kill_caspar_on_port(port)
        _log_event(f"Inst {inst_id} ({inst['name']}) stopped.")

    threading.Thread(target=_do_stop, daemon=True).start()
    return {"ok": True, "message": f"Stopping {inst['name']}..."}


class AMCPCommandRequest(BaseModel):
    command: str


@app.post("/api/instance/{inst_id}/amcp")
def api_instance_amcp(inst_id: int, req: AMCPCommandRequest):
    cfg = load_config()
    inst_map = {i["id"]: i for i in cfg.get("instances", [])}
    if inst_id not in inst_map:
        raise HTTPException(status_code=404, detail=f"Instance {inst_id} not found")
    port = instance_amcp_port(cfg, inst_map[inst_id])
    client = AMCPClient(port=port)
    res = client.send(req.command.strip())
    _log_event(f"Inst {inst_id} AMCP: {req.command[:60]} → {res[:60]}")
    return {"ok": True, "response": res}


@app.get("/api/load")
def api_load_clip(instance: str, clip: str, loop: bool = True):
    """Load a clip into a named media instance via HTTP GET.

    Usage: GET /api/load?instance=Clipplayer&clip=MYCLIP
    Optional: &loop=false to play once without looping.

    Designed for external triggers (hardware controllers, automation systems).
    """
    cfg = load_config()
    inst = next(
        (i for i in cfg.get("instances", []) if i["name"].lower() == instance.lower()),
        None,
    )
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance}' not found")
    if inst.get("type", "html") != "media":
        raise HTTPException(
            status_code=400,
            detail=f"Instance '{instance}' is not a media type — only media instances support clip loading",
        )
    port = instance_amcp_port(cfg, inst)
    client = AMCPClient(port=port)
    loop_str = " LOOP" if loop else ""
    cmd = f'PLAY 1-1 "{clip}"{loop_str}'
    res = client.send(cmd)
    _log_event(f"HTTP load: {instance} → {cmd} → {res[:60]}")
    return {"ok": True, "instance": instance, "clip": clip, "command": cmd, "response": res}


@app.get("/api/instance/{inst_id}/load")
def api_instance_load_clip(inst_id: int, clip: str, loop: bool = True):
    """Load a clip into a media instance by ID via HTTP GET.

    Usage: GET /api/instance/6/load?clip=MYCLIP
    """
    cfg = load_config()
    inst_map = {i["id"]: i for i in cfg.get("instances", [])}
    if inst_id not in inst_map:
        raise HTTPException(status_code=404, detail=f"Instance {inst_id} not found")
    inst = inst_map[inst_id]
    if inst.get("type", "html") != "media":
        raise HTTPException(status_code=400, detail=f"Instance {inst_id} is not a media type")
    port = instance_amcp_port(cfg, inst)
    client = AMCPClient(port=port)
    loop_str = " LOOP" if loop else ""
    cmd = f'PLAY 1-1 "{clip}"{loop_str}'
    res = client.send(cmd)
    _log_event(f"HTTP load: Inst {inst_id} ({inst['name']}) → {cmd} → {res[:60]}")
    return {"ok": True, "instance": inst["name"], "clip": clip, "command": cmd, "response": res}


@app.get("/api/media")
def api_media():
    cfg = load_config()
    custom_media = cfg.get("media_path", "").strip()
    if custom_media and os.path.isdir(custom_media):
        media_dir = custom_media
    else:
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
    # Renumber instances by array order so the web UI can reorder freely
    if "instances" in data:
        for i, inst in enumerate(data["instances"], start=1):
            inst["id"] = i
    cfg.update(data)
    save_config(cfg)
    regenerate_all_instance_configs(cfg)
    _refresh_tally_monitors()
    _log_event("Config saved and instance configs regenerated.")
    return {"ok": True}


@app.get("/api/config/export")
def api_config_export():
    import json as _json
    cfg = load_config()
    content = _json.dumps(cfg, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=elliotts_caspar_config.json"},
    )


@app.post("/api/config/import")
async def api_config_import(request: Request):
    import json as _json
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Config must be a JSON object")
    save_config(body)
    regenerate_all_instance_configs(body)
    _log_event("Config imported via web UI.")
    return {"ok": True}


@app.get("/api/remotes")
def api_remotes():
    cfg = load_config()
    remotes = cfg.get("remote_controllers", [])
    if not remotes:
        return {"remotes": []}

    def _fetch(idx: int, remote: dict) -> dict:
        global _remote_name_cache
        url = remote.get("url", "").rstrip("/")
        try:
            # 6s timeout: remote /api/status pings up to 6 AMCP ports in parallel
            # (each join has a 3s timeout) so 5s gives a comfortable margin
            r = _requests.get(f"{url}/api/status", timeout=6)
            data = r.json()
            server_name = data.get("server_name", "").strip()
            if not server_name and url not in _remote_name_cache:
                # Only fetch config the first time — afterwards use the cache
                try:
                    cfg_r = _requests.get(f"{url}/api/config", timeout=4)
                    server_name = cfg_r.json().get("server_name", "").strip()
                except Exception:
                    pass
            if server_name:
                _remote_name_cache[url] = server_name
            display_name = server_name or _remote_name_cache.get(url) or url
            return {
                "idx": idx, "url": url,
                "display_name": display_name,
                "online": True, "status": data,
            }
        except Exception:
            return {
                "idx": idx, "url": url,
                "display_name": _remote_name_cache.get(url) or url,
                "online": False, "status": None,
            }

    results: list = [None] * len(remotes)
    with ThreadPoolExecutor(max_workers=max(len(remotes), 1)) as ex:
        futs = {ex.submit(_fetch, i, r): i for i, r in enumerate(remotes)}
        for f in futs:
            results[futs[f]] = f.result()
    return {"remotes": results}


@app.get("/api/remote/{idx}/media")
def api_remote_media_proxy(idx: int):
    cfg = load_config()
    remotes = cfg.get("remote_controllers", [])
    if idx < 0 or idx >= len(remotes):
        raise HTTPException(status_code=404, detail=f"Remote {idx} not found")
    url = remotes[idx].get("url", "").rstrip("/")
    try:
        r = _requests.get(f"{url}/api/media", timeout=5)
        return r.json()
    except Exception:
        return {"clips": [], "error": "Could not reach remote"}


class _RemoteTestRequest(BaseModel):
    url: str


@app.post("/api/remote/test")
def api_remote_test(req: _RemoteTestRequest):
    url = req.url.rstrip("/")
    try:
        r = _requests.get(f"{url}/api/status", timeout=3)
        data = r.json()
        return {"online": True, "server_name": data.get("server_name", ""), "version": data.get("version", "")}
    except Exception:
        return {"online": False}


class _RemoteProxyRequest(BaseModel):
    path: str
    body: Optional[dict] = None


@app.post("/api/remote/{idx}/proxy")
def api_remote_proxy(idx: int, req: _RemoteProxyRequest):
    cfg = load_config()
    remotes = cfg.get("remote_controllers", [])
    if idx < 0 or idx >= len(remotes):
        raise HTTPException(status_code=404, detail=f"Remote {idx} not found")
    url = remotes[idx].get("url", "").rstrip("/")
    try:
        if req.body is not None:
            r = _requests.post(f"{url}{req.path}", json=req.body, timeout=5)
        else:
            r = _requests.post(f"{url}{req.path}", timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Remote unreachable: {e}")


@app.get("/login", response_class=HTMLResponse)
def page_login(error: str = ""):
    cfg = load_config()
    server_name = cfg.get("server_name", "").strip()
    name_html = (f'<p style="color:var(--muted);font-size:14px;margin-bottom:24px">{server_name}</p>'
                 if server_name else '<div style="margin-bottom:24px"></div>')
    error_html = (f'<p style="color:var(--error);font-size:13px;margin-bottom:12px">{error}</p>'
                  if error else "")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login — Elliott's Caspar Controller</title>
<style>{BASE_CSS}</style></head>
<body style="display:flex;align-items:center;justify-content:center;min-height:100vh">
<div class="card" style="width:380px;padding:32px">
  <h1 style="margin-bottom:4px">Elliott's Caspar Controller</h1>
  {name_html}
  {error_html}
  <div class="form-group">
    <label>Password</label>
    <input type="password" id="pw" placeholder="Enter password" autofocus>
  </div>
  <button class="btn btn-primary" style="width:100%" onclick="doLogin()">Sign In</button>
  <p style="color:var(--muted);font-size:12px;margin-top:16px;text-align:center">
    Connecting from this machine? Use <a href="http://127.0.0.1:{cfg.get('web_port', 5280)}">localhost</a> to bypass.
  </p>
</div>
<script>
function doLogin() {{
  const pw = document.getElementById('pw').value;
  fetch('/login', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{password:pw}})}})
    .then(r => r.json().then(d => ({{ok:r.ok,d}})))
    .then(({{ok,d}}) => {{ if (ok) location.href='/'; else document.querySelector('.card').insertAdjacentHTML('afterbegin','<p style="color:var(--error);margin-bottom:12px">'+d.detail+'</p>'); }});
}}
document.addEventListener('keydown', e => {{ if (e.key==='Enter') doLogin(); }});
</script>
</body></html>""")


@app.post("/login")
def api_login(req: _LoginRequest, response: Response):
    cfg = load_config()
    if req.password == cfg.get("web_password", ""):
        token = secrets.token_urlsafe(32)
        _sessions.add(token)
        response.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400 * 30)
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Incorrect password")


@app.post("/logout")
def api_logout(request: Request, response: Response):
    _sessions.discard(request.cookies.get("session", ""))
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/log")
def api_log():
    with _log_lock:
        return {"log": list(_log)}


@app.get("/api/tally")
def api_tally():
    return {
        "available": ndi_tally.is_available(),
        "tally": ndi_tally.get_tally(),
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def page_dashboard():
    body = """
<div id="setup-banner" style="display:none;background:rgba(245,158,11,0.12);border:2px solid var(--warning);border-radius:12px;padding:20px 24px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
    <span style="font-size:22px">⚙</span>
    <h2 style="color:var(--warning)">Setup Required</h2>
  </div>
  <p style="color:var(--muted);margin-bottom:12px">
    CasparCG is not configured yet. Go to <strong style="color:var(--text)">Settings</strong> to set the path to <code>casparcg.exe</code> and add your output instances.
  </p>
  <a href="/settings" class="btn btn-warning">Go to Settings →</a>
</div>

<div class="card">
  <div class="card-header">
    <div style="display:flex;align-items:center">
      <span class="pulse" id="pulse"></span>
      <span id="server-status-label">Checking...</span>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-success" id="btn-start" onclick="serverAction('start')">Start All</button>
      <button class="btn btn-danger"  onclick="serverAction('stop')">Stop All</button>
    </div>
  </div>
</div>

<div id="instance-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:16px"></div>

<div id="remotes-section"></div>

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
    const regular = _mediaClips.filter(c => !c.startsWith('TEST_'));
    const tests   = _mediaClips.filter(c =>  c.startsWith('TEST_'));
    document.querySelectorAll('[id^="media_"]').forEach(sel => {
      const current = sel.value;
      let html = '<option value="">— pick a clip —</option>';
      html += regular.map(c => `<option value="${c}"${c===current?' selected':''}>${c}</option>`).join('');
      if (tests.length) {
        html += '<option disabled>─── Test Patterns ───</option>';
        html += tests.map(c => `<option value="${c}"${c===current?' selected':''}>${c}</option>`).join('');
      }
      sel.innerHTML = html;
    });
  });
}

function onMediaSelect(id) {
  const clip = document.getElementById('media_' + id).value;
  if (!clip) return;
  document.getElementById('amcp_' + id).value = `PLAY 1-1 "${clip}" LOOP`;
}

function renderInstances(instances) {
  const g = document.getElementById('instance-grid');
  g.innerHTML = instances.map(inst => {
    const isHtml = inst.type === 'html' || !inst.type;
    const typeBadge = isHtml
      ? '<span class="badge badge-neutral" style="font-size:10px">HTML5</span>'
      : '<span class="badge badge-warning" style="font-size:10px">Media</span>';

    const tallyClass = inst.on_program ? 'tally-program' : inst.on_preview ? 'tally-preview' : '';
    const tallyBadge = inst.on_program
      ? '<span class="tally-badge-program">● LIVE</span>'
      : inst.on_preview
        ? '<span class="tally-badge-preview">◐ PVW</span>'
        : '';

    const sourceInfo = '';
    const loadUrl = '';
    const amcpRow = !isHtml ? `
      <div style="display:flex;gap:4px;margin-top:4px">
        <select id="media_${inst.id}"
                style="flex:1;font-size:11px;padding:5px 8px;min-width:0;background:var(--input-bg);color:var(--muted);border:1px solid var(--border);border-radius:6px"
                onchange="onMediaSelect(${inst.id})">
          <option value="">— pick a clip —</option>
        </select>
      </div>
      <div style="display:flex;gap:4px;margin-top:4px">
        <input type="text" id="amcp_${inst.id}" placeholder='PLAY 1-1 "CLIP" LOOP'
               style="flex:1;font-size:11px;padding:5px 8px;min-width:0">
        <button class="btn btn-secondary btn-sm" style="padding:0 10px;flex-shrink:0"
                onclick="sendAmcp(${inst.id})">Send</button>
      </div>` : '';
    return `
    <div class="channel-card ${tallyClass}">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div class="ch-num">Instance ${inst.id} &nbsp;<span style="color:var(--muted);font-size:10px">:${inst.amcp_port}</span></div>
        <div style="display:flex;gap:4px;align-items:center">${tallyBadge}${typeBadge}</div>
      </div>
      <div class="ch-name">${inst.name}</div>
      <div class="ch-ndi">NDI: ${inst.ndi_name}</div>
      ${sourceInfo}
      ${loadUrl}
      <span class="badge ${inst.status === 'live' ? 'badge-success' : 'badge-error'}">${inst.status}</span>
      ${inst.status === 'live'
        ? `<button class="btn btn-danger btn-sm" style="width:100%" onclick="stopInstance(${inst.id}, '${inst.name}')">■ Stop</button>`
        : `<button class="btn btn-success btn-sm" style="width:100%" onclick="startInstance(${inst.id}, '${inst.name}')">▶ Start</button>`
      }
      ${amcpRow}
    </div>`;
  }).join('');
}

// Track whether a media select dropdown is currently open
let _dropdownOpen = false;
document.addEventListener('mousedown', e => { if (e.target.tagName === 'SELECT') _dropdownOpen = true; });
document.addEventListener('change',    e => { if (e.target.tagName === 'SELECT') _dropdownOpen = false; });
document.addEventListener('focusout',  e => { if (e.target.tagName === 'SELECT') _dropdownOpen = false; });

function updateStatus() {
  api('/api/status').then(data => {
    // Check HERE, just before touching the DOM — not before the async fetch
    const skipRender = _dropdownOpen;

    const running = data.running;
    document.getElementById('setup-banner').style.display = data.needs_setup ? 'block' : 'none';
    document.getElementById('pulse').className = 'pulse ' + (running ? 'pulse-green' : 'pulse-red');
    const liveCount = data.instances.filter(i => i.status === 'live').length;
    const total = data.instances.length;
    document.getElementById('server-status-label').textContent = running
      ? `CasparCG Running — ${liveCount}/${total} instances`
      : 'CasparCG Stopped';

    const btnStart = document.getElementById('btn-start');
    if (btnStart) {
      const allRunning = total > 0 && liveCount === total;
      btnStart.disabled = allRunning;
      btnStart.style.opacity = allRunning ? '0.4' : '';
      btnStart.style.cursor  = allRunning ? 'not-allowed' : '';
      btnStart.textContent = allRunning
        ? `All Running (${total}/${total})`
        : liveCount > 0
          ? `Start Remaining (${total - liveCount})`
          : 'Start All';
    }

    if (!skipRender) {
      // Preserve user input across re-renders
      const saved = {};
      document.querySelectorAll('[id^="amcp_"], [id^="media_"]').forEach(el => {
        if (el.value) saved[el.id] = el.value;
      });
      renderInstances(data.instances);
      loadMediaClips();
      Object.entries(saved).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) el.value = val;
      });
    }

    if (lastRunning !== null && lastRunning !== running)
      toast(running ? 'CasparCG is now running' : 'CasparCG stopped', running ? 'success' : 'warning');
    lastRunning = running;
  });
  api('/api/log').then(data => {
    document.getElementById('log-box').innerHTML = data.log.slice().reverse().map(l => `<p>${l}</p>`).join('');
  });
}

function serverAction(action) {
  if (action === 'start') {
    const btn = document.getElementById('btn-start');
    if (btn && btn.disabled) return;
  }
  toast('Sending ' + action + '...', 'info');
  api('/api/server/' + action, 'POST').then(d => {
    toast(d.message || (action + ' OK'), 'success');
    updateStatus();
  }).catch(() => toast('Failed to ' + action, 'error'));
}

function startInstance(id, name) {
  toast('Starting ' + name + '...', 'info');
  api('/api/instance/' + id + '/restart', 'POST').then(d => {
    toast(d.message || (name + ' starting...'), 'info');
    let attempts = 0;
    const poll = setInterval(() => {
      attempts++;
      updateStatus();
      api('/api/status').then(data => {
        const inst = data.instances.find(i => i.id === id);
        if (inst && inst.status === 'live') {
          clearInterval(poll);
          toast(name + ' is live', 'success');
        } else if (attempts > 90) {
          clearInterval(poll);
          toast(name + ' took too long — check logs', 'warning');
        }
      });
    }, 2000);
  }).catch(() => toast('Failed to start ' + name, 'error'));
}

function stopInstance(id, name) {
  toast('Stopping ' + name + '...', 'warning');
  api('/api/instance/' + id + '/stop', 'POST').then(() => {
    toast(name + ' stopped', 'success');
    updateStatus();
  }).catch(() => toast('Failed to stop ' + name, 'error'));
}

function sendAmcp(id) {
  const input = document.getElementById('amcp_' + id);
  const cmd = input.value.trim();
  if (!cmd) { toast('Enter an AMCP command first', 'warning'); return; }
  api('/api/instance/' + id + '/amcp', 'POST', { command: cmd }).then(d => {
    toast('Inst' + id + ': ' + (d.response || 'OK'), 'success');
  }).catch(() => toast('Failed to send AMCP', 'error'));
}

// ── Remote Controllers ─────────────────────────────────────────

const _remoteStatusCache = {};  // idx -> last known status object

function _remoteCollapseKey(idx) { return 'remote_collapsed_' + idx; }

function _isCollapsed(idx) {
  return localStorage.getItem(_remoteCollapseKey(idx)) === '1';
}

function toggleRemote(idx) {
  const header = document.getElementById('rh_' + idx);
  const body   = document.getElementById('rb_' + idx);
  if (!header || !body) return;
  const collapsed = body.classList.contains('hidden');
  if (collapsed) {
    body.classList.remove('hidden');
    header.classList.remove('collapsed');
    localStorage.removeItem(_remoteCollapseKey(idx));
  } else {
    body.classList.add('hidden');
    header.classList.add('collapsed');
    localStorage.setItem(_remoteCollapseKey(idx), '1');
  }
}

function remoteInstanceCard(rem, inst) {
  const isLive = inst.status === 'live';
  const isMedia = inst.type === 'media';
  const tallyClass = inst.on_program ? 'tally-program' : inst.on_preview ? 'tally-preview' : '';
  const tallyBadge = inst.on_program
    ? '<span class="tally-badge-program">● LIVE</span>'
    : inst.on_preview ? '<span class="tally-badge-preview">◐ PVW</span>' : '';
  const actionBtn = isLive
    ? `<button class="btn btn-danger btn-sm" style="width:100%"
         onclick="remoteInstanceAction(${rem.idx}, ${inst.id}, 'stop')">■ Stop</button>`
    : `<button class="btn btn-success btn-sm" style="width:100%"
         onclick="remoteInstanceAction(${rem.idx}, ${inst.id}, 'restart')">▶ Start</button>`;
  const mediaRow = isMedia ? `
    <div style="display:flex;gap:4px;margin-top:4px">
      <select id="rmedia_${rem.idx}_${inst.id}"
              style="flex:1;font-size:11px;padding:5px 8px;min-width:0;background:var(--input-bg);color:var(--muted);border:1px solid var(--border);border-radius:6px"
              onchange="onRemoteMediaSelect(${rem.idx},${inst.id})">
        <option value="">— pick a clip —</option>
      </select>
    </div>
    <div style="display:flex;gap:4px;margin-top:4px">
      <input type="text" id="ramcp_${rem.idx}_${inst.id}" placeholder='PLAY 1-1 "CLIP" LOOP'
             style="flex:1;font-size:11px;padding:5px 8px;min-width:0">
      <button class="btn btn-secondary btn-sm" style="padding:0 10px;flex-shrink:0"
              onclick="sendRemoteAmcp(${rem.idx},${inst.id})">Send</button>
    </div>` : '';
  return `
  <div class="channel-card ${tallyClass}">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="ch-num">Instance ${inst.id} &nbsp;<span style="color:var(--muted);font-size:10px">:${inst.amcp_port}</span></div>
      ${tallyBadge}
    </div>
    <div class="ch-name">${inst.name}</div>
    <div class="ch-ndi">NDI: ${inst.ndi_name}</div>
    <span class="badge ${isLive ? 'badge-success' : 'badge-error'}">${inst.status}</span>
    ${actionBtn}
    ${mediaRow}
  </div>`;
}

function renderRemotes(remotes) {
  const sec = document.getElementById('remotes-section');
  if (!sec) return;
  if (!remotes || remotes.length === 0) { sec.innerHTML = ''; return; }

  // Build a header row if we don't have one yet
  let html = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
    <h2 style="color:var(--muted);font-size:14px;font-weight:600;text-transform:uppercase;letter-spacing:.5px">Remote Controllers</h2>
  </div>`;

  remotes.forEach(rem => {
    if (!rem) return;
    const collapsed = _isCollapsed(rem.idx);
    // Cache status when online so we can show stale data when offline
    if (rem.online && rem.status) _remoteStatusCache[rem.idx] = rem.status;
    const effectiveStatus = rem.online ? rem.status : _remoteStatusCache[rem.idx];

    const liveCount = effectiveStatus
      ? effectiveStatus.instances.filter(i => i.status === 'live').length : 0;
    const total = effectiveStatus ? effectiveStatus.instances.length : 0;

    const statusBadge = rem.online
      ? `<span class="badge badge-success" style="font-size:11px;white-space:nowrap">● Online</span>`
      : `<span class="badge badge-error"   style="font-size:11px;white-space:nowrap">● Offline</span>`;

    const liveChip = effectiveStatus
      ? `<span style="background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.3);border-radius:20px;
                      padding:4px 12px;font-size:13px;color:var(--success);white-space:nowrap;font-weight:600">
           ${liveCount}/${total} live
         </span>` : '';

    const versionChip = effectiveStatus
      ? `<span style="background:var(--input-bg);border:1px solid var(--border);border-radius:20px;
                      padding:4px 12px;font-size:12px;color:var(--muted);white-space:nowrap">
           v${effectiveStatus.version || '?'}
         </span>` : '';

    // Always show Start All so instances can be restarted even when CasparCG is stopped
    // (the web UI on the remote is still running even when CasparCG instances are stopped)
    const actionBtns = `
      <button class="btn btn-success btn-sm"
        onclick="event.stopPropagation();remoteServerAction(${rem.idx},'start')">Start All</button>
      ${rem.online ? `<button class="btn btn-danger btn-sm"
        onclick="event.stopPropagation();remoteServerAction(${rem.idx},'stop')">Stop All</button>` : ''}`;

    html += `
    <div class="remote-section">
      <div class="remote-header ${collapsed ? 'collapsed' : ''}" id="rh_${rem.idx}"
           onclick="toggleRemote(${rem.idx})"
           style="justify-content:space-between">
        <div style="display:flex;align-items:center;gap:10px;min-width:0;flex:1">
          <span class="remote-chevron">▼</span>
          <span style="font-weight:700;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${rem.display_name}</span>
          ${statusBadge}
          ${liveChip}
          ${versionChip}
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0;margin-left:16px" onclick="event.stopPropagation()">
          ${actionBtns}
        </div>
      </div>
      <div class="remote-body ${collapsed ? 'hidden' : ''}" id="rb_${rem.idx}">
        ${effectiveStatus && effectiveStatus.instances.length
          ? effectiveStatus.instances.map(inst => remoteInstanceCard(rem, inst)).join('')
            + (!rem.online ? '<div class="remote-offline-msg" style="grid-column:1/-1;margin-top:8px">⚠ Controller offline — showing last known state. Start All will attempt to reconnect.</div>' : '')
          : rem.online
            ? '<div class="remote-offline-msg">No instances configured on this controller.</div>'
            : `<div class="remote-offline-msg">Cannot reach ${rem.url} — check that the controller is running and the URL is correct.</div>`
        }
      </div>
    </div>`;
  });

  sec.innerHTML = html;
  // Populate clip dropdowns for media instances on each online remote
  remotes.forEach(rem => {
    if (rem && rem.online && rem.status) populateRemoteMediaDropdowns(rem.idx, rem.status.instances);
  });
}

function updateRemotes() {
  api('/api/remotes').then(data => renderRemotes(data.remotes || []));
}

function remoteServerAction(idx, action) {
  toast('Sending ' + action + ' to remote...', 'info');
  api('/api/remote/' + idx + '/proxy', 'POST', { path: '/api/server/' + action })
    .then(d => { toast(d.message || action + ' OK', 'success'); updateRemotes(); })
    .catch(() => toast('Remote action failed', 'error'));
}

function remoteInstanceAction(idx, instId, action) {
  api('/api/remote/' + idx + '/proxy', 'POST', { path: '/api/instance/' + instId + '/' + action })
    .then(() => { setTimeout(updateRemotes, 2000); updateRemotes(); })
    .catch(() => toast('Remote action failed', 'error'));
}

const _remoteClips = {};
function loadRemoteClips(idx) {
  if (_remoteClips[idx]) return Promise.resolve(_remoteClips[idx]);
  return api('/api/remote/' + idx + '/media').then(data => {
    _remoteClips[idx] = data.clips || [];
    return _remoteClips[idx];
  });
}

function populateRemoteMediaDropdowns(idx, instances) {
  const mediaInsts = instances.filter(i => i.type === 'media');
  if (!mediaInsts.length) return;
  loadRemoteClips(idx).then(clips => {
    const regular = clips.filter(c => !c.startsWith('TEST_'));
    const tests   = clips.filter(c =>  c.startsWith('TEST_'));
    mediaInsts.forEach(inst => {
      const sel = document.getElementById('rmedia_' + idx + '_' + inst.id);
      if (!sel) return;
      let html = '<option value="">— pick a clip —</option>';
      html += regular.map(c => `<option value="${c}">${c}</option>`).join('');
      if (tests.length) {
        html += '<option disabled>─── Test Patterns ───</option>';
        html += tests.map(c => `<option value="${c}">${c}</option>`).join('');
      }
      sel.innerHTML = html;
    });
  });
}

function onRemoteMediaSelect(idx, instId) {
  const clip = document.getElementById('rmedia_' + idx + '_' + instId)?.value;
  if (!clip) return;
  const inp = document.getElementById('ramcp_' + idx + '_' + instId);
  if (inp) inp.value = `PLAY 1-1 "${clip}" LOOP`;
}

function sendRemoteAmcp(idx, instId) {
  const input = document.getElementById('ramcp_' + idx + '_' + instId);
  const cmd = input?.value?.trim();
  if (!cmd) { toast('Enter an AMCP command first', 'warning'); return; }
  api('/api/remote/' + idx + '/proxy', 'POST', { path: '/api/instance/' + instId + '/amcp', body: { command: cmd } })
    .then(d => toast('Remote: ' + (d.response || 'OK'), 'success'))
    .catch(() => toast('Remote AMCP failed', 'error'));
}

updateStatus();
updateRemotes();
setInterval(updateStatus, 4000);
setInterval(updateRemotes, 5000);
"""
    return HTMLResponse(page("Dashboard", "dashboard", body, js))




def _get_network_ip() -> str:
    import socket as _socket
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


@app.get("/http-generator", response_class=HTMLResponse)
def page_http_generator():
    cfg = load_config()
    network_base = f"http://{_get_network_ip()}:{cfg.get('web_port', 5280)}"
    body = """
<p style="color:var(--muted);margin-bottom:20px">
  Select an instance and clip to generate a ready-to-use HTTP GET URL.
  Any device that can fire an HTTP request — browser, automation system, hardware controller — can use it to load a clip instantly.
</p>

<div class="card">
  <h2 style="margin-bottom:20px">URL Builder</h2>

  <div class="grid-2" style="margin-bottom:16px">
    <div class="form-group" style="margin:0">
      <label>Media Instance</label>
      <select id="gen-instance" onchange="onSelectionChange()">
        <option value="">— select instance —</option>
      </select>
    </div>
    <div class="form-group" style="margin:0">
      <label>Clip</label>
      <select id="gen-clip" onchange="onSelectionChange()">
        <option value="">— select clip —</option>
      </select>
    </div>
  </div>

  <div class="form-group" style="margin-bottom:20px">
    <label>Playback</label>
    <select id="gen-loop" onchange="onSelectionChange()" style="max-width:220px">
      <option value="">Loop continuously (default)</option>
      <option value="false">Play once then stop</option>
    </select>
  </div>

  <div id="gen-url-container" style="display:none">
    <label style="margin-bottom:8px;display:block">Generated URL — click to copy</label>
    <div id="gen-url" onclick="copyUrl()"
         style="background:var(--input-bg);border:2px solid var(--border);border-radius:10px;
                padding:16px 20px;font-family:Consolas,monospace;font-size:13px;
                cursor:pointer;word-break:break-all;color:var(--accent);
                transition:border-color 0.2s,background 0.2s"
         onmouseenter="this.style.borderColor='var(--accent)'"
         onmouseleave="this.style.borderColor='var(--border)'"
         title="Click to copy to clipboard">
    </div>
    <p id="gen-copied"
       style="color:var(--success);font-size:13px;margin-top:8px;display:none;font-weight:600">
      ✓ Copied to clipboard
    </p>
  </div>
</div>

<div class="card" style="margin-top:16px">
  <h3 style="margin-bottom:12px">How it works</h3>
  <p style="color:var(--muted);font-size:13px;line-height:1.7">
    Send the generated URL as an HTTP GET request from any device on the same network.
    The app will forward the clip to the selected CasparCG instance immediately.<br><br>
    Works from a web browser, <code>curl</code>, a Companion button, a touchscreen panel,
    or any automation system that supports HTTP requests.
  </p>
  <div style="margin-top:12px;background:var(--input-bg);border-radius:8px;padding:12px 16px;font-family:Consolas,monospace;font-size:12px;color:var(--muted)">
    curl "NETWORK_BASE/api/load?instance=Clipplayer&clip=MYCLIP"
  </div>
</div>
"""
    js = """
let _mediaInstances = [];
let _clips = [];

function loadData() {
  api('/api/status').then(data => {
    _mediaInstances = (data.instances || []).filter(i => i.type === 'media');
    const sel = document.getElementById('gen-instance');
    if (_mediaInstances.length === 0) {
      sel.innerHTML = '<option value="">No media instances configured</option>';
    } else {
      sel.innerHTML = '<option value="">— select instance —</option>' +
        _mediaInstances.map(i => `<option value="${i.name}">${i.name}</option>`).join('');
    }
    onSelectionChange();
  });
  api('/api/media').then(data => {
    _clips = data.clips || [];
    const sel = document.getElementById('gen-clip');
    sel.innerHTML = '<option value="">— select clip —</option>' +
      _clips.map(c => `<option value="${c}">${c}</option>`).join('');
    onSelectionChange();
  });
}

function onSelectionChange() {
  const instance = document.getElementById('gen-instance').value;
  const clip     = document.getElementById('gen-clip').value;
  const loopVal  = document.getElementById('gen-loop').value;
  const container = document.getElementById('gen-url-container');
  const urlEl     = document.getElementById('gen-url');

  if (!instance || !clip) {
    container.style.display = 'none';
    return;
  }

  const base = 'NETWORK_BASE';
  let url = base + '/api/load?instance=' + encodeURIComponent(instance) + '&clip=' + encodeURIComponent(clip);
  if (loopVal === 'false') url += '&loop=false';

  urlEl.textContent = url;
  container.style.display = 'block';
  document.getElementById('gen-copied').style.display = 'none';
}

function copyUrl() {
  const url = document.getElementById('gen-url').textContent.trim();
  if (!url) return;
  const copied = () => {
    const el = document.getElementById('gen-copied');
    el.style.display = 'block';
    document.getElementById('gen-url').style.background = 'rgba(0,188,212,0.1)';
    setTimeout(() => {
      el.style.display = 'none';
      document.getElementById('gen-url').style.background = 'var(--input-bg)';
    }, 2000);
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(url).then(copied).catch(() => fallbackCopy(url, copied));
  } else {
    fallbackCopy(url, copied);
  }
}

function fallbackCopy(text, cb) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { document.execCommand('copy'); cb(); } catch(e) {}
  document.body.removeChild(ta);
}

loadData();
"""
    body = body.replace("NETWORK_BASE", network_base)
    js   = js.replace("NETWORK_BASE", network_base)
    return HTMLResponse(page("HTTP Generator", "http-generator", body, js))


@app.get("/settings", response_class=HTMLResponse)
def page_settings():
    body = """
<!-- Server Identity -->
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-bottom:16px">Server Identity</h2>
  <div style="display:flex;gap:10px;align-items:flex-end">
    <div class="form-group" style="flex:1;margin:0">
      <label>Server Name <span style="color:var(--muted);font-size:11px">(shown in the nav bar and browser tab)</span></label>
      <input type="text" id="server_name" placeholder="e.g. GFX PC, Studio A, Backup">
    </div>
    <button class="btn btn-primary" onclick="saveServerName()" style="flex-shrink:0">Save</button>
  </div>
</div>

<!-- Web UI Password -->
<div class="card" style="margin-bottom:16px">
  <h2 style="margin-bottom:12px">Web UI Password</h2>
  <div style="display:flex;gap:10px;align-items:flex-end">
    <div class="form-group" style="flex:1;margin:0">
      <label>Password <span style="color:var(--muted);font-size:11px">(leave blank to disable — this machine always bypasses, only remote devices are blocked)</span></label>
      <input type="password" id="web_password" placeholder="Leave blank to disable">
    </div>
    <button class="btn btn-primary" onclick="savePassword()" style="flex-shrink:0">Save</button>
  </div>
</div>

<!-- CasparCG Executable -->
<div class="card" style="margin-bottom:16px" id="exe-card">
  <h2 style="margin-bottom:4px">CasparCG Executable</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:16px">
    Download CasparCG Server from
    <a href="https://github.com/CasparCG/server/releases" target="_blank">github.com/CasparCG/server/releases</a>
    and extract it, then point to the <code>casparcg.exe</code> inside.
  </p>
  <div id="exe-warning" style="display:none;background:rgba(245,158,11,0.12);border:1px solid var(--warning);border-radius:8px;padding:10px 14px;margin-bottom:12px;color:var(--warning);font-size:13px">
    ⚠ CasparCG path is not set — the app cannot start CasparCG until this is configured.
  </div>
  <div style="display:flex;gap:10px;align-items:flex-end">
    <div class="form-group" style="flex:1;margin:0">
      <label>Path to casparcg.exe</label>
      <input type="text" id="caspar_exe_path" placeholder="C:\\CasparCG\\casparcg.exe">
    </div>
    <button class="btn btn-primary" onclick="saveExePath()" style="flex-shrink:0">Save Path</button>
  </div>
  <p style="color:var(--muted);font-size:12px;margin-top:8px">
    Per-instance config files are written to the same folder as the exe when CasparCG is started.
  </p>
</div>

<!-- Output settings + instance editor -->
<div class="card" id="settings-form">
  <h2 style="margin-bottom:16px">Output Settings</h2>
  <div class="grid-2">
    <div class="form-group">
      <label>Video Mode</label>
      <select id="video_mode">
        <option value="1080p2500">1080p 25fps</option>
        <option value="1080p5000">1080p 50fps</option>
        <option value="1080p2997">1080p 29.97fps</option>
        <option value="1080p3000">1080p 30fps</option>
        <option value="1080p5994">1080p 59.94fps</option>
        <option value="1080p6000">1080p 60fps</option>
        <option value="1080i5000">1080i 50i</option>
        <option value="1080i5994">1080i 59.94i</option>
        <option value="1080i6000">1080i 60i</option>
      </select>
    </div>
    <div class="form-group">
      <label>Base AMCP Port <span style="color:var(--muted);font-size:11px">(instances get base, base+1, base+2…)</span></label>
      <input type="number" id="amcp_base_port" value="5250" oninput="onBasePortChange()">
    </div>
    <div class="form-group">
      <label>Web UI Port</label>
      <input type="number" id="web_port" value="5280">
    </div>
    <div class="form-group" style="display:flex;align-items:center;gap:10px;padding-top:4px">
      <input type="checkbox" id="autostart_caspar"
             style="width:18px;height:18px;flex-shrink:0;accent-color:var(--accent);cursor:pointer">
      <label for="autostart_caspar" style="margin:0;color:var(--text);cursor:pointer">
        Auto-start CasparCG when the app launches
      </label>
    </div>
    <div class="form-group" style="grid-column:1/-1">
      <label>Media Folder Path <span style="color:var(--muted);font-size:11px">(leave blank to use <code>media\</code> next to casparcg.exe)</span></label>
      <input type="text" id="media_path" placeholder="e.g. D:\\Media or leave blank for default">
    </div>
  </div>

  <h2 style="margin:20px 0 8px">Instances</h2>

  <!-- Column header row -->
  <div style="display:flex;gap:8px;padding:0 12px 6px;color:var(--muted);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.5px">
    <span style="width:48px;flex-shrink:0"></span>
    <span style="width:86px;flex-shrink:0">Type</span>
    <span style="flex:0 0 110px">Name</span>
    <span style="flex:0 0 160px">NDI Name</span>
    <span style="flex:1">URL / Startup Command</span>
    <span style="width:90px;flex-shrink:0">AMCP Port</span>
    <span style="width:36px;flex-shrink:0"></span>
  </div>

  <div id="instances-tbody"></div>

  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:20px">
    <button class="btn btn-primary" onclick="saveSettings()">Save & Regenerate Configs</button>
    <button class="btn btn-primary btn-sm" onclick="addInstance()">+ Add Instance</button>
  </div>
  <p style="color:var(--muted);font-size:12px;margin-top:10px">
    Each instance is a separate CasparCG process with its own AMCP port. Restart CasparCG after saving to apply changes.
  </p>
</div>

<!-- Remote Controllers -->
<div class="card" style="margin-top:16px">
  <h2 style="margin-bottom:8px">Remote Controllers</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:16px">
    Add other Elliott's Caspar Controller instances to monitor and control from the dashboard.
    Use the full URL including port, e.g. <code>http://192.168.1.101:5280</code>.
    The server name is pulled automatically from each remote.
  </p>
  <div id="remotes-list"></div>
  <div style="display:flex;gap:10px;margin-top:12px">
    <button class="btn btn-primary btn-sm" onclick="addRemote()">+ Add Remote</button>
    <button class="btn btn-primary" onclick="saveRemotes()">Save Remote Controllers</button>
  </div>
</div>

<!-- Config Import / Export -->
<div class="card" style="margin-top:16px">
  <h2 style="margin-bottom:8px">Config Backup</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:16px">
    Export your full configuration as a JSON file, or import a previously saved config (this will overwrite all current settings).
  </p>
  <div style="display:flex;gap:10px">
    <button class="btn btn-secondary" onclick="exportConfig()">Export Config</button>
    <button class="btn btn-secondary" onclick="importConfig()">Import Config</button>
  </div>
</div>
"""
    js = """
let currentInstances = [];

let _remotes = [];

function renderRemoteList() {
  const el = document.getElementById('remotes-list');
  if (!_remotes.length) {
    el.innerHTML = '<p style="color:var(--muted);font-size:13px;margin-bottom:8px">No remote controllers added yet.</p>';
    return;
  }
  el.innerHTML = _remotes.map((r, i) => `
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
      <input type="text" id="remote_url_${i}" value="${(r.url||'').replace(/"/g,'&quot;')}"
             placeholder="http://192.168.1.101:5280"
             style="flex:1;min-width:0">
      <button class="btn btn-secondary btn-sm" onclick="testRemote(${i})" title="Test connection">Test</button>
      <button class="btn btn-danger btn-sm" style="flex-shrink:0"
              onclick="removeRemote(${i})">×</button>
    </div>`).join('');
}

function addRemote() {
  _remotes = getFormRemotes();
  _remotes.push({ url: '', label: '' });
  renderRemoteList();
}

function removeRemote(i) {
  _remotes = getFormRemotes();
  _remotes.splice(i, 1);
  renderRemoteList();
}

function getFormRemotes() {
  return _remotes.map((_, i) => ({
    url: (document.getElementById('remote_url_' + i)?.value || '').trim(),
  })).filter(r => r.url);
}

function testRemote(i) {
  const url = (document.getElementById('remote_url_' + i)?.value || '').trim();
  if (!url) { toast('Enter a URL first', 'warning'); return; }
  toast('Testing connection...', 'info');
  api('/api/remote/test', 'POST', { url }).then(d => {
    if (d.online) {
      const name = d.server_name || url;
      toast('Connected! ' + name + ' (v' + (d.version || '?') + ')', 'success');
    } else {
      toast('Could not reach ' + url, 'error');
    }
  }).catch(() => toast('Test failed', 'error'));
}

function saveRemotes() {
  const remotes = getFormRemotes();
  api('/api/config', 'POST', { remote_controllers: remotes })
    .then(() => { _remotes = remotes; renderRemoteList(); toast('Remote controllers saved', 'success'); })
    .catch(() => toast('Failed to save', 'error'));
}

function loadSettings() {
  api('/api/config').then(cfg => {
    const exePath = cfg.caspar_exe_path || '';
    document.getElementById('caspar_exe_path').value = exePath;
    document.getElementById('exe-warning').style.display = exePath ? 'none' : 'block';
    document.getElementById('video_mode').value = cfg.video_mode || '1080p2500';
    document.getElementById('amcp_base_port').value = cfg.amcp_base_port || 5250;
    document.getElementById('web_port').value = cfg.web_port || 5280;
    document.getElementById('autostart_caspar').checked = !!cfg.autostart_caspar;
    document.getElementById('media_path').value = cfg.media_path || '';
    document.getElementById('server_name').value = cfg.server_name || '';
    document.getElementById('web_password').value = cfg.web_password || '';
    _remotes = (cfg.remote_controllers || []);
    renderRemoteList();
    currentInstances = (cfg.instances || []).map(inst => ({
      ...inst,
      type: inst.type || 'html',
      startup_command: inst.startup_command || '',
      url: inst.url || '',
      amcp_port: inst.amcp_port || 0,
    }));
    renderInstanceTable(currentInstances);
  
  });
}

function computedPort(i) {
  return (parseInt(document.getElementById('amcp_base_port').value) || 5250) + i;
}

function onBasePortChange() {
  currentInstances = getFormInstances();
  renderInstanceTable(currentInstances);

}

function renderInstanceTable(insts) {
  const last = insts.length - 1;
  document.getElementById('instances-tbody').innerHTML = insts.map((inst, i) => {
    const isHtml = (inst.type || 'html') === 'html';
    const urlVal = (inst.url || '').replace(/"/g, '&quot;');
    const cmdVal = (inst.startup_command || '').replace(/"/g, '&quot;');
    const nameVal = (inst.name || '').replace(/"/g, '&quot;');
    const ndiVal  = (inst.ndi_name || '').replace(/"/g, '&quot;');
    const port = computedPort(i);
    return `
    <div class="ch-edit-card">
      <div class="ch-edit-top">
        <div style="flex-shrink:0;width:48px;display:flex;flex-direction:column;gap:3px">
          <button class="btn btn-secondary btn-sm" style="height:22px;padding:0 8px;font-size:11px"
                  ${i===0?'disabled':''} onclick="moveUp(${i})">▲</button>
          <button class="btn btn-secondary btn-sm" style="height:22px;padding:0 8px;font-size:11px"
                  ${i===last?'disabled':''} onclick="moveDown(${i})">▼</button>
        </div>
        <select id="inst_type_${i}" onchange="toggleType(${i})" style="flex-shrink:0;width:86px">
          <option value="html" ${isHtml?'selected':''}>HTML5</option>
          <option value="media" ${!isHtml?'selected':''}>Media</option>
        </select>
        <input type="text" id="inst_name_${i}" value="${nameVal}" placeholder="Name"
               style="flex:0 0 110px;min-width:0">
        <input type="text" id="inst_ndi_${i}" value="${ndiVal}" placeholder="NDI Name"
               style="flex:0 0 160px;min-width:0">
        <input type="number" id="inst_port_${i}" value="${inst.amcp_port || port}"
               placeholder="${port}"
               style="flex-shrink:0;width:90px;font-size:11px;padding:5px 8px;text-align:right;margin-left:auto"
               title="Leave blank or set to 0 to auto-assign (base + position)">
        <button class="btn btn-danger btn-sm" style="flex-shrink:0;padding:0 10px"
                onclick="deleteInstance(${i})" title="Remove this instance">×</button>
      </div>
      <div class="ch-edit-source">
        <input type="text" id="inst_url_${i}" value="${urlVal}" placeholder="https://..."
               style="width:100%;${isHtml?'':'display:none'}">
        <input type="text" id="inst_cmd_${i}" value="${cmdVal}"
               placeholder='PLAY 1-1 "CLIP" LOOP — leave blank to just CLEAR'
               style="width:100%;${!isHtml?'':'display:none'}">
      </div>
    </div>`;
  }).join('');
}

function toggleType(i) {
  const isHtml = document.getElementById('inst_type_' + i).value === 'html';
  document.getElementById('inst_url_' + i).style.display = isHtml ? '' : 'none';
  document.getElementById('inst_cmd_' + i).style.display = isHtml ? 'none' : '';
}

function getFormInstances() {
  const base = parseInt(document.getElementById('amcp_base_port').value) || 5250;
  return currentInstances.map((inst, i) => {
    const portVal = parseInt(document.getElementById('inst_port_' + i)?.value) || 0;
    const autoPort = base + i;
    return {
      ...inst,
      name:            document.getElementById('inst_name_' + i)?.value ?? inst.name,
      ndi_name:        document.getElementById('inst_ndi_' + i)?.value ?? inst.ndi_name,
      type:            document.getElementById('inst_type_' + i)?.value ?? inst.type,
      url:             document.getElementById('inst_url_' + i)?.value ?? inst.url,
      startup_command: document.getElementById('inst_cmd_' + i)?.value ?? inst.startup_command,
      // Only save explicit port if it differs from auto-computed; 0 means "auto"
      amcp_port:       (portVal && portVal !== autoPort) ? portVal : 0,
    };
  });
}


function moveUp(i) {
  if (i === 0) return;
  currentInstances = getFormInstances();
  [currentInstances[i-1], currentInstances[i]] = [currentInstances[i], currentInstances[i-1]];
  renderInstanceTable(currentInstances);
}

function moveDown(i) {
  if (i >= currentInstances.length - 1) return;
  currentInstances = getFormInstances();
  [currentInstances[i], currentInstances[i+1]] = [currentInstances[i+1], currentInstances[i]];
  renderInstanceTable(currentInstances);
}

function addInstance() {
  currentInstances = getFormInstances();
  const n = currentInstances.length + 1;
  currentInstances.push({ id: n, name: 'INST' + n, ndi_name: 'PCR3 INST' + n,
                           type: 'html', url: '', startup_command: '', amcp_port: 0 });
  renderInstanceTable(currentInstances);

  toast('Instance added', 'success');
}

function deleteInstance(i) {
  const name = currentInstances[i]?.name || ('Inst ' + (i+1));
  if (!confirm('Delete instance "' + name + '"?')) return;
  currentInstances = getFormInstances();
  currentInstances.splice(i, 1);
  renderInstanceTable(currentInstances);

  toast(name + ' deleted', 'warning');
}

function saveExePath() {
  const path = document.getElementById('caspar_exe_path').value.trim();
  api('/api/config', 'POST', { caspar_exe_path: path })
    .then(() => {
      toast('CasparCG path saved', 'success');
      document.getElementById('exe-warning').style.display = path ? 'none' : 'block';
    })
    .catch(() => toast('Failed to save path', 'error'));
}

function saveSettings() {
  const instances = getFormInstances();
  const payload = {
    video_mode:       document.getElementById('video_mode').value,
    amcp_base_port:   parseInt(document.getElementById('amcp_base_port').value),
    web_port:         parseInt(document.getElementById('web_port').value),
    autostart_caspar: document.getElementById('autostart_caspar').checked,
    media_path:       document.getElementById('media_path').value.trim(),
    instances,
  };
  api('/api/config', 'POST', payload).then(() => {
    currentInstances = instances;
    toast('Settings saved — restart CasparCG to apply', 'success');
  }).catch(() => toast('Failed to save settings', 'error'));
}

function saveServerName() {
  const name = document.getElementById('server_name').value.trim();
  api('/api/config', 'POST', { server_name: name })
    .then(() => { toast('Server name saved', 'success'); location.reload(); })
    .catch(() => toast('Failed to save', 'error'));
}

function savePassword() {
  const pw = document.getElementById('web_password').value;
  api('/api/config', 'POST', { web_password: pw, web_password_enabled: pw.length > 0 })
    .then(() => toast(pw ? 'Password set' : 'Password disabled', 'success'))
    .catch(() => toast('Failed to save', 'error'));
}

function exportConfig() {
  fetch('/api/config/export')
    .then(r => r.blob())
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'elliotts_caspar_config.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast('Config exported', 'success');
    })
    .catch(() => toast('Export failed', 'error'));
}

function importConfig() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json,application/json';
  input.onchange = e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
      let cfg;
      try { cfg = JSON.parse(ev.target.result); }
      catch { toast('Invalid JSON file', 'error'); return; }
      if (!confirm('This will replace all current settings. Continue?')) return;
      api('/api/config/import', 'POST', cfg)
        .then(() => { toast('Config imported', 'success'); loadSettings(); })
        .catch(() => toast('Import failed', 'error'));
    };
    reader.readAsText(file);
  };
  input.click();
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
    cfg_obj = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
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
