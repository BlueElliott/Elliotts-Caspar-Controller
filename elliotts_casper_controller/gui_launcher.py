"""Tkinter desktop launcher for Elliott's Caspar Controller."""
import logging
import math
import os
import socket
import sys
import threading
import time
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

import psutil
import pystray
from PIL import Image, ImageDraw, ImageTk

from elliotts_casper_controller import __version__
from elliotts_casper_controller.amcp_client import AMCPClient
from elliotts_casper_controller.config_manager import (
    load as load_config, save as save_config,
    instance_amcp_port, regenerate_instance_config, regenerate_all_instance_configs,
)
from elliotts_casper_controller.process_manager import CasparProcessManager

# Set Windows taskbar app ID
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "elliott.caspercontroller.ecc.1"
    )
except Exception:
    pass

logger = logging.getLogger(__name__)


def _get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def _kill_port(port: int) -> None:
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
BG_DARK   = "#1a1a1a"
BG_MEDIUM = "#252525"
BG_CARD   = "#2d2d2d"
ACCENT    = "#00bcd4"
ACCENT_DK = "#0097a7"
TEXT      = "#ffffff"
MUTED     = "#888888"
BTN_BLUE  = "#2196f3"
BTN_CASPAR= "#006978"  # dark teal — CasparCG console button
BTN_GREEN = "#4caf50"
BTN_RED   = "#ff5252"
BTN_RED_DK= "#c0392b"
BTN_GRAY  = "#3d3d3d"
BTN_ORNG  = "#e67e22"
SUCCESS   = "#22c55e"
ERROR     = "#ef4444"
WARNING   = "#f59e0b"


# ---------------------------------------------------------------------------
# Main GUI class
# ---------------------------------------------------------------------------

class CasparControllerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Elliott's Caspar Controller  v{__version__}")
        self.root.resizable(False, True)
        self.root.minsize(750, 600)
        self.root.configure(bg=BG_DARK)

        self._cfg = load_config()
        self._web_port = self._cfg.get("web_port", 5280)

        self._caspar_running = False
        self._web_running = False
        self._start_time = time.time()
        self._pulse_angle = 0
        self._pulse_image_ref = None

        # Multi-instance managers: inst_id -> CasparProcessManager
        self._managers: dict = {}
        self._server_thread: threading.Thread | None = None
        self._uvicorn_server = None

        self._tray_icon: pystray.Icon | None = None

        self._load_fonts()
        self._set_window_icon()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.root.after(100, self._fit_window_height)
        self.root.after(400, self._start_web_server)
        self._update_pulse()
        self._update_runtime()
        self._poll_caspar_status()

    # -----------------------------------------------------------------------
    # Fonts & icon
    # -----------------------------------------------------------------------

    def _load_fonts(self):
        static = Path(__file__).parent.parent / "static"
        has_reem = (static / "ITV Reem-Regular.ttf").exists()
        fam = "ITV Reem" if has_reem else "Segoe UI"
        self.font_reg    = (fam, 10)
        self.font_reg11  = (fam, 11)
        self.font_reg24  = (fam, 24)
        self.font_bold   = (fam, 10, "bold")
        self.font_bold11 = (fam, 11, "bold")
        self.font_bold24 = (fam, 24, "bold")
        self.font_bold32 = (fam, 32, "bold")

    def _set_window_icon(self):
        try:
            ico = Path(__file__).parent.parent / "static" / "esc_icon.ico"
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Canvas helpers
    # -----------------------------------------------------------------------

    def _rounded_rect(self, canvas, x1, y1, x2, y2, r, fill):
        canvas.create_oval(x1, y1, x1+r*2, y1+r*2, fill=fill, outline=fill)
        canvas.create_oval(x2-r*2, y1, x2, y1+r*2, fill=fill, outline=fill)
        canvas.create_oval(x1, y2-r*2, x1+r*2, y2, fill=fill, outline=fill)
        canvas.create_oval(x2-r*2, y2-r*2, x2, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x1+r, y1, x2-r, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x1, y1+r, x2, y2-r, fill=fill, outline=fill)

    def _make_btn(self, parent, text, cmd, color, w=290, h=50, state=tk.NORMAL):
        cv = tk.Canvas(parent, width=w, height=h, bg=BG_DARK,
                       highlightthickness=0, bd=0)
        self._rounded_rect(cv, 0, 0, w, h, 10, color)
        fg = TEXT if state == tk.NORMAL else MUTED
        cv.create_text(w/2, h/2, text=text, fill=fg, font=self.font_bold11)
        if state == tk.NORMAL:
            cv.bind("<Button-1>", lambda e: cmd())
            cv.bind("<Enter>",    lambda e: cv.configure(cursor="hand2"))
            cv.bind("<Leave>",    lambda e: cv.configure(cursor=""))
        cv._color = color
        cv._state = state
        return cv

    def _redraw_btn(self, cv, text, color=None, state=tk.NORMAL):
        color = color or cv._color
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        self._rounded_rect(cv, 0, 0, w, h, 10, color)
        fg = TEXT if state == tk.NORMAL else MUTED
        cv.create_text(w/2, h/2, text=text, fill=fg, font=self.font_bold11)
        cv._color = color
        cv._state = state

    def _enable_btn(self, cv, cmd, text=None, color=None):
        if text or color:
            self._redraw_btn(cv, text or "", color or cv._color, tk.NORMAL)
        cv._state = tk.NORMAL
        cv.bind("<Button-1>", lambda e: cmd())
        cv.bind("<Enter>",    lambda e: cv.configure(cursor="hand2"))
        cv.bind("<Leave>",    lambda e: cv.configure(cursor=""))

    def _disable_btn(self, cv, text=None):
        self._redraw_btn(cv, text or "", state=tk.DISABLED)
        cv._state = tk.DISABLED
        cv.unbind("<Button-1>")
        cv.configure(cursor="")

    # -----------------------------------------------------------------------
    # Build UI
    # -----------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ---- Title ----
        top = tk.Frame(root, bg=BG_DARK, height=70)
        top.pack(fill=tk.X, padx=40, pady=(28, 0))
        top.pack_propagate(False)
        title_f = tk.Frame(top, bg=BG_DARK)
        title_f.pack(expand=True)
        tk.Label(title_f, text="Elliott's Caspar Controller",
                 font=self.font_bold24, bg=BG_DARK, fg=TEXT).pack()
        tk.Label(title_f, text=f"Version {__version__}",
                 font=self.font_reg, bg=BG_DARK, fg=MUTED).pack()

        # ---- Content ----
        content = tk.Frame(root, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True, padx=40, pady=(18, 20))

        # -- Port card (Web UI port only — AMCP ports managed in Settings) --
        port_cv = tk.Canvas(content, width=670, height=130,
                             bg=BG_DARK, highlightthickness=0)
        port_cv.pack(pady=(0, 12))
        self._rounded_rect(port_cv, 0, 0, 670, 130, 20, BG_CARD)

        cx = 335  # centre of 670-wide canvas
        port_cv.create_text(cx, 20, text="WEB UI PORT", fill=MUTED, font=self.font_bold)
        self._rounded_rect(port_cv, cx - 70, 32, cx + 70, 82, 12, ACCENT)
        self._port_text_id = port_cv.create_text(
            cx, 57, text=str(self._web_port), fill=TEXT, font=self.font_bold32
        )
        self._rounded_rect(port_cv, cx - 55, 92, cx + 55, 118, 12, BG_MEDIUM)
        port_cv.create_text(cx, 105, text="Change Port", fill=MUTED, font=(self.font_reg[0], 9))

        def _port_card_click(e):
            if (cx - 55) <= e.x <= (cx + 55) and 92 <= e.y <= 118:
                self._change_web_port(port_cv)
        port_cv.bind("<Button-1>", _port_card_click)
        port_cv.bind("<Enter>",    lambda e: port_cv.configure(cursor="hand2"))
        port_cv.bind("<Leave>",    lambda e: port_cv.configure(cursor=""))
        self._port_cv = port_cv

        # -- URL row: Network (left) | Local (right) --
        local_ip = _get_local_ip()
        self._network_url = f"http://{local_ip}:{self._web_port}"
        url_row = tk.Frame(content, bg=BG_DARK)
        url_row.pack(pady=(0, 8))

        tk.Label(url_row, text="Network:", font=self.font_reg11,
                 bg=BG_DARK, fg=MUTED).pack(side=tk.LEFT, padx=(0, 4))
        self._net_label = tk.Label(url_row, text=self._network_url,
                                   font=self.font_reg11, bg=BG_DARK, fg=ACCENT, cursor="hand2")
        self._net_label.pack(side=tk.LEFT)
        self._net_label.bind("<Button-1>", lambda e: self._copy_url())
        self._net_label.bind("<Enter>",    lambda e: self._net_label.config(fg=TEXT))
        self._net_label.bind("<Leave>",    lambda e: self._net_label.config(fg=ACCENT))

        tk.Label(url_row, text="   |   Local:", font=self.font_reg11,
                 bg=BG_DARK, fg=MUTED).pack(side=tk.LEFT)
        self._url_label = tk.Label(url_row, text=f"http://127.0.0.1:{self._web_port}/",
                                   font=self.font_reg11, bg=BG_DARK, fg=MUTED)
        self._url_label.pack(side=tk.LEFT, padx=(4, 0))

        # -- Status row (pulse + label) --
        status_f = tk.Frame(content, bg=BG_DARK)
        status_f.pack(pady=(0, 2))
        self._pulse_label = tk.Label(status_f, bg=BG_DARK, bd=0, highlightthickness=0)
        self._pulse_label.pack(side=tk.LEFT, padx=(0, 8))
        self._status_label = tk.Label(status_f, text="Web server starting...",
                                       font=self.font_reg11, bg=BG_DARK, fg=MUTED)
        self._status_label.pack(side=tk.LEFT)

        # -- Controller uptime row --
        runtime_f = tk.Frame(content, bg=BG_DARK)
        runtime_f.pack(pady=(0, 6))
        tk.Label(runtime_f, text="Controller Uptime:", font=self.font_reg,
                 bg=BG_DARK, fg=MUTED).pack(side=tk.LEFT)
        self._runtime_label = tk.Label(runtime_f, text="—", font=self.font_reg,
                                        bg=BG_DARK, fg=MUTED)
        self._runtime_label.pack(side=tk.LEFT, padx=(4, 0))

        # -- Action buttons --
        btn_area = tk.Frame(content, bg=BG_DARK)
        btn_area.pack(pady=(0, 6))

        row1 = tk.Frame(btn_area, bg=BG_DARK)
        row1.pack(pady=4)
        self._btn_start = self._make_btn(row1, "Start CasparCG", self._start_caspar, BTN_GREEN, h=46)
        self._btn_start.pack(side=tk.LEFT, padx=6)
        self._btn_stop = self._make_btn(row1, "Stop CasparCG", self._stop_caspar, BTN_RED, h=46, state=tk.DISABLED)
        self._btn_stop.pack(side=tk.LEFT, padx=6)

        row2 = tk.Frame(btn_area, bg=BG_DARK)
        row2.pack(pady=4)
        self._btn_web = self._make_btn(row2, "Open Web UI", self._open_browser, BTN_BLUE, h=46, state=tk.DISABLED)
        self._btn_web.pack(side=tk.LEFT, padx=6)
        self._btn_update = self._make_btn(row2, "Check for Updates", self._check_updates, ACCENT, h=46)
        self._btn_update.pack(side=tk.LEFT, padx=6)

        row3 = tk.Frame(btn_area, bg=BG_DARK)
        row3.pack(pady=4)
        self._make_btn(row3, "Hide to Tray", self._hide_to_tray, BTN_GRAY, h=46).pack(side=tk.LEFT, padx=6)
        self._make_btn(row3, "Quit", self._on_close, BTN_RED_DK, h=46).pack(side=tk.LEFT, padx=6)

    def _fit_window_height(self):
        self.root.update_idletasks()
        self.root.geometry(f"750x{self.root.winfo_reqheight()}")

    # -----------------------------------------------------------------------
    # Port card
    # -----------------------------------------------------------------------

    def _change_web_port(self, port_cv):
        new_port = simpledialog.askinteger(
            "Change Web UI Port", "Enter new port number:",
            initialvalue=self._web_port, minvalue=1024, maxvalue=65535,
            parent=self.root,
        )
        if new_port and new_port != self._web_port:
            self._web_port = new_port
            cfg = load_config()
            cfg["web_port"] = new_port
            save_config(cfg)
            port_cv.itemconfig(self._port_text_id, text=str(new_port))
            self._url_label.config(text=f"http://127.0.0.1:{new_port}/")
            messagebox.showinfo("Port Changed",
                                f"Web UI port changed to {new_port}.\nRestart the app for the new port to take effect.",
                                parent=self.root)


    def _copy_url(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._network_url)
            self.root.update()
            orig = self._status_label.cget("text")
            self._status_label.config(text=f"✓ Copied: {self._network_url}")
            self.root.after(2000, lambda: self._status_label.config(text=orig))
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Pulse animation
    # -----------------------------------------------------------------------

    def _update_pulse(self):
        size, scale = 40, 4
        big = size * scale
        bg_rgb = (26, 26, 26)
        r_on, g_on, b_on = 80, 180, 255
        r_off, g_off, b_off = 100, 100, 100

        if self._web_running:
            self._pulse_angle = (self._pulse_angle + 8) % 360
            def _blend(phase):
                op = (math.sin(math.radians(phase)) + 1) / 2
                return (
                    int(bg_rgb[0] + (r_on - bg_rgb[0]) * op),
                    int(bg_rgb[1] + (g_on - bg_rgb[1]) * op),
                    int(bg_rgb[2] + (b_on - bg_rgb[2]) * op),
                )
            c_center = _blend(self._pulse_angle)
            c_inner  = _blend(self._pulse_angle - 90)
            c_outer  = _blend(self._pulse_angle - 180)
        else:
            c_center = c_inner = c_outer = (r_off, g_off, b_off)

        img = Image.new("RGB", (big, big), bg_rgb)
        d = ImageDraw.Draw(img)
        cx = cy = big // 2
        for radius, color, filled in [
            (18 * scale, c_outer, False),
            (11 * scale, c_inner, False),
            (5  * scale, c_center, True),
        ]:
            box = [cx - radius, cy - radius, cx + radius, cy + radius]
            if filled:
                d.ellipse(box, fill=color)
            else:
                d.ellipse(box, outline=color, width=3 * scale)

        img = img.resize((size, size), Image.LANCZOS)
        self._pulse_image_ref = ImageTk.PhotoImage(img)
        self._pulse_label.configure(image=self._pulse_image_ref)
        self.root.after(40, self._update_pulse)

    # -----------------------------------------------------------------------
    # Runtime counter
    # -----------------------------------------------------------------------

    @staticmethod
    def _fmt_elapsed(seconds: int) -> str:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def _update_runtime(self):
        if self._web_running:
            elapsed = int(time.time() - self._start_time)
            self._runtime_label.config(text=self._fmt_elapsed(elapsed), fg=ACCENT)
        else:
            self._runtime_label.config(text="—", fg=MUTED)
        self.root.after(1000, self._update_runtime)

    # -----------------------------------------------------------------------
    # Web server
    # -----------------------------------------------------------------------

    def _start_web_server(self):
        import uvicorn
        from elliotts_casper_controller.core import app

        if _is_port_in_use(self._web_port):
            _kill_port(self._web_port)
            time.sleep(0.4)

        import logging
        for _log_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            _lg = logging.getLogger(_log_name)
            _lg.handlers = [logging.NullHandler()]
            _lg.propagate = False

        cfg_obj = uvicorn.Config(app, host="0.0.0.0", port=self._web_port,
                                  log_level="warning", access_log=False,
                                  log_config=None)
        self._uvicorn_server = uvicorn.Server(cfg_obj)
        self._server_error: str | None = None

        def run():
            try:
                self._uvicorn_server.run()
            except Exception as exc:
                self._server_error = str(exc)
                import traceback
                tb = traceback.format_exc()
                try:
                    from elliotts_casper_controller.config_manager import _config_dir
                    log_path = os.path.join(_config_dir(), "webserver_error.log")
                    with open(log_path, "w") as f:
                        f.write(f"Server error: {exc}\n\n{tb}")
                except Exception:
                    pass

        self._server_thread = threading.Thread(target=run, daemon=True)
        self._server_thread.start()
        self.root.after(500, self._check_web_server_up, 0)

    def _check_web_server_up(self, attempt: int):
        if _is_port_in_use(self._web_port):
            self._web_running = True
            self._start_time = time.time()
            self._status_label.config(text=f"Web server running on port {self._web_port}", fg=ACCENT)
            self._enable_btn(self._btn_web, self._open_browser, "Open Web UI", BTN_BLUE)
            cfg = load_config()
            if cfg.get("autostart_caspar"):
                self.root.after(800, self._auto_start_caspar)
            # Silent update check on startup — shows button only if update found
            self.root.after(2000, lambda: self._check_updates(silent=True))
            return

        if self._server_error:
            self._status_label.config(text="Web server failed to start", fg=ERROR)
            messagebox.showerror(
                "Web Server Error",
                f"The web server failed to start on port {self._web_port}.\n\n{self._server_error}",
                parent=self.root,
            )
            return

        if attempt >= 24:
            self._status_label.config(text=f"Web server timed out on port {self._web_port}", fg=WARNING)
            messagebox.showwarning(
                "Web Server Timeout",
                f"The web server did not start within 12 seconds on port {self._web_port}.\n"
                "Check that the port is not in use and try restarting.",
                parent=self.root,
            )
            return

        self._status_label.config(text=f"Starting web server… (attempt {attempt + 1})", fg=MUTED)
        self.root.after(500, self._check_web_server_up, attempt + 1)

    def _open_browser(self):
        webbrowser.open(f"http://127.0.0.1:{self._web_port}")

    # -----------------------------------------------------------------------
    # CasparCG process management
    # -----------------------------------------------------------------------

    def _check_updates(self, silent: bool = False):
        if not silent:
            self._disable_btn(self._btn_update, "Checking...")
        def run():
            try:
                import requests as _req
                url = "https://api.github.com/repos/BlueElliott/Elliotts-Caspar-Controller/releases/latest"
                r = _req.get(url, headers={"User-Agent": "ElliotsCasparController"}, timeout=8)
                data = r.json()
                latest = data.get("tag_name", "").lstrip("v")
                current = __version__
                if latest and latest != current:
                    # Find the .exe asset download URL
                    exe_url = None
                    for asset in data.get("assets", []):
                        if asset.get("name", "").endswith(".exe"):
                            exe_url = asset.get("browser_download_url")
                            break
                    self.root.after(0, lambda: self._update_available(latest, data.get("html_url", ""), exe_url))
                else:
                    if not silent:
                        self.root.after(0, self._up_to_date)
            except Exception as e:
                if not silent:
                    self.root.after(0, lambda: self._update_error(str(e)))
        threading.Thread(target=run, daemon=True).start()

    def _update_available(self, latest: str, release_url: str, exe_url: str | None):
        if exe_url and getattr(sys, "frozen", False):
            # Running as a frozen exe — offer one-click auto-update
            self._pending_exe_url = exe_url
            self._pending_latest = latest
            self._redraw_btn(self._btn_update, f"Install v{latest}", BTN_ORNG, tk.NORMAL)
            self._enable_btn(self._btn_update, self._do_auto_update,
                             f"Install v{latest}", BTN_ORNG)
        else:
            # Running from source — open release page instead
            self._redraw_btn(self._btn_update, f"v{latest} Available!", BTN_ORNG, tk.NORMAL)
            self._enable_btn(self._btn_update, lambda: webbrowser.open(release_url),
                             f"v{latest} Available!", BTN_ORNG)
        self._status_label.config(text=f"Update available: v{latest}", fg=WARNING)

    def _do_auto_update(self):
        import requests as _req

        exe_url = getattr(self, "_pending_exe_url", None)
        latest = getattr(self, "_pending_latest", "?")
        if not exe_url:
            return

        confirmed = messagebox.askyesno(
            "Install Update",
            f"Download and install v{latest} now?\n\n"
            "The app will close and relaunch automatically.",
            parent=self.root,
        )
        if not confirmed:
            return

        self._disable_btn(self._btn_update, "Downloading...")
        self._status_label.config(text=f"Downloading v{latest}...", fg=MUTED)

        # Download into the same folder as the running exe so the swap script
        # doesn't have to cross drives or deal with temp-folder permissions.
        exe_dir = os.path.dirname(sys.executable)
        pending_exe = os.path.join(exe_dir, "ElliottsCasparController_update.exe")

        def download():
            try:
                r = _req.get(exe_url, stream=True, timeout=60,
                             headers={"User-Agent": "ElliotsCasparController"})
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(pending_exe, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = int(downloaded * 100 / total)
                                self.root.after(0, lambda p=pct: self._disable_btn(
                                    self._btn_update, f"Downloading {p}%..."))

                self.root.after(0, lambda: self._apply_update(pending_exe))

            except Exception as e:
                self.root.after(0, lambda: self._update_error(f"Download failed: {e}"))
                self.root.after(0, lambda: self._enable_btn(
                    self._btn_update, self._do_auto_update, f"Install v{latest}", BTN_ORNG))

        threading.Thread(target=download, daemon=True).start()

    def _apply_update(self, pending_exe: str):
        import subprocess

        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)
        exe_name = os.path.basename(current_exe)
        old_exe = os.path.join(exe_dir, exe_name + ".old")
        meipass = getattr(sys, "_MEIPASS", "")
        ps_path = os.path.join(exe_dir, "update.ps1")

        def ps_str(p: str) -> str:
            return "'" + p.replace("'", "''") + "'"

        lines = [
            f"$current = {ps_str(current_exe)}",
            f"$pending = {ps_str(pending_exe)}",
            f"$old     = {ps_str(old_exe)}",
            f"$meipass = {ps_str(meipass)}",
            "",
            # Step 1: retry moving current → old until the exe file is released.
            "$deadline = (Get-Date).AddSeconds(60)",
            "$moved = $false",
            "while (-not $moved -and (Get-Date) -lt $deadline) {",
            "    try {",
            "        if (Test-Path $old) { Remove-Item $old -Force -ErrorAction Stop }",
            "        Move-Item -Path $current -Destination $old -Force -ErrorAction Stop",
            "        $moved = $true",
            "    } catch {",
            "        Start-Sleep -Milliseconds 500",
            "    }",
            "}",
            "if (-not $moved) { Remove-Item -Path $pending -Force -ErrorAction SilentlyContinue; exit 1 }",
            "",
            # Step 2: delete the old _MEI folder so it can't interfere.
            "if ($meipass -and (Test-Path $meipass)) {",
            "    Remove-Item -Path $meipass -Recurse -Force -ErrorAction SilentlyContinue",
            "}",
            "",
            # Step 3: unblock + move new exe into place.
            "Unblock-File -Path $pending -ErrorAction SilentlyContinue",
            "try {",
            "    Move-Item -Path $pending -Destination $current -Force -ErrorAction Stop",
            "} catch {",
            "    Move-Item -Path $old -Destination $current -Force -ErrorAction SilentlyContinue",
            "    exit 1",
            "}",
            "",
            # Step 4: clean up .old and script — no auto-relaunch.
            # Windows Defender scans newly-placed exes on first execution and
            # blocks PyInstaller's DLL extraction mid-run. The user relaunches
            # from their shortcut (Explorer/ShellExecute) which handles the
            # first-run check before the process starts.
            "$dlDeadline = (Get-Date).AddSeconds(15)",
            "while ((Test-Path $old) -and (Get-Date) -lt $dlDeadline) {",
            "    try { Remove-Item -Path $old -Force -ErrorAction Stop; break }",
            "    catch { Start-Sleep -Milliseconds 500 }",
            "}",
            "Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue",
        ]
        with open(ps_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self._status_label.config(text="Update downloaded — close and reopen the app to finish.", fg=MUTED)

        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            [
                "powershell.exe", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", ps_path,
            ],
            creationflags=CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )

        # Show a clear message then close. The swap script runs in the background
        # and completes after this process exits.
        self.root.after(200, lambda: self._prompt_relaunch())

    def _prompt_relaunch(self):
        messagebox.showinfo(
            "Update Ready",
            "The update has been downloaded and will be applied when the app closes.\n\n"
            "Please reopen the app from your shortcut or taskbar after it closes.",
        )
        self._quit()

    def _up_to_date(self):
        self._redraw_btn(self._btn_update, "Up to Date ✓", SUCCESS, tk.NORMAL)
        self.root.after(3000, lambda: self._enable_btn(
            self._btn_update, self._check_updates, "Check for Updates", ACCENT))

    def _update_error(self, err: str):
        self._redraw_btn(self._btn_update, "Check Failed", BTN_GRAY, tk.NORMAL)
        self.root.after(3000, lambda: self._enable_btn(
            self._btn_update, self._check_updates, "Check for Updates", ACCENT))

    def _auto_start_caspar(self):
        self._status_label.config(text="Auto-starting CasparCG...", fg=MUTED)
        self._disable_btn(self._btn_start, "Auto-Starting...")
        self._start_caspar(_auto=True)

    def _start_caspar(self, _auto: bool = False):
        exe = load_config().get("caspar_exe_path", "").strip()
        if not os.path.isfile(exe):
            if not _auto:
                messagebox.showerror(
                    "CasparCG Not Found",
                    f"Cannot find:\n{exe or '(no path set)'}\n\n"
                    "Go to Web UI → Settings to set the CasparCG executable path.",
                    parent=self.root,
                )
            else:
                self._status_label.config(text="Auto-start: CasparCG exe not found — set path in Settings", fg=ERROR)
                self._enable_btn(self._btn_start, self._start_caspar, "Start CasparCG", BTN_GREEN)
            return
        if not _auto:
            self._disable_btn(self._btn_start, "Starting...")
        self._status_label.config(text="Starting CasparCG instances...", fg=MUTED)

        def run():
            try:
                cfg = load_config()
                instances = cfg.get("instances", [])
                regenerate_all_instance_configs(cfg)

                # Always kill every running CasparCG before launching fresh.
                # Conditional kill misses instances on stale ports and causes
                # processes to accumulate across multiple Start clicks.
                CasparProcessManager._kill_all_caspar_instances()

                self._managers = {}
                started = []
                errors = []

                # Sequential startup with 5s gap — NDI sources appear one at a time
                # in config order so Tricaster locks onto the correct source.
                for i, inst in enumerate(instances):
                    port = instance_amcp_port(cfg, inst)
                    m = CasparProcessManager(
                        exe_path=exe,
                        amcp_port=port,
                        startup_delay=cfg.get("startup_delay", 60),
                        window_title=f"PCR3 CasparCG — {inst['name']}",
                        config_filename=f"casparcg_inst_{inst['id']}.config",
                    )
                    self._managers[inst["id"]] = m
                    ok = m.start()
                    if ok:
                        res = self._send_instance_load(inst, AMCPClient(port=port))
                        logger.info(f"Inst {inst['id']} ({inst['name']}) → {res[:60]}")
                        started.append(inst["id"])
                        if i < len(instances) - 1:
                            time.sleep(5)  # let NDI source settle before announcing next
                    else:
                        logger.warning(f"Inst {inst['id']} ({inst['name']}) FAILED to start")
                        errors.append(inst["id"])

                self._sync_api_managers()
                if started:
                    self.root.after(0, lambda s=len(started), total=len(instances):
                                    self._on_caspar_started(s, total))
                else:
                    self._managers = {}
                    self._sync_api_managers()
                    self.root.after(0, lambda: self._on_caspar_failed(
                        "No CasparCG instances started successfully.\n"
                        "Check the exe path and that AMCP ports are free."
                    ))
            except Exception as exc:
                self._managers = {}
                self._sync_api_managers()
                self.root.after(0, lambda: self._on_caspar_failed(str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def _start_remaining(self):
        """Start only the instances that are not currently responding to AMCP ping.

        Does NOT kill running instances — avoids disrupting live CEF sessions
        and prevents the Chromium config-path popup on already-running instances.
        """
        exe = load_config().get("caspar_exe_path", "").strip()
        if not os.path.isfile(exe):
            messagebox.showerror("CasparCG Not Found",
                                 f"Cannot find:\n{exe or '(no path set)'}\n\n"
                                 "Go to Web UI → Settings to set the CasparCG executable path.",
                                 parent=self.root)
            return
        self._disable_btn(self._btn_start, "Starting...")
        self._status_label.config(text="Starting remaining instances...", fg=MUTED)

        def run():
            try:
                cfg = load_config()
                instances = cfg.get("instances", [])
                started = []
                errors = []
                first = True
                for i, inst in enumerate(instances):
                    port = instance_amcp_port(cfg, inst)
                    if AMCPClient(port=port).ping():
                        continue  # already live — leave it alone
                    if not first:
                        time.sleep(5)
                    first = False
                    from elliotts_casper_controller.config_manager import regenerate_instance_config
                    regenerate_instance_config(cfg, inst)
                    m = CasparProcessManager(
                        exe_path=exe,
                        amcp_port=port,
                        startup_delay=cfg.get("startup_delay", 60),
                        window_title=f"PCR3 CasparCG — {inst['name']}",
                        config_filename=f"casparcg_inst_{inst['id']}.config",
                    )
                    self._managers[inst["id"]] = m
                    ok = m.start()
                    if ok:
                        res = self._send_instance_load(inst, AMCPClient(port=port))
                        logger.info(f"Inst {inst['id']} ({inst['name']}) → {res[:60]}")
                        started.append(inst["id"])
                    else:
                        logger.warning(f"Inst {inst['id']} ({inst['name']}) FAILED to start")
                        errors.append(inst["id"])
                self._sync_api_managers()
                total = len(instances)
                live = sum(1 for inst in instances
                           if AMCPClient(port=instance_amcp_port(cfg, inst)).ping())
                self.root.after(0, lambda s=live, t=total: self._on_caspar_started(s, t))
            except Exception as exc:
                self.root.after(0, lambda: self._on_caspar_failed(str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def _on_caspar_started(self, started: int, total: int):
        self._caspar_running = True
        msg = f"CasparCG running — {started}/{total} instances loaded"
        self._status_label.config(text=msg, fg=SUCCESS)
        self._enable_btn(self._btn_start, self._start_caspar, "Start CasparCG", BTN_GREEN)
        self._enable_btn(self._btn_stop, self._stop_caspar, "Stop CasparCG", BTN_RED)
        logger.info(msg)

    def _on_caspar_failed(self, reason: str):
        self._status_label.config(text="CasparCG failed to start", fg=ERROR)
        self._enable_btn(self._btn_start, self._start_caspar, "Start CasparCG", BTN_GREEN)
        logger.error(f"CasparCG failed: {reason}")
        messagebox.showerror("CasparCG Failed", f"Could not start CasparCG:\n\n{reason}", parent=self.root)

    def _stop_caspar(self):
        def run():
            # Stop all managers in parallel for instant response
            threads = [threading.Thread(target=m.stop, daemon=True)
                       for m in list(self._managers.values())]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=3)
            # Kill any stragglers
            CasparProcessManager._kill_all_caspar_instances()
            self._managers = {}
            self._sync_api_managers()
            self.root.after(0, self._on_caspar_stopped)

        self._disable_btn(self._btn_stop, "Stopping...")
        threading.Thread(target=run, daemon=True).start()

    def _on_caspar_stopped(self):
        self._caspar_running = False
        self._status_label.config(text="CasparCG stopped", fg=MUTED)
        self._enable_btn(self._btn_stop, self._stop_caspar, "Stop CasparCG", BTN_RED)
        logger.info("CasparCG stopped.")

    def _sync_api_managers(self) -> None:
        """Mirror self._managers into core._managers so dashboard controls work."""
        import sys
        core = sys.modules.get("elliotts_casper_controller.core")
        if core is None:
            return
        try:
            for k in list(core._managers.keys()):
                if k not in self._managers:
                    del core._managers[k]
            for k, v in self._managers.items():
                core._managers[k] = v
        except Exception:
            pass

    def _try_adopt_instances(self):
        """Attempt to adopt any running CasparCG instances that we don't manage yet."""
        try:
            cfg = load_config()
            adopted = 0
            for inst in cfg.get("instances", []):
                if inst["id"] in self._managers:
                    continue
                port = instance_amcp_port(cfg, inst)
                if not AMCPClient(port=port).ping():
                    continue
                m = CasparProcessManager(
                    exe_path=cfg.get("caspar_exe_path", "casparcg.exe"),
                    amcp_port=port,
                    startup_delay=cfg["startup_delay"],
                    window_title=f"PCR3 CasparCG — {inst['name']}",
                    config_filename=f"casparcg_inst_{inst['id']}.config",
                )
                if m.adopt_existing():
                    self._managers[inst["id"]] = m
                    adopted += 1
            self._sync_api_managers()
            if adopted > 0:
                self._caspar_running = True
                self._status_label.config(
                    text=f"CasparCG running (reconnected {adopted} instance(s))", fg=SUCCESS)
                self._enable_btn(self._btn_stop, self._stop_caspar, "Stop CasparCG", BTN_RED)
                logger.info(f"Reconnected to {adopted} CasparCG instance(s).")
        except Exception:
            pass

    def _poll_caspar_status(self):
        def check():
            try:
                cfg = load_config()
                instances = cfg.get("instances", [])
                instance_states = {
                    inst["id"]: AMCPClient(port=instance_amcp_port(cfg, inst)).ping()
                    for inst in instances
                }
                running_count = sum(instance_states.values())
                overall = running_count > 0

                # Adopt any unmanaged running instances
                managed_ids = set(self._managers.keys())
                has_unmanaged = any(v and k not in managed_ids for k, v in instance_states.items())
                if has_unmanaged:
                    self.root.after(0, self._try_adopt_instances)

                if overall:
                    # Always update count so it reflects instances coming up/down during restarts
                    tot = len(instances)
                    all_up = running_count == tot
                    self.root.after(0, lambda rc=running_count, t=tot:
                                    self._status_label.config(
                                        text=f"CasparCG running — {rc}/{t} instances", fg=SUCCESS))
                    if all_up:
                        self.root.after(0, lambda: self._disable_btn(self._btn_start, "All Running"))
                    else:
                        remaining = tot - running_count
                        self.root.after(0, lambda r=remaining: self._enable_btn(
                            self._btn_start, self._start_remaining, f"Start Remaining ({r})", BTN_GREEN))
                    if not self._caspar_running:
                        self._caspar_running = True
                elif self._caspar_running:
                    self._caspar_running = False
                    self.root.after(0, self._on_caspar_stopped)
                else:
                    # Nothing running — ensure Start button is active
                    self.root.after(0, lambda: self._enable_btn(
                        self._btn_start, self._start_caspar, "Start CasparCG", BTN_GREEN))
            except Exception:
                pass
            self.root.after(4000, self._poll_caspar_status)

        threading.Thread(target=check, daemon=True).start()

    # -----------------------------------------------------------------------
    # Instance restart
    # -----------------------------------------------------------------------

    @staticmethod
    def _send_instance_load(inst: dict, client: AMCPClient) -> str:
        if inst.get("type", "html") == "html":
            url = inst.get("url", "").strip()
            return client.play_html(1, url) if url else client.send("CLEAR 1")
        cmd = inst.get("startup_command", "").strip()
        return client.send(cmd) if cmd else client.send("CLEAR 1")

    def _restart_inst(self, inst_id: int, name: str):
        """Stop the CasparCG process for one instance and relaunch it."""
        def run():
            cfg = load_config()
            inst_map = {i["id"]: i for i in cfg.get("instances", [])}
            inst = inst_map.get(inst_id)
            if not inst:
                return
            if inst_id in self._managers:
                self._managers[inst_id].stop()
            regenerate_instance_config(cfg, inst)
            port = instance_amcp_port(cfg, inst)
            m = CasparProcessManager(
                exe_path=cfg.get("caspar_exe_path", ""),
                amcp_port=port,
                startup_delay=cfg["startup_delay"],
                window_title=f"PCR3 CasparCG — {inst['name']}",
                config_filename=f"casparcg_inst_{inst_id}.config",
            )
            self._managers[inst_id] = m
            ok = m.start()
            if ok:
                res = self._send_instance_load(inst, AMCPClient(port=port))
                logger.info(f"Inst {inst_id} ({name}) restarted → {res[:60]}")
            else:
                logger.warning(f"Inst {inst_id} ({name}) failed to restart")
                self._managers.pop(inst_id, None)
            self._sync_api_managers()
        threading.Thread(target=run, daemon=True).start()

    def _restart_all(self):
        """Stop all CasparCG processes and relaunch them sequentially."""
        def run():
            cfg = load_config()
            instances = cfg.get("instances", [])
            for inst in instances:
                if inst["id"] in self._managers:
                    self._managers[inst["id"]].stop()
            for inst in instances:
                regenerate_instance_config(cfg, inst)
                port = instance_amcp_port(cfg, inst)
                m = CasparProcessManager(
                    exe_path=cfg.get("caspar_exe_path", ""),
                    amcp_port=port,
                    startup_delay=cfg["startup_delay"],
                    window_title=f"PCR3 CasparCG — {inst['name']}",
                    config_filename=f"casparcg_inst_{inst['id']}.config",
                )
                self._managers[inst["id"]] = m
                ok = m.start()
                if ok:
                    res = self._send_instance_load(inst, AMCPClient(port=port))
                    logger.info(f"Inst {inst['id']} restarted → {res[:60]}")
                else:
                    logger.warning(f"Inst {inst['id']} failed to restart")
                    self._managers.pop(inst["id"], None)
            self._sync_api_managers()
        threading.Thread(target=run, daemon=True).start()

    # -----------------------------------------------------------------------
    # Tray / close
    # -----------------------------------------------------------------------

    def _make_tray_image(self) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (26, 26, 26, 255))
        d = ImageDraw.Draw(img)
        cx, cy = 32, 32
        color = (0, 188, 212, 255)
        lw = 2
        for r in [22, 15, 8]:
            d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=lw)
        d.line([(cx, cy-22), (cx, 2)], fill=color, width=lw)
        d.line([(cx+22, cy), (62, cy)], fill=color, width=lw)
        d.line([(cx-4, cy+20), (8, 60)], fill=color, width=lw)
        return img

    def _hide_to_tray(self):
        self.root.withdraw()
        if not self._tray_icon:
            menu = pystray.Menu(
                pystray.MenuItem("Show Window",          lambda: self._show_from_tray()),
                pystray.MenuItem("Open Web UI",          lambda: self._open_browser()),
                pystray.MenuItem("Restart All Instances", lambda: self._restart_all()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit",                 lambda: self._quit()),
            )
            self._tray_icon = pystray.Icon(
                "ElliotsCasparController",
                self._make_tray_image(),
                "Elliott's Caspar Controller",
                menu,
            )
            threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_from_tray(self):
        self.root.deiconify()
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None

    def _on_close(self):
        if messagebox.askokcancel("Quit", "Quit Elliott's Caspar Controller?\n\nThe web server will stop.",
                                   parent=self.root):
            self._quit()

    def _quit(self):
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Run
    # -----------------------------------------------------------------------

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def launch():
    app = CasparControllerGUI()
    app.run()


def main():
    launch()


if __name__ == "__main__":
    main()
