"""/api/status, the background status worker and INFO parsing.

The INFO XML below is written in the shape today's parser expects. It has not
been captured from a real CasparCG yet: replace it with captures from the
galleries' build when they are available (see #7).
"""

import json
import threading
import time
import types

import pytest
from conftest import free_port, instance
from fake_amcp import EMPTY_LAYER_XML, FakeAMCPServer

from caspar_controller import instances, log, tally
from caspar_controller.caspar.info import parse_layer_info

PLAYING_XML = (
    '<layer><foreground><producer type="ffmpeg-producer">'
    "<filename>D:\\media\\AMB.mp4</filename><time>12.5</time><duration>60</duration>"
    "<loop>1</loop></producer></foreground></layer>"
)
EMPTY = {"clip": None, "time": 0.0, "duration": 0.0, "loop": False, "producer": "empty"}


# ---------------------------------------------------------------- INFO parsing


def test_parse_playing_clip():
    assert parse_layer_info("201 INFO OK\r\n" + PLAYING_XML) == {
        "clip": "AMB.mp4",
        "time": 12.5,
        "duration": 60.0,
        "loop": True,
        "producer": "ffmpeg-producer",
    }


def test_parse_strips_numeric_suffix():
    xml = PLAYING_XML.replace("AMB.mp4", "AMB.mp4_0")
    assert parse_layer_info("201 INFO OK\n" + xml)["clip"] == "AMB.mp4"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ERROR: refused",
        "404 INFO FAILED\r\n",
        "201 INFO OK",
        "201 INFO OK\r\n",
        "201 INFO OK\r\n<not xml",
        "201 INFO OK\r\n<layer/>",
        "201 INFO OK\r\n" + EMPTY_LAYER_XML,
    ],
)
def test_parse_non_playing_replies_are_empty(raw):
    assert parse_layer_info(raw) == EMPTY


def test_parse_loop_false_values():
    for value in ("0", "false", "False"):
        xml = PLAYING_XML.replace("<loop>1</loop>", f"<loop>{value}</loop>")
        assert parse_layer_info("201 INFO OK\n" + xml)["loop"] is False


# ---------------------------------------------------------------- status


STATUS_KEYS = {"running", "version", "instances", "needs_setup", "server_name", "tally_available"}


def test_status_shape_before_first_poll(client, write_config):
    write_config(
        {
            "caspar_exe_path": "C:\\CasparCG\\casparcg.exe",
            "server_name": "Studio A",
            "instances": [instance(1, "GFX1", url="https://x", amcp_port=6100)],
        }
    )
    data = client.get("/api/status").json()

    assert set(data) == STATUS_KEYS
    assert data["running"] is False
    assert data["needs_setup"] is False
    assert data["server_name"] == "Studio A"
    assert data["tally_available"] is False  # NDI is stubbed out in conftest
    assert data["instances"][0] == {
        "id": 1,
        "name": "GFX1",
        "ndi_name": "PCR3 GFX1",
        "type": "html",
        "url": "https://x",
        "startup_command": "",
        "amcp_port": 6100,
        "status": "stopped",
        "layer": {},
        "caspar_version": "",
        "auto_restart": True,
        "console_lines": 0,
        "on_program": False,
        "on_preview": False,
    }


@pytest.mark.parametrize(
    ("cfg", "expected"),
    [
        ({"caspar_exe_path": "", "instances": [instance(1, "A")]}, True),
        ({"caspar_exe_path": "casparcg.exe", "instances": []}, True),
        ({"caspar_exe_path": "casparcg.exe", "instances": [instance(1, "A")]}, False),
    ],
)
def test_needs_setup(client, write_config, cfg, expected):
    write_config(cfg)
    assert client.get("/api/status").json()["needs_setup"] is expected


def test_worker_marks_live_instances_and_clip_info(client, write_config):
    with FakeAMCPServer(info_xml=PLAYING_XML) as live:
        write_config(
            {
                "caspar_exe_path": "casparcg.exe",
                "instances": [
                    instance(1, "MEDIA1", "media", amcp_port=live.port),
                    instance(2, "GFX2", amcp_port=free_port()),
                ],
            }
        )
        instances.manager.poll_status()

        assert live.commands == ["VERSION", "INFO 1-1"]  # VERSION for liveness, INFO for the clip
        data = client.get("/api/status").json()

    assert data["running"] is True
    one, two = data["instances"]
    assert one["status"] == "live"
    assert one["layer"]["clip"] == "AMB.mp4"
    assert two["status"] == "stopped"
    assert two["layer"] == EMPTY


