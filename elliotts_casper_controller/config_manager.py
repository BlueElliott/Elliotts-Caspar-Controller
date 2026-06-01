"""Read/write app config and regenerate casparcg.config."""
import json
import os
import sys
import xml.etree.ElementTree as ET


def _config_dir() -> str:
    """Return the directory where the app config file should live.
    When frozen (exe): same folder as the exe.
    When running from source: project root (parent of this package).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DEFAULT_CONFIG = {
    "caspar_exe_path": "casparcg.exe",
    "amcp_port": 5250,
    "web_port": 5280,
    "startup_delay": 8,
    "video_mode": "1080p2500",
    "autostart_caspar": False,
    "channels": [
        {"number": 1, "name": "GFX1",   "ndi_name": "PCR3 GFX1",   "type": "html", "url": "https://app.singular.live/output/66B4M4gG2cjcbEEP51ORwU/Output?aspect=16:9&g_custom1=GFX1",   "startup_command": ""},
        {"number": 2, "name": "GFX2",   "ndi_name": "PCR3 GFX2",   "type": "html", "url": "https://app.singular.live/output/66B4M4gG2cjcbEEP51ORwU/Output?aspect=16:9&g_custom1=GFX2",   "startup_command": ""},
        {"number": 3, "name": "GFX3",   "ndi_name": "PCR3 GFX3",   "type": "html", "url": "https://app.singular.live/output/66B4M4gG2cjcbEEP51ORwU/Output?aspect=16:9&g_custom1=GFX3",   "startup_command": ""},
        {"number": 4, "name": "GFX4",   "ndi_name": "PCR3 GFX4",   "type": "html", "url": "https://app.singular.live/output/66B4M4gG2cjcbEEP51ORwU/Output?aspect=16:9&g_custom1=GFX4",   "startup_command": ""},
        {"number": 5, "name": "GFXPVW", "ndi_name": "PCR3 GFXPVW", "type": "html", "url": "https://app.singular.live/output/66B4M4gG2cjcbEEP51ORwU/Output?aspect=16:9&g_custom1=GFXPVW", "startup_command": ""},
    ],
}

CASPAR_CONFIG_FILENAME = "casparcg.config"


def _config_file() -> str:
    return os.path.join(_config_dir(), "elliotts_casper_config.json")


def load() -> dict:
    cfg_file = _config_file()
    if os.path.exists(cfg_file):
        with open(cfg_file, "r") as f:
            stored = json.load(f)
        config = dict(DEFAULT_CONFIG)
        config.update(stored)
    else:
        config = dict(DEFAULT_CONFIG)
    # Backfill new top-level fields on older configs
    config.setdefault("autostart_caspar", False)
    # Backfill per-channel fields
    for ch in config.get("channels", []):
        ch.setdefault("type", "html")
        ch.setdefault("startup_command", "")
        ch.setdefault("url", "")
    return config


def save(config: dict) -> None:
    with open(_config_file(), "w") as f:
        json.dump(config, f, indent=2)


def caspar_config_path(config: dict) -> str:
    """Return the path where casparcg.config should be written (same dir as exe)."""
    exe = config.get("caspar_exe_path", "")
    if exe and os.path.isabs(exe):
        return os.path.join(os.path.dirname(exe), CASPAR_CONFIG_FILENAME)
    return CASPAR_CONFIG_FILENAME


def regenerate_caspar_config(config: dict) -> str:
    """Write casparcg.config next to casparcg.exe. Returns the path written."""
    channels_xml = ""
    for ch in config["channels"]:
        channels_xml += f"""
    <!-- Channel {ch['number']}: {ch['name']} -->
    <channel>
      <video-mode>{config['video_mode']}</video-mode>
      <consumers>
        <ndi>
          <name>{ch['ndi_name']}</name>
          <allow-fields>false</allow-fields>
        </ndi>
      </consumers>
    </channel>
"""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <log-level>info</log-level>

  <channels>
{channels_xml.rstrip()}
  </channels>

  <paths>
    <media-path>media\\</media-path>
    <log-path>log\\</log-path>
    <data-path>data\\</data-path>
    <template-path>template\\</template-path>
  </paths>

  <controllers>
    <tcp>
      <port>{config['amcp_port']}</port>
      <protocol>AMCP</protocol>
    </tcp>
  </controllers>

</configuration>
"""
    out_path = caspar_config_path(config)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return out_path


def import_from_caspar_config(xml_path: str, existing_config: dict) -> dict:
    """Parse an existing casparcg.config XML and merge settings into existing_config."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    config = dict(existing_config)

    # AMCP port
    port_el = root.find(".//controllers/tcp/port")
    if port_el is not None and port_el.text:
        try:
            config["amcp_port"] = int(port_el.text.strip())
        except ValueError:
            pass

    # Channels — pick up video-mode and NDI names
    channels_el = root.findall(".//channels/channel")
    if channels_el:
        # Use existing channel list as base, just update what we find
        existing_channels = {ch["number"]: dict(ch) for ch in config["channels"]}
        for i, ch_el in enumerate(channels_el, start=1):
            vm = ch_el.find("video-mode")
            if vm is not None and vm.text:
                config["video_mode"] = vm.text.strip()  # last one wins (all same)
            ndi_name = ch_el.find(".//consumers/ndi/name")
            if i in existing_channels and ndi_name is not None and ndi_name.text:
                existing_channels[i]["ndi_name"] = ndi_name.text.strip()
        config["channels"] = [existing_channels[n] for n in sorted(existing_channels)]

    return config
