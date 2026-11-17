"""Shared fixtures for the characterisation suite.

Every test runs against an isolated config directory, and may only kill
processes it launched itself, so the suite can never take down a real CasparCG
running on a developer or gallery machine.
"""

import json
import os
import socket
import sys
from pathlib import Path

import psutil
import pytest
from fake_ndi import FakeNDI
from fastapi.testclient import TestClient

from caspar_controller import instances, log, remotes, settings, tally
from caspar_controller.api import auth as api_auth, events
from caspar_controller.api.app import app
from caspar_controller.caspar.process import CasparProcessManager
from caspar_controller.throttle import Throttle

TESTS_DIR = Path(__file__).parent
FAKE_CASPAR = TESTS_DIR / "fake_caspar.py"
FIXTURES = TESTS_DIR / "fixtures"
API_KEY = "test-api-key"
LOCAL = ("127.0.0.1", 50000)
LOCAL_URL = "http://127.0.0.1:5280"  # Host header a local browser sends

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="launches Windows processes")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def refused_kills(monkeypatch):
    """Only kill processes this test run launched; record any other PID instead."""
    refused = []
    real_kill = CasparProcessManager._kill_tree

    def guarded(pid: int) -> None:
        if pid in {p.pid for p in psutil.Process().children(recursive=True)}:
            real_kill(pid)
        else:
            refused.append(pid)

    monkeypatch.setattr(CasparProcessManager, "_kill_tree", staticmethod(guarded))
    return refused


@pytest.fixture(autouse=True)
def short_event_stream(monkeypatch):
    """/api/events ends after half a second, so a test reading it gets the whole body."""
    monkeypatch.setattr(events, "LIFETIME", 0.5)


@pytest.fixture(autouse=True)
def no_ndi(monkeypatch):
    """Behave as if ndi-python isn't installed, whatever the environment."""
    monkeypatch.setattr(tally, "is_available", lambda: False)
    monkeypatch.setattr(tally, "refresh_monitors", lambda: None)


@pytest.fixture
def fake_ndi(monkeypatch):
    """Tally talks to a FakeNDI that has found its source; queue frames, then run a session."""
    fake = FakeNDI()
    monkeypatch.setattr(tally, "ndi", fake)
    monkeypatch.setattr(tally, "_find_source", lambda name, stop: "source")
    monkeypatch.setattr(tally, "_tally", {})
    monkeypatch.setattr(tally, "_failing", set())
    return fake


@pytest.fixture(autouse=True)
def fresh_core_state(monkeypatch):
    """Reset module-level state between tests; finish any instance jobs before the next."""
    manager = instances.InstanceManager()
    monkeypatch.setattr(instances, "manager", manager)
    monkeypatch.setattr(log, "_log", [])
    monkeypatch.setattr(api_auth, "_sessions", {})
    monkeypatch.setattr(api_auth, "_sign_in_failures", Throttle())
    monkeypatch.setattr(api_auth, "_wrong_key_log", Throttle())
    monkeypatch.setattr(remotes, "_remote_name_cache", {})
    yield
    manager.wait()


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    """Point the app's config file at a temp directory.

    Also run from tmp_path: with no absolute exe path set, the app writes
    casparcg_inst_N.config files into the current directory.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(settings.INITIAL_PASSWORD_ENV, raising=False)
    d = tmp_path / "app"
    d.mkdir()
    monkeypatch.setenv(settings.HOME_ENV, str(d))
    # Never pick up the real v1.x config beside the repo (it holds a real API key).
    monkeypatch.setattr(settings, "LEGACY_DIR", str(tmp_path / "legacy"))
    monkeypatch.setattr(settings, "USERS_DIR", str(tmp_path / "Users"))
    monkeypatch.setattr(settings, "V1_CASPAR_DIR", str(tmp_path / "CasparCG"))
    monkeypatch.setattr(settings, "_cache", None)
    return d


@pytest.fixture
def write_config(config_dir):
    """Write a config file, with the test API key unless the test sets its own."""

    def _write(cfg: dict) -> dict:
        cfg = {"api_key": API_KEY, **cfg}
        (config_dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        settings._cache = None  # load() reads the file again
        return cfg

    return _write


# No context manager on these clients: the lifespan (status thread, NDI tally) isn't started.


@pytest.fixture
def client():
    """A trusted operator: on this PC and sending the API key."""
    return TestClient(app, base_url=LOCAL_URL, client=LOCAL, headers={"X-API-Key": API_KEY})


@pytest.fixture
def anon():
    """Another device on the network with no credentials."""
    return TestClient(app)


@pytest.fixture
def local_anon():
    """A browser on this PC with no credentials."""
    return TestClient(app, base_url=LOCAL_URL, client=LOCAL)


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """Record the 5 s gaps between instance starts instead of waiting them out."""
    sleeps = []
    monkeypatch.setattr(instances.InstanceManager, "_gap", lambda self: sleeps.append(5))
    return sleeps


@pytest.fixture
def caspar_dir(tmp_path):
    """A folder holding a casparcg.cmd shim that runs tests/fake_caspar.py.

    Any process left running in this folder is killed afterwards.
    """
    d = tmp_path / "caspar"
    d.mkdir()
    (d / "casparcg.cmd").write_text(f'@"{sys.executable}" "{FAKE_CASPAR}" %*\r\n', encoding="utf-8")
    yield d
    instances.manager.wait()  # a job still starting would launch more after the sweep
    target = os.path.normcase(str(d))
    for proc in psutil.process_iter(["pid"]):
        try:
            if os.path.normcase(proc.cwd()) == target:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass


def amcp_log(caspar_dir: Path, port: int) -> list:
    """Commands received by the fake CasparCG listening on ``port``."""
    path = caspar_dir / f"amcp_{port}.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def instance(
    id_: int,
    name: str,
    type_: str = "html",
    url: str = "",
    startup_command: str = "",
    amcp_port: int = 0,
    ndi_name: str | None = None,
) -> dict:
    return {
        "id": id_,
        "name": name,
        "ndi_name": ndi_name or f"PCR3 {name}",
        "type": type_,
        "url": url,
        "startup_command": startup_command,
        "amcp_port": amcp_port,
    }
