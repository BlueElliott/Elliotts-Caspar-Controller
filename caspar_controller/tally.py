"""
NDI tally monitor — connects to each CasparCG NDI source in metadata-only
mode and tracks on-air / on-preview state via tally echo XML messages.

How it works:
  1. When a downstream device (e.g. Tricaster) takes a source on-air it calls
     NDIlib_recv_set_tally(program=True) on its receiver connection.
  2. The NDI sender (CasparCG) echoes that tally state back to EVERY connected
     receiver as XML metadata: <ndi_tally_echo on_program="true" .../>
  3. Our metadata-only receiver picks up that echo and updates _tally.

Dependencies:
  pip install ndi-python
  NDI Runtime must be installed (already present on any machine running CasparCG).

Silently no-ops if ndi-python is not installed or the NDI Runtime is missing.
"""

import logging
import os
import socket
import threading
import time
import xml.etree.ElementTree as ET
from typing import Dict

from caspar_controller.log import log_event
from caspar_controller.settings import load as load_config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NDI Runtime path hint — the runtime DLL ships with CasparCG / NDI Tools.
# Add the most common install locations to PATH before importing so the
# Python wrapper can find Processing.NDI.Lib.x64.dll in a frozen build.
# ---------------------------------------------------------------------------
for _ndi_path in (
    r"C:\Program Files\NDI\NDI 6 Runtime\v6",
    r"C:\Program Files\NDI\NDI 5 Runtime\v5",
    r"C:\Program Files\NewTek\NDI 6 Runtime\v6",
    r"C:\Program Files\NewTek\NDI 5 Runtime\v5",
    r"C:\Program Files\NewTek\NDI 4 Runtime",
):
    if os.path.isdir(_ndi_path) and _ndi_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ndi_path + os.pathsep + os.environ.get("PATH", "")

try:
    import NDIlib as ndi

    _AVAILABLE: bool = ndi.initialize()
except Exception:
    _AVAILABLE = False
    ndi = None  # type: ignore

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_tally: Dict[str, dict] = {}  # ndi_name -> {"program": bool, "preview": bool}
_lock = threading.Lock()
_monitors: dict = {}  # ndi_name -> {"thread": Thread, "stop": Event}


def is_available() -> bool:
    return _AVAILABLE


def get_tally() -> dict:
    """Return a copy of the current tally state keyed by NDI source name."""
    with _lock:
        return dict(_tally)


# ---------------------------------------------------------------------------
# Per-source monitor thread
# ---------------------------------------------------------------------------


def _this_pc() -> set:
    # NDI may use the DNS host name or the 15-character NetBIOS name.
    return {n.lower() for n in (socket.gethostname(), os.environ.get("COMPUTERNAME", "")) if n}


def is_our_source(source_name: str, ndi_name: str) -> bool:
    """NDI names sources "HOST (name)": match this PC's exact name, so GFX1 isn't GFX10."""
    host, sep, rest = source_name.partition(" (")
    return bool(sep) and rest.lower() == f"{ndi_name.lower()})" and host.lower() in _this_pc()


_not_found: set = set()  # NDI names already reported missing, so the retry loop doesn't spam
_failing: set = set()  # NDI names whose session error is already logged, likewise


def _find_source(ndi_name: str, stop: threading.Event):
    """Search for an NDI source matching ndi_name. Returns source or None."""
    find_create = ndi.FindCreate()
    find_create.show_local_sources = True
    finder = ndi.find_create_v2(find_create)
    source = None
    deadline = time.time() + 15
    while time.time() < deadline and not stop.is_set():
        ndi.find_wait_for_sources(finder, 500)
        sources = ndi.find_get_current_sources(finder)
        if sources:
            for s in sources:
                src_name = getattr(s, "ndi_name", "") or ""
                if is_our_source(src_name, ndi_name):
                    source = s
                    break
        if source:
            break
    ndi.find_destroy(finder)
    if not source and not stop.is_set() and ndi_name not in _not_found:
        _not_found.add(ndi_name)
        log_event(f"Tally: no NDI source '{ndi_name}' from this PC yet (still looking).")
    if source:
        _not_found.discard(ndi_name)
    return source


def _read_tally(ndi_name: str, xml: str) -> None:
    """Record the program/preview state from an <ndi_tally_echo> metadata message."""
    if "tally" not in xml.lower():
        return
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        log.warning("Tally: unreadable metadata from %s: %.200s", ndi_name, xml)
        return
    if "tally" in root.tag.lower():
        prog = root.get("on_program", "false").lower() == "true"
        prev = root.get("on_preview", "false").lower() == "true"
        with _lock:
            _tally[ndi_name] = {"program": prog, "preview": prev}


def _run_session(ndi_name: str, stop: threading.Event) -> None:
    """One connection attempt: find source, connect, read metadata until stop."""
    source = _find_source(ndi_name, stop)
    if not source or stop.is_set():
        return

    recv_create = ndi.RecvCreateV3()
    recv_create.bandwidth = ndi.RECV_BANDWIDTH_METADATA_ONLY  # the default pulls full video
    recv_create.allow_video_fields = False
    recv_create.ndi_recv_name = "Caspar Controller Tally"

    recv = ndi.recv_create_v3(recv_create)
    if not recv:
        return
    try:
        ndi.recv_connect(recv, source)
        while not stop.is_set():
            # Metadata only here too, so no video or audio frame can pile up unfreed.
            frame_type, _, _, metadata = ndi.recv_capture_v3(
                recv, 500, want_video=False, want_audio=False
            )
            if frame_type == ndi.FRAME_TYPE_METADATA:
                xml = metadata.data
                ndi.recv_free_metadata(recv, metadata)
                _read_tally(ndi_name, xml)
    finally:
        ndi.recv_destroy(recv)


def _monitor_loop(ndi_name: str, stop: threading.Event):
    """Outer loop: retries the session every 10s if CasparCG isn't running yet."""
    while not stop.is_set():
        try:
            _run_session(ndi_name, stop)
            _failing.discard(ndi_name)
        except Exception:
            if ndi_name not in _failing:
                _failing.add(ndi_name)
                log.exception("Tally for %s failed; retrying every 10 s", ndi_name)
        if not stop.is_set():
            # Source not found or connection dropped — wait then retry
            stop.wait(10)


# ---------------------------------------------------------------------------
# Public control API
# ---------------------------------------------------------------------------


def start_monitoring(ndi_names: list):
    """
    Start background tally monitors for the given NDI source names.
    Stops any monitors for names no longer in the list.
    Safe to call multiple times — only starts monitors that aren't running.
    """
    if not _AVAILABLE:
        return

    wanted = set(ndi_names)
    current = set(_monitors.keys())

    # Stop monitors for removed instances
    for name in current - wanted:
        _monitors[name]["stop"].set()
        _monitors.pop(name, None)

    # Start new monitors
    for name in wanted - current:
        stop_evt = threading.Event()
        t = threading.Thread(
            target=_monitor_loop, args=(name, stop_evt), daemon=True, name=f"tally:{name}"
        )
        t.start()
        _monitors[name] = {"thread": t, "stop": stop_evt}


def stop_all():
    """Stop all tally monitors (called on app shutdown)."""
    for m in _monitors.values():
        m["stop"].set()
    _monitors.clear()
    with _lock:
        _tally.clear()


def refresh_monitors() -> None:
    """Start/stop tally monitors to match current instance config."""
    cfg = load_config()
    ndi_names = [i["ndi_name"] for i in cfg.get("instances", []) if i.get("ndi_name")]
    start_monitoring(ndi_names)
