"""Read/write app config and regenerate per-instance casparcg.config files."""
import json
import os
import sys


def _config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_SINGULAR_BASE = (
    "https://app.singular.live/output/66B4M4gG2cjcbEEP51ORwU/Output?aspect=16:9&g_custom1="
)

DEFAULT_CONFIG = {
    "caspar_exe_path": "casparcg.exe",
    "amcp_base_port": 5250,
    "web_port": 5280,
    "startup_delay": 8,
    "video_mode": "1080p2500",
    "autostart_caspar": False,
    "instances": [
        {"id": 1, "name": "GFX1",   "ndi_name": "PCR3 GFX1",   "type": "html", "url": _SINGULAR_BASE + "GFX1",   "startup_command": ""},
        {"id": 2, "name": "GFX2",   "ndi_name": "PCR3 GFX2",   "type": "html", "url": _SINGULAR_BASE + "GFX2",   "startup_command": ""},
        {"id": 3, "name": "GFX3",   "ndi_name": "PCR3 GFX3",   "type": "html", "url": _SINGULAR_BASE + "GFX3",   "startup_command": ""},
        {"id": 4, "name": "GFX4",   "ndi_name": "PCR3 GFX4",   "type": "html", "url": _SINGULAR_BASE + "GFX4",   "startup_command": ""},
        {"id": 5, "name": "GFXPVW", "ndi_name": "PCR3 GFXPVW", "type": "html", "url": _SINGULAR_BASE + "GFXPVW", "startup_command": ""},
    ],
}


def _config_file() -> str:
    return os.path.join(_config_dir(), "elliotts_casper_config.json")


def instance_amcp_port(cfg: dict, inst: dict) -> int:
    """Return the AMCP port for an instance.

    Uses inst['amcp_port'] if explicitly set (non-zero), otherwise falls back
    to base_port + position in the instances list.
    """
    override = inst.get("amcp_port")
    if override:
        return int(override)
    base = cfg.get("amcp_base_port", 5250)
    for i, x in enumerate(cfg.get("instances", [])):
        if x["id"] == inst["id"]:
            return base + i
    return base


def load() -> dict:
    cfg_file = _config_file()
    if os.path.exists(cfg_file):
        with open(cfg_file, "r") as f:
            stored = json.load(f)
        config = dict(DEFAULT_CONFIG)
        config.update(stored)
    else:
        config = dict(DEFAULT_CONFIG)

    # --- Migrate old single-server channel config to multi-instance ---
    if "channels" in config and "instances" not in config:
        config["instances"] = [
            {
                "id": ch.get("number", i + 1),
                "name": ch.get("name", f"CH{i + 1}"),
                "ndi_name": ch.get("ndi_name", f"PCR3 CH{i + 1}"),
                "type": ch.get("type", "html"),
                "url": ch.get("url", ""),
                "startup_command": ch.get("startup_command", ""),
            }
            for i, ch in enumerate(config["channels"])
        ]
        del config["channels"]

    # Migrate amcp_port → amcp_base_port
    if "amcp_port" in config and "amcp_base_port" not in config:
        config["amcp_base_port"] = config["amcp_port"]
    config.pop("amcp_port", None)

    # Backfill top-level defaults
    config.setdefault("amcp_base_port", 5250)
    config.setdefault("autostart_caspar", False)
    config.setdefault("instances", list(DEFAULT_CONFIG["instances"]))

    # Backfill per-instance fields
    for inst in config.get("instances", []):
        inst.setdefault("type", "html")
        inst.setdefault("startup_command", "")
        inst.setdefault("url", "")

    return config


def save(config: dict) -> None:
    with open(_config_file(), "w") as f:
        json.dump(config, f, indent=2)


def caspar_instance_config_path(config: dict, inst: dict) -> str:
    """Return the full path for a per-instance casparcg config file."""
    filename = f"casparcg_inst_{inst['id']}.config"
    exe = config.get("caspar_exe_path", "")
    if exe and os.path.isabs(exe):
        return os.path.join(os.path.dirname(exe), filename)
    return filename


def regenerate_instance_config(config: dict, inst: dict) -> str:
    """Write a single-channel casparcg.config for one instance. Returns the path written."""
    port = instance_amcp_port(config, inst)
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <log-level>info</log-level>

  <channels>
    <!-- Instance: {inst['name']} -->
    <channel>
      <video-mode>{config['video_mode']}</video-mode>
      <consumers>
        <ndi>
          <name>{inst['ndi_name']}</name>
          <allow-fields>false</allow-fields>
        </ndi>
      </consumers>
    </channel>
  </channels>

  <paths>
    <media-path>media\\</media-path>
    <log-path>log\\</log-path>
    <data-path>data\\</data-path>
    <template-path>template\\</template-path>
  </paths>

  <controllers>
    <tcp>
      <port>{port}</port>
      <protocol>AMCP</protocol>
    </tcp>
  </controllers>

</configuration>
"""
    out_path = caspar_instance_config_path(config, inst)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return out_path


def regenerate_all_instance_configs(config: dict) -> list:
    """Regenerate config files for every instance. Returns list of paths written."""
    return [regenerate_instance_config(config, inst) for inst in config.get("instances", [])]
