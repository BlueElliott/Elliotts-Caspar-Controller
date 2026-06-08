# Elliott's Casper Controller

> Desktop app and web UI for managing multiple CasparCG NDI outputs from a single Windows machine.

[![Build Status](https://github.com/BlueElliott/Elliotts-Casper-Controller/actions/workflows/build.yml/badge.svg)](https://github.com/BlueElliott/Elliotts-Casper-Controller/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What it does

Elliott's Casper Controller launches and manages multiple CasparCG processes simultaneously — one per NDI output — from a single desktop GUI and web dashboard. Each instance gets its own AMCP port and NDI source name, so receivers (Tricasters, vMix, NDI Monitor, etc.) can independently subscribe to whichever outputs they need.

It was built for live broadcast workflows where you need several named NDI graphics outputs running reliably from one Windows PC.

---

## Features

- **Desktop GUI** — Native Windows launcher with system tray, status indicator, and controller uptime
- **Multi-instance CasparCG** — Each output is a separate CasparCG process with its own AMCP port and NDI name
- **Sequential startup** — Instances start one at a time with a gap between them, so NDI receivers latch onto the correct source
- **Web dashboard** — Live instance status, Start/Stop controls per instance, media clip picker, AMCP command input, event log
- **HTTP clip loading** — External devices (hardware controllers, Companion, automation systems) can load clips via a simple HTTP GET
- **HTTP Generator** — Built-in URL builder for generating and copying clip-load URLs
- **Settings page** — Configure the CasparCG path, video mode, AMCP ports, and manage instances (add, remove, reorder) from the browser
- **Check for Updates** — Checks GitHub releases and links directly to the latest version
- **Auto-start** — Optionally launch CasparCG automatically when the app starts

---

## Quick Start

### 1. Download both files from the [Releases page](https://github.com/BlueElliott/Elliotts-Casper-Controller/releases)

| File | What it is |
|------|------------|
| `ElliottsCasperController.exe` | The controller app |
| `LiteCasperServer.zip` | CasparCG Server — pre-configured, ready to use |

### 2. Set up CasparCG

1. Extract `LiteCasperServer.zip` to a permanent folder on your machine, e.g. `C:\CasparCG\`
2. Inside you'll find `casparcg.exe` — this is what the controller launches

> **NDI:** Make sure the [NDI Runtime](https://ndi.video/tools/) is installed on the machine so CasparCG can output NDI sources.

### 3. Run the controller

1. Run `ElliottsCasperController.exe` — no installation needed, no Python required
2. The desktop launcher opens. Click **Open Web UI** (or go to `http://127.0.0.1:5280` in a browser)

### 4. Configure

1. Go to **Settings** in the web UI
2. Set the **path to casparcg.exe** (e.g. `C:\CasparCG\casparcg.exe`) and click **Save Path**
3. Set your **Video Mode** (default: 1080p 25fps)
4. Under **Instances**, click **+ Add Instance** for each NDI output you want:
   - Give it a **Name** (used in the dashboard) and an **NDI Name** (how it appears on the network)
   - Set the **Type**: `HTML5` for web-based graphics (e.g. Singular.live), `Media` for video clip playback
   - For HTML5: enter the graphics URL. For Media: optionally enter a startup AMCP command
5. Click **Save & Regenerate Configs**

### 5. Start CasparCG

Click **Start All** on the Dashboard (or **Start CasparCG** in the desktop launcher). The app will:

1. Write a config file for each instance next to `casparcg.exe`
2. Kill any existing CasparCG processes
3. Launch each instance sequentially, waiting for AMCP to respond before moving to the next
4. Send each instance its startup command (load URL or play clip)

NDI sources will appear on the network named exactly as you configured them.

---

## HTTP Clip Loading

Any device on the same network can trigger a clip load via HTTP GET — no special integration needed.

```
GET http://<controller-ip>:<web-port>/api/load?instance=<name>&clip=<clip-name>
GET http://<controller-ip>:<web-port>/api/load?instance=<name>&clip=<clip-name>&loop=false
```

Go to **HTTP Generator** in the web UI to build and copy these URLs without typing.

Works from a web browser, `curl`, a Companion HTTP button, a touchscreen panel, or any automation system that can send HTTP GET requests.

---

## Web Interface

| URL | Page |
|-----|------|
| `http://<ip>:<port>/` | Dashboard — server controls, instance cards, media picker, event log |
| `http://<ip>:<port>/http-generator` | HTTP URL Generator |
| `http://<ip>:<port>/settings` | Settings — exe path, video mode, ports, instance editor |

Default web port is `5280`. Change it via the port card in the desktop launcher or in Settings.

The dashboard is accessible from any device on the network using the machine's IP address.

---

## Instance Types

| Type | What it does |
|------|-------------|
| `HTML5` | Sends `PLAY 1-1 [url]` to load a web graphics page (e.g. Singular.live, Vizrt Live, any URL) |
| `Media` | Sends a custom AMCP startup command, or `CLEAR 1` if left blank. Exposes a clip picker on the dashboard. |

---

## Requirements

- Windows 10 / 11
- [NDI Runtime](https://ndi.video/tools/) installed on the machine
- `LiteCasperServer.zip` from the [Releases page](https://github.com/BlueElliott/Elliotts-Casper-Controller/releases) (includes CasparCG)

### Running from source

```bash
git clone https://github.com/BlueElliott/Elliotts-Casper-Controller.git
cd Elliotts-Casper-Controller
pip install -r requirements.txt
python -m elliotts_casper_controller
```

Python 3.8+ required.

### PyPI

```bash
pip install elliotts-casper-controller
python -m elliotts_casper_controller
```

---

## Configuration file

Settings are saved to `elliotts_casper_config.json` next to the exe (or project root when running from source). You can edit this file directly, but it's easier to use the Settings page.

Per-instance CasparCG configs (`casparcg_inst_N.config`) are auto-generated next to `casparcg.exe` each time CasparCG is started. Do not edit these manually — they will be overwritten.

---

## Building the executable

```bash
pip install pyinstaller
pyinstaller ElliottsCasperController.spec
# Output: dist/ElliottsCasperController-X.X.X.exe
```

Releases are built automatically by GitHub Actions when a `v*.*.*` tag is pushed.

---

## Architecture

```
ElliottsCasperController.exe
├── Tkinter desktop window    (gui_launcher.py)
├── FastAPI web server         (core.py)            → http://0.0.0.0:<web-port>
├── AMCP TCP client            (amcp_client.py)     → localhost:<amcp-port>
├── CasparCG process manager   (process_manager.py)
└── Config manager             (config_manager.py)  → elliotts_casper_config.json
```

Each CasparCG instance is launched as a separate process with `CREATE_NEW_CONSOLE` so they get independent console windows. The web server and desktop GUI share process state via in-place dict mutation (`_sync_api_managers`).

---

## Known limitations

- **Windows only** — The process management and console handling use Windows-specific APIs.
- **NDI receiver sequencing** — If you start all instances simultaneously, some receivers may latch onto the wrong NDI source. The app starts instances sequentially with a 5-second gap to avoid this. Do not bypass this by starting instances manually in parallel.

---

## Issues

Report bugs at: https://github.com/BlueElliott/Elliotts-Casper-Controller/issues