def test_liveness_uses_version(client, write_config):
    # A live server that rejects INFO (e.g. channel not ready) used to show as stopped.
    with FakeAMCPServer(replies={"INFO": "404 INFO FAILED"}) as s:
        write_config({"instances": [instance(1, "GFX1", amcp_port=s.port)]})
        instances.manager.poll_status()
        assert client.get("/api/status").json()["instances"][0]["status"] == "live"


def test_tally_is_merged_by_ndi_name(client, write_config, monkeypatch):
    write_config({"instances": [instance(1, "GFX1"), instance(2, "GFX2")]})
    monkeypatch.setattr(
        tally, "get_tally", lambda: {"PCR3 GFX2": {"program": True, "preview": False}}
    )
    a, b = client.get("/api/status").json()["instances"]
    assert (a["on_program"], b["on_program"], b["on_preview"]) == (False, True, False)


def test_log_endpoint_returns_event_log(client):
    log.log_event("hello")
    lines = client.get("/api/log").json()["log"]
    assert len(lines) == 1 and lines[0].endswith("] hello")


def test_log_keeps_last_200():
    for i in range(205):
        log.log_event(f"e{i}")
    assert len(log._log) == 200
    assert log._log[0].endswith("e5")


# ---------------------------------------------------------------- INFO layouts (#7)
# Synthetic until captures from the galleries' CasparCG arrive; both known layouts are covered.

CASPAR_23_XML = (
    "<layer><background><producer>empty</producer></background><foreground>"
    "<file><clip>0 60</clip><name>AMB</name><path>media/AMB.mp4</path><time>12.5 60</time></file>"
    "<loop>false</loop><paused>false</paused><producer>ffmpeg</producer></foreground></layer>"
)


def test_parse_caspar_23_layout():
    assert parse_layer_info("201 INFO OK\r\n" + CASPAR_23_XML) == {
        "clip": "AMB.mp4",  # the path's name with extension, as 2.0 shows it
        "time": 12.5,
        "duration": 60.0,
        "loop": False,
        "producer": "ffmpeg",
    }


def test_parse_caspar_23_repeated_time_elements():
    xml = CASPAR_23_XML.replace("<time>12.5 60</time>", "<time>12.5</time><time>60</time>")
    info = parse_layer_info("201 INFO OK\r\n" + xml)
    assert (info["time"], info["duration"]) == (12.5, 60.0)


def test_parse_caspar_23_empty_layer():
    xml = "<layer><foreground><producer>empty</producer></foreground></layer>"
    assert parse_layer_info("201 INFO OK\r\n" + xml) == EMPTY


def test_parse_caspar_21_frames():
    xml = (
        "<layer><foreground><producer><type>ffmpeg-producer</type>"
        "<filename>media/PROMO.mov</filename><fps>25</fps><file-frame-number>250</file-frame-number>"
        "<file-nb-frames>1500</file-nb-frames><loop>true</loop></producer></foreground></layer>"
    )
    info = parse_layer_info("201 INFO OK\r\n" + xml)
    assert (info["clip"], info["time"], info["duration"], info["loop"]) == (
        "PROMO.mov",
        10.0,
        60.0,
        True,
    )


def test_clip_names_with_numeric_suffix_kept():
    xml = (
        '<layer><foreground><producer type="ffmpeg-producer">'
        "<filename>PROMO_2024</filename></producer></foreground></layer>"
    )
    assert parse_layer_info("201 INFO OK\n" + xml)["clip"] == "PROMO_2024"


# ---------------------------------------------------------------- tally (#7)


@pytest.mark.parametrize(
    ("source", "matches"),
    [
        ("PLAYOUT-PC (PCR3 GFX1)", True),
        ("playout-pc (pcr3 gfx1)", True),
        ("PLAYOUT-PC (PCR3 GFX10)", False),  # used to match by substring
        ("OTHER-PC (PCR3 GFX1)", False),  # same name on another machine
    ],
)
def test_tally_matches_exact_local_source(monkeypatch, source, matches):
    monkeypatch.setattr(tally.socket, "gethostname", lambda: "PLAYOUT-PC")
    monkeypatch.delenv("COMPUTERNAME", raising=False)
    assert tally.is_our_source(source, "PCR3 GFX1") is matches


