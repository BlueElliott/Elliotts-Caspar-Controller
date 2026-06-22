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

import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from typing import Dict

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

_tally: Dict[str, dict] = {}   # ndi_name -> {"program": bool, "preview": bool}
_lock = threading.Lock()
_monitors: dict = {}           # ndi_name -> {"thread": Thread, "stop": Event}


def is_available() -> bool:
    return _AVAILABLE


def get_tally() -> dict:
    """Return a copy of the current tally state keyed by NDI source name."""
    with _lock:
        return dict(_tally)


# ---------------------------------------------------------------------------
# Per-source monitor thread
# ---------------------------------------------------------------------------

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
                if ndi_name.lower() in src_name.lower():
                    source = s
                    break
        if source:
            break
    ndi.find_destroy(finder)
    return source


def _run_session(ndi_name: str, stop: threading.Event):
    """One connection attempt: find source, connect, read metadata until stop."""
    source = _find_source(ndi_name, stop)
    if not source or stop.is_set():
        return

    recv_create = ndi.RecvCreateV3()
    try:
        # Metadata-only mode — zero video/audio bandwidth
        recv_create.bandwidth = ndi.RecvBandwidth.METADATA_ONLY
    except AttributeError:
        try:
            recv_create.bandwidth = -10  # METADATA_ONLY constant value in some builds
        except Exception:
            pass
    recv_create.allow_video_fields = False
    recv_create.ndi_recv_name = "Elliott's Caspar Controller Tally"

    recv = ndi.recv_create_v3(recv_create)
    if not recv:
        return
    ndi.recv_connect(recv, source)

    while not stop.is_set():
        try:
            result = ndi.recv_capture_v3(recv, 500)
            # recv_capture_v3 returns (frame_type, video, audio, metadata)
            frame_type = result[0]
            metadata_frame = result[3] if len(result) > 3 else None

            if metadata_frame is not None:
                try:
                    xml_str = getattr(metadata_frame, "data", None) or ""
                    if xml_str and "tally" in xml_str.lower():
                        root = ET.fromstring(xml_str)
                        if "tally" in root.tag.lower():
                            prog = root.get("on_program", "false").lower() == "true"
                            prev = root.get("on_preview", "false").lower() == "true"
                            with _lock:
                                _tally[ndi_name] = {"program": prog, "preview": prev}
                except Exception:
                    pass
        except Exception:
            break

    try:
        ndi.recv_destroy(recv)
    except Exception:
        pass


def _monitor_loop(ndi_name: str, stop: threading.Event):
    """Outer loop: retries the session every 10s if CasparCG isn't running yet."""
    while not stop.is_set():
        try:
            _run_session(ndi_name, stop)
        except Exception:
            pass
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
