"""Read/write app config and regenerate per-instance casparcg.config files."""
import json
import os
import sys


def _config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DEFAULT_CONFIG = {
    "caspar_exe_path": "",
    "amcp_base_port": 5250,
    "web_port": 5280,
    "startup_delay": 60,
    "video_mode": "1080p2500",
    "autostart_caspar": False,
    "instances": [],
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
    config.setdefault("instances", [])
    if config.get("startup_delay", 60) <= 15:
        config["startup_delay"] = 60

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
    """Write a single-channel casparcg.config for one instance. Returns the path written.

    Each instance gets its own log/inst_N and data/inst_N subdirectory to prevent file-locking
    conflicts when multiple CasparCG processes run from the same folder simultaneously.
    """
    port = instance_amcp_port(config, inst)
    inst_id = inst["id"]

    import shutil

    exe = config.get("caspar_exe_path", "")
    if exe and os.path.isabs(exe):
        exe_dir = os.path.dirname(exe)
        for subdir in (f"log\\inst_{inst_id}", f"data\\inst_{inst_id}"):
            os.makedirs(os.path.join(exe_dir, subdir), exist_ok=True)
        # Wipe the CEF session cache before each start so Chromium never shows
        # a "Restore pages?" dialog from a previous abrupt kill.
        html_cache = os.path.join(exe_dir, f"html_cache\\inst_{inst_id}")
        shutil.rmtree(html_cache, ignore_errors=True)
        os.makedirs(html_cache, exist_ok=True)

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
    <log-path>log\\inst_{inst_id}\\</log-path>
    <data-path>data\\inst_{inst_id}\\</data-path>
    <template-path>template\\</template-path>
  </paths>

  <controllers>
    <tcp>
      <port>{port}</port>
      <protocol>AMCP</protocol>
    </tcp>
  </controllers>

  <html>
    <remote-debugging-port>0</remote-debugging-port>
    <enable-gpu>false</enable-gpu>
    <cache-path>html_cache\\inst_{inst_id}\\</cache-path>
  </html>

</configuration>
"""
    out_path = caspar_instance_config_path(config, inst)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return out_path


def regenerate_all_instance_configs(config: dict) -> list:
    """Regenerate config files for every instance. Returns list of paths written."""
    return [regenerate_instance_config(config, inst) for inst in config.get("instances", [])]


_TEST_COLOURS = {
    "TEST_BLACK": (0,   0,   0),
    "TEST_WHITE": (255, 255, 255),
    "TEST_RED":   (255, 0,   0),
    "TEST_GREEN": (0,   255, 0),
    "TEST_BLUE":  (0,   0,   255),
    "TEST_GREY":  (128, 128, 128),
}

# 7 standard EBU/SMPTE colour bar stripes (100%)
_SMPTE_BARS = [
    (255, 255, 255),  # White
    (255, 255,   0),  # Yellow
    (  0, 255, 255),  # Cyan
    (  0, 255,   0),  # Green
    (255,   0, 255),  # Magenta
    (255,   0,   0),  # Red
    (  0,   0, 255),  # Blue
]


def _make_bars_image():
    from PIL import Image, ImageDraw
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    bar_w = W // len(_SMPTE_BARS)
    for i, colour in enumerate(_SMPTE_BARS):
        x0 = i * bar_w
        x1 = x0 + bar_w if i < len(_SMPTE_BARS) - 1 else W
        draw.rectangle([x0, 0, x1, H], fill=colour)
    return img


def ensure_test_pattern_images(config: dict) -> None:
    """Write solid-colour and bars PNG test patterns into the CasparCG media folder.

    Called on every server start so test clips are always available.
    Skips if exe path is not set or media folder doesn't exist yet.
    """
    exe = config.get("caspar_exe_path", "")
    if not exe or not os.path.isabs(exe):
        return
    media_dir = os.path.join(os.path.dirname(exe), "media")
    os.makedirs(media_dir, exist_ok=True)
    try:
        from PIL import Image
        for name, rgb in _TEST_COLOURS.items():
            path = os.path.join(media_dir, f"{name}.png")
            if not os.path.exists(path):
                Image.new("RGB", (1920, 1080), rgb).save(path)
        bars_path = os.path.join(media_dir, "TEST_BARS.png")
        if not os.path.exists(bars_path):
            _make_bars_image().save(bars_path)
    except Exception:
        pass