def test_tally_accepts_the_netbios_name(monkeypatch):
    # Host names over 15 characters: NDI may use the shortened NetBIOS name.
    monkeypatch.setattr(tally.socket, "gethostname", lambda: "gallery-playout-pc-01")
    monkeypatch.setenv("COMPUTERNAME", "GALLERY-PLAYOUT")
    assert tally.is_our_source("GALLERY-PLAYOUT (PCR3 GFX1)", "PCR3 GFX1")


def test_tally_receiver_is_metadata_only(fake_ndi):
    # #49: a wrong enum name left it at full bandwidth, leaking every video frame.
    fake_ndi.frames = ['<ndi_tally_echo on_program="false" on_preview="false"/>']
    tally._run_session("PCR3 GFX1", fake_ndi.stop)
    assert [r.bandwidth for r in fake_ndi.receivers] == [fake_ndi.RECV_BANDWIDTH_METADATA_ONLY]
    assert set(fake_ndi.captures) == {(False, False)}


def test_tally_frees_every_frame_and_reads_the_echo(fake_ndi):
    echo = '<ndi_tally_echo on_program="true" on_preview="false"/>'
    fake_ndi.frames = ['<ndi_product long_name="CasparCG"/>', echo]
    tally._run_session("PCR3 GFX1", fake_ndi.stop)
    assert fake_ndi.freed == ['<ndi_product long_name="CasparCG"/>', echo]
    assert fake_ndi.destroyed == 1
    assert tally.get_tally() == {"PCR3 GFX1": {"program": True, "preview": False}}


def test_tally_session_errors_are_logged(fake_ndi, caplog):
    fake_ndi.connect_error = RuntimeError("NDI went away")
    fake_ndi.stop.wait = lambda timeout: fake_ndi.stop.set()  # no 10 s retry wait
    tally._monitor_loop("PCR3 GFX1", fake_ndi.stop)
    assert "Tally for PCR3 GFX1 failed" in caplog.text
    assert "NDI went away" in caplog.text
    assert fake_ndi.destroyed == 1


def test_html_outputs_are_not_asked_for_clip_info(write_config):
    with FakeAMCPServer() as s:
        write_config({"instances": [instance(1, "GFX1", amcp_port=s.port)]})
        instances.manager.poll_status()
        assert s.commands == ["VERSION"]


# ---------------------------------------------------------------- live events (#7)


def events_of(body: str) -> list:
    """(event name, data) for each server-sent event in a response body."""
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        if "event" in fields:  # skips the opening "retry:" line
            out.append((fields["event"], json.loads(fields["data"])))
    return out


def test_events_stream_asks_for_a_quick_reconnect(client, write_config):
    write_config({"instances": []})
    assert client.get("/api/events").text.startswith("retry: 500\n\n")


def test_events_stream_ends_when_the_session_does(write_config, monkeypatch):
    from caspar_controller.api import auth as api_auth

    write_config({"instances": []})
    signed_in = types.SimpleNamespace(cookies={"session": "tok"})
    api_auth._sessions["tok"] = time.time()
    assert api_auth.still_allowed(signed_in) is True
    api_auth._sessions.pop("tok")  # signed out after the stream opened
    assert api_auth.still_allowed(signed_in) is False


def test_events_stream_sends_status_and_log_once_each(client, write_config):
    write_config({"instances": [instance(1, "GFX1")]})
    log.log_event("hello")
    r = client.get("/api/events")
    assert r.headers["content-type"].startswith("text/event-stream")
    names = [name for name, _ in events_of(r.text)]
    assert names == ["status", "log"]  # nothing changed, so nothing sent again
    status, logged = (data for _, data in events_of(r.text))
    assert status == client.get("/api/status").json()
    assert logged["log"][-1].endswith("hello")


def test_events_stream_sends_changes_within_a_second(client, write_config):
    write_config({"instances": []})
    threading.Timer(0.2, log.log_event, args=("later",)).start()
    events = events_of(client.get("/api/events").text)
    assert [name for name, _ in events] == ["status", "log", "log"]
    assert events[-1][1]["log"][-1].endswith("later")


def test_worker_records_caspar_version(client, write_config):
    with FakeAMCPServer(version="2.3.3 Stable") as s:
        write_config({"instances": [instance(1, "GFX1", amcp_port=s.port)]})
        instances.manager.poll_status()
        assert client.get("/api/status").json()["instances"][0]["caspar_version"] == "2.3.3 Stable"
