"""Tkinter desktop launcher for Elliott's Casper Controller."""
import logging
import math
import os
import socket
import sys
import threading
import time
import webbrowser
import tkinter as tk
from io import StringIO
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog

import psutil
import pystray
from PIL import Image, ImageDraw, ImageTk

from elliotts_casper_controller import __version__
from elliotts_casper_controller.amcp_client import AMCPClient
from elliotts_casper_controller.config_manager import load as load_config, save as save_config
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
BTN_GREEN = "#4caf50"
BTN_RED   = "#ff5252"
BTN_RED_DK= "#c0392b"
BTN_GRAY  = "#3d3d3d"
BTN_ORNG  = "#e67e22"
SUCCESS   = "#22c55e"
ERROR     = "#ef4444"


# ---------------------------------------------------------------------------
# Console redirect helpers
# ---------------------------------------------------------------------------

class _ConsoleRedirector:
    def __init__(self, widget):
        self._w = widget
        self._buf = StringIO()

    def write(self, msg):
        try:
            self._w.insert(tk.END, msg)
            self._w.see(tk.END)
        except Exception:
            pass
        self._buf.write(msg)

    def flush(self):
        pass


class _TkLogHandler(logging.Handler):
    def __init__(self, widget):
        super().__init__()
        self._w = widget

    def emit(self, record):
        try:
            self._w.insert(tk.END, self.format(record) + "\n")
            self._w.see(tk.END)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main GUI class
# ---------------------------------------------------------------------------

class CasperControllerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Elliott's Casper Controller  v{__version__}")
        self.root.geometry("750x740")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_DARK)

        self._cfg = load_config()
        self._web_port = self._cfg.get("web_port", 5280)
        self._amcp_port = self._cfg.get("amcp_port", 5250)

        self._caspar_running = False
        self._web_running = False
        self._start_time = time.time()
        self._pulse_angle = 0
        self._pulse_image_ref = None

        self._manager: CasparProcessManager | None = None
        self._server_thread: threading.Thread | None = None
        self._uvicorn_server = None

        self._tray_icon: pystray.Icon | None = None
        self._console_window = None
        self._console_text = None
        self._log_handler = None

        self._load_fonts()
        self._set_window_icon()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Auto-start web server
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
        tk.Label(title_f, text="Elliott's Casper Controller",
                 font=self.font_bold24, bg=BG_DARK, fg=TEXT).pack()
        tk.Label(title_f, text=f"Version {__version__}",
                 font=self.font_reg, bg=BG_DARK, fg=MUTED).pack()

        # ---- Content ----
        content = tk.Frame(root, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True, padx=40, pady=(18, 20))

        # -- Port card --
        port_cv = tk.Canvas(content, width=670, height=130,
                             bg=BG_DARK, highlightthickness=0)
        port_cv.pack(pady=(0, 12))
        self._rounded_rect(port_cv, 0, 0, 670, 130, 20, BG_CARD)

        # Web UI port (left)
        port_cv.create_text(220, 20, text="WEB UI PORT", fill=MUTED, font=self.font_bold)
        self._rounded_rect(port_cv, 150, 32, 290, 82, 12, ACCENT)
        self._port_text_id = port_cv.create_text(
            220, 57, text=str(self._web_port), fill=TEXT, font=self.font_bold32
        )
        self._rounded_rect(port_cv, 175, 92, 265, 118, 12, BG_MEDIUM)
        port_cv.create_text(220, 105, text="Change Port", fill=MUTED, font=(self.font_reg[0], 9))

        # AMCP port (right) — also clickable
        port_cv.create_text(480, 20, text="AMCP PORT", fill=MUTED, font=self.font_bold)
        self._rounded_rect(port_cv, 410, 32, 550, 82, 12, BTN_GRAY)
        self._amcp_text_id = port_cv.create_text(
            480, 57, text=str(self._amcp_port), fill=TEXT, font=self.font_bold32
        )
        self._rounded_rect(port_cv, 435, 92, 525, 118, 12, BG_MEDIUM)
        port_cv.create_text(480, 105, text="Change Port", fill=MUTED, font=(self.font_reg[0], 9))

        def _port_card_click(e):
            if 175 <= e.x <= 265 and 92 <= e.y <= 118:
                self._change_web_port(port_cv)
            elif 435 <= e.x <= 525 and 92 <= e.y <= 118:
                self._change_amcp_port(port_cv)
        port_cv.bind("<Button-1>", _port_card_click)
        port_cv.bind("<Enter>",    lambda e: port_cv.configure(cursor="hand2"))
        port_cv.bind("<Leave>",    lambda e: port_cv.configure(cursor=""))
        self._port_cv = port_cv

        # -- Network URL --
        local_ip = _get_local_ip()
        self._network_url = f"http://{local_ip}:{self._web_port}"
        self._net_label = tk.Label(content, text=f"Network: {self._network_url}",
                                    font=self.font_reg11, bg=BG_DARK, fg=ACCENT, cursor="hand2")
        self._net_label.pack(pady=(0, 8))
        self._net_label.bind("<Button-1>", lambda e: self._copy_url())
        self._net_label.bind("<Enter>",    lambda e: self._net_label.config(fg=TEXT))
        self._net_label.bind("<Leave>",    lambda e: self._net_label.config(fg=ACCENT))

        # -- Status row (pulse + label + runtime) --
        status_f = tk.Frame(content, bg=BG_DARK)
        status_f.pack(pady=(0, 4))
        self._pulse_label = tk.Label(status_f, bg=BG_DARK, bd=0, highlightthickness=0)
        self._pulse_label.pack(side=tk.LEFT, padx=(0, 8))
        self._status_label = tk.Label(status_f, text="Web server starting...",
                                       font=self.font_reg11, bg=BG_DARK, fg=MUTED)
        self._status_label.pack(side=tk.LEFT)
        self._runtime_label = tk.Label(status_f, text="", font=self.font_reg,
                                        bg=BG_DARK, fg=MUTED)
        self._runtime_label.pack(side=tk.LEFT, padx=(16, 0))

        self._url_label = tk.Label(content, text=f"http://127.0.0.1:{self._web_port}/",
                                    font=self.font_reg, bg=BG_DARK, fg=MUTED)
        self._url_label.pack(pady=(0, 6))

        # -- CasparCG path info (read-only — edit via Web UI Settings) --
        self._path_var = tk.StringVar(value=self._cfg.get("caspar_exe_path", "casparcg.exe"))
        info_f = tk.Frame(content, bg=BG_CARD, pady=7, padx=14)
        info_f.pack(fill=tk.X, pady=(0, 10))
        tk.Label(info_f, text="CasparCG:", font=self.font_bold, bg=BG_CARD, fg=MUTED,
                 width=10, anchor="w").pack(side=tk.LEFT)
        self._exe_display = tk.Label(info_f, textvariable=self._path_var,
                                      bg=BG_CARD, fg=TEXT, font=self.font_reg,
                                      anchor="w", justify="left")
        self._exe_display.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 10))
        tk.Label(info_f, text="Configure in Web UI → Settings",
                  bg=BG_CARD, fg=ACCENT, font=(self.font_reg[0], 9),
                  cursor="hand2").pack(side=tk.LEFT)

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
        self._btn_console = self._make_btn(row2, "Open Console", self._toggle_console, BTN_GRAY, h=46)
        self._btn_console.pack(side=tk.LEFT, padx=6)

        row3 = tk.Frame(btn_area, bg=BG_DARK)
        row3.pack(pady=4)
        self._btn_update = self._make_btn(row3, "Check for Updates", self._check_updates, ACCENT, h=46)
        self._btn_update.pack(side=tk.LEFT, padx=6)
        self._make_btn(row3, "Hide to Tray", self._hide_to_tray, BTN_GRAY, h=46).pack(side=tk.LEFT, padx=6)

        row4 = tk.Frame(btn_area, bg=BG_DARK)
        row4.pack(pady=4)
        self._make_btn(row4, "Quit", self._on_close, BTN_RED_DK, h=46).pack(side=tk.LEFT, padx=6)

        # -- Channel restarts --
        ch_outer = tk.Frame(content, bg=BG_DARK)
        ch_outer.pack(fill=tk.X, pady=(4, 0))
        tk.Label(ch_outer, text="CHANNEL RESTARTS", font=self.font_bold,
                 bg=BG_DARK, fg=MUTED).pack(anchor="w", pady=(0, 6))
        ch_row = tk.Frame(ch_outer, bg=BG_DARK)
        ch_row.pack(fill=tk.X)
        self._cfg = load_config()
        for ch in self._cfg["channels"]:
            self._make_btn(
                ch_row, f"↺  {ch['name']}",
                lambda n=ch["number"], name=ch["name"]: self._restart_ch(n, name),
                BTN_GRAY, w=110, h=38,
            ).pack(side=tk.LEFT, padx=(0, 6))
        self._make_btn(
            ch_row, "↺  All", self._restart_all,
            BTN_ORNG, w=90, h=38,
        ).pack(side=tk.LEFT, padx=(0, 6))

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

    def _change_amcp_port(self, port_cv):
        new_port = simpledialog.askinteger(
            "Change AMCP Port", "Enter CasparCG AMCP port:",
            initialvalue=self._amcp_port, minvalue=1024, maxvalue=65535,
            parent=self.root,
        )
        if new_port and new_port != self._amcp_port:
            self._amcp_port = new_port
            cfg = load_config()
            cfg["amcp_port"] = new_port
            save_config(cfg)
            port_cv.itemconfig(self._amcp_text_id, text=str(new_port))
            messagebox.showinfo("AMCP Port Changed",
                                f"AMCP port changed to {new_port}.\nRestart CasparCG for changes to take effect.",
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

    def _update_runtime(self):
        if self._web_running:
            elapsed = int(time.time() - self._start_time)
            h, rem = divmod(elapsed, 3600)
            m, s   = divmod(rem, 60)
            if h:
                rt = f"Runtime: {h}h {m}m {s}s"
            elif m:
                rt = f"Runtime: {m}m {s}s"
            else:
                rt = f"Runtime: {s}s"
            self._runtime_label.config(text=rt)
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

        # Suppress uvicorn's StreamHandlers — in a windowed exe sys.stderr may
        # be None and any write to it kills the server thread silently.
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
                # Write to a log file next to exe so we can read it even without a console
                try:
                    from elliotts_casper_controller.config_manager import _config_dir
                    log_path = os.path.join(_config_dir(), "webserver_error.log")
                    with open(log_path, "w") as f:
                        f.write(f"Server error: {exc}\n\n{tb}")
                except Exception:
                    pass

        self._server_thread = threading.Thread(target=run, daemon=True)
        self._server_thread.start()

        # Poll until the port is actually listening (max 12 s)
        self.root.after(500, self._check_web_server_up, 0)

    def _check_web_server_up(self, attempt: int):
        """Poll until the web server is listening, then update UI. Max 24 attempts × 500 ms = 12 s."""
        if _is_port_in_use(self._web_port):
            self._web_running = True
            self._start_time = time.time()
            self._status_label.config(text=f"Web server running on port {self._web_port}", fg=ACCENT)
            self._enable_btn(self._btn_web, self._open_browser, "Open Web UI", BTN_BLUE)
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
    # CasparCG process
    # -----------------------------------------------------------------------

    def _refresh_exe_display(self):
        cfg = load_config()
        self._path_var.set(cfg.get("caspar_exe_path", "casparcg.exe"))

    def _check_updates(self):
        self._disable_btn(self._btn_update, "Checking...")
        def run():
            try:
                import urllib.request, json as _json
                url = "https://api.github.com/repos/BlueElliott/Elliotts-Casper-Controller/releases/latest"
                req = urllib.request.Request(url, headers={"User-Agent": "ElliotsCasperController"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = _json.loads(r.read())
                latest = data.get("tag_name", "").lstrip("v")
                current = __version__
                if latest and latest != current:
                    self.root.after(0, lambda: self._update_available(latest, data.get("html_url", "")))
                else:
                    self.root.after(0, self._up_to_date)
            except Exception as e:
                self.root.after(0, lambda: self._update_error(str(e)))
        threading.Thread(target=run, daemon=True).start()

    def _update_available(self, latest: str, url: str):
        self._redraw_btn(self._btn_update, f"v{latest} Available!", BTN_ORNG, tk.NORMAL)
        self._enable_btn(self._btn_update, lambda: webbrowser.open(url),
                         f"v{latest} Available!", BTN_ORNG)
        self._status_label.config(text=f"Update available: v{latest}", fg=WARNING)

    def _up_to_date(self):
        self._redraw_btn(self._btn_update, "Up to Date ✓", SUCCESS, tk.NORMAL)
        self.root.after(3000, lambda: self._enable_btn(
            self._btn_update, self._check_updates, "Check for Updates", ACCENT))

    def _update_error(self, err: str):
        self._redraw_btn(self._btn_update, "Check Failed", BTN_GRAY, tk.NORMAL)
        self.root.after(3000, lambda: self._enable_btn(
            self._btn_update, self._check_updates, "Check for Updates", ACCENT))

    def _start_caspar(self):
        exe = load_config().get("caspar_exe_path", "").strip()
        if not os.path.isfile(exe):
            messagebox.showerror(
                "CasparCG Not Found",
                f"Cannot find:\n{exe or '(no path set)'}\n\n"
                "Go to Web UI → Settings to set the CasparCG executable path.",
                parent=self.root,
            )
            return
        self._disable_btn(self._btn_start, "Starting...")
        self._status_label.config(text="Starting CasparCG...", fg=MUTED)

        def run():
            try:
                cfg = load_config()
                self._manager = CasparProcessManager(
                    exe_path=exe,
                    amcp_port=cfg["amcp_port"],
                    startup_delay=cfg["startup_delay"],
                    window_title="PCR3 CasparCG — NDI Server",
                )
                ok = self._manager.start(config=cfg)  # writes casparcg.config to exe dir first
                if ok:
                    client = AMCPClient(port=cfg["amcp_port"])
                    for ch in cfg["channels"]:
                        res = self._send_channel_load(ch, client)
                        self._log_to_console(f"CH{ch['number']} ({ch['name']}) -> {res[:60]}")
                    self.root.after(0, self._on_caspar_started)
                else:
                    self._manager = None
                    self.root.after(0, lambda: self._on_caspar_failed(
                        "CasparCG started but AMCP did not respond.\nCheck that the config is correct and NDI is installed."
                    ))
            except Exception as exc:
                self._manager = None
                self.root.after(0, lambda: self._on_caspar_failed(str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def _on_caspar_started(self):
        self._caspar_running = True
        self._status_label.config(text="CasparCG running — all channels loaded", fg=SUCCESS)
        self._enable_btn(self._btn_start, self._start_caspar, "Start CasparCG", BTN_GREEN)
        self._enable_btn(self._btn_stop, self._stop_caspar,  "Stop CasparCG",  BTN_RED)
        self._log_to_console("CasparCG started and all channels loaded.")

    def _on_caspar_failed(self, reason: str):
        self._status_label.config(text="CasparCG failed to start", fg=ERROR)
        self._enable_btn(self._btn_start, self._start_caspar, "Start CasparCG", BTN_GREEN)
        messagebox.showerror("CasparCG Failed", f"Could not start CasparCG:\n\n{reason}", parent=self.root)
        self._log_to_console(f"ERROR starting CasparCG: {reason}")

    def _stop_caspar(self):
        def run():
            if self._manager:
                # Stop only our specific process — does not affect other CasparCG instances
                self._manager.stop()
                self._manager = None
            else:
                # Fallback: send BYE via AMCP only (no process kill)
                cfg = load_config()
                AMCPClient(port=cfg["amcp_port"]).send("BYE")
            self.root.after(0, self._on_caspar_stopped)

        self._disable_btn(self._btn_stop, "Stopping...")
        threading.Thread(target=run, daemon=True).start()

    def _on_caspar_stopped(self):
        self._caspar_running = False
        self._status_label.config(text="CasparCG stopped", fg=MUTED)
        self._enable_btn(self._btn_stop, self._stop_caspar, "Stop CasparCG", BTN_RED)
        self._log_to_console("CasparCG stopped.")

    def _poll_caspar_status(self):
        def check():
            try:
                cfg = load_config()
                client = AMCPClient(port=cfg["amcp_port"])
                running = client.ping()
                if running != self._caspar_running:
                    self._caspar_running = running
                    if running:
                        self.root.after(0, lambda: self._status_label.config(
                            text="CasparCG running", fg=SUCCESS))
                    else:
                        self.root.after(0, lambda: self._status_label.config(
                            text="CasparCG stopped", fg=MUTED))
            except Exception:
                pass
            self.root.after(4000, self._poll_caspar_status)

        threading.Thread(target=check, daemon=True).start()

    # -----------------------------------------------------------------------
    # Channel restart
    # -----------------------------------------------------------------------

    @staticmethod
    def _send_channel_load(ch: dict, client: AMCPClient) -> str:
        n = ch["number"]
        if ch.get("type", "html") == "html":
            return client.play_html(n, ch.get("url", ""))
        cmd = ch.get("startup_command", "").strip()
        return client.send(cmd) if cmd else client.send(f"CLEAR {n}")

    def _restart_ch(self, number: int, name: str):
        def run():
            cfg = load_config()
            channels = {ch["number"]: ch for ch in cfg["channels"]}
            ch = channels.get(number)
            if not ch:
                return
            client = AMCPClient(port=cfg["amcp_port"])
            client.stop_channel(number)
            time.sleep(0.5)
            res = self._send_channel_load(ch, client)
            self._log_to_console(f"CH{number} ({name}) restarted -> {res[:60]}")

        threading.Thread(target=run, daemon=True).start()

    def _restart_all(self):
        def run():
            cfg = load_config()
            client = AMCPClient(port=cfg["amcp_port"])
            for ch in cfg["channels"]:
                client.stop_channel(ch["number"])
                time.sleep(0.3)
                res = self._send_channel_load(ch, client)
                self._log_to_console(f"CH{ch['number']} restarted -> {res[:60]}")

        threading.Thread(target=run, daemon=True).start()

    # -----------------------------------------------------------------------
    # Console window
    # -----------------------------------------------------------------------

    def _log_to_console(self, msg: str):
        if self._console_text:
            try:
                ts = time.strftime("%H:%M:%S")
                self._console_text.insert(tk.END, f"[{ts}] {msg}\n")
                self._console_text.see(tk.END)
            except Exception:
                pass

    def _toggle_console(self):
        try:
            alive = self._console_window and self._console_window.winfo_exists()
        except Exception:
            alive = False

        if not alive:
            self._console_window = tk.Toplevel(self.root)
            self._console_window.title("Console — Elliott's Casper Controller")
            self._console_window.geometry("800x400")
            self._console_window.configure(bg=BG_DARK)
            self._console_window.protocol("WM_DELETE_WINDOW", self._close_console)

            self._console_text = scrolledtext.ScrolledText(
                self._console_window, bg="#1e1e1e", fg="#d4d4d4",
                font=("Consolas", 9), relief=tk.FLAT, wrap=tk.WORD,
            )
            self._console_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            self._console_text.insert(tk.END, f"Elliott's Casper Controller v{__version__}\n")
            self._console_text.insert(tk.END, "=" * 60 + "\n")
            self._console_text.insert(tk.END,
                f"Web UI: http://127.0.0.1:{self._web_port}/\n"
                f"CasparCG: {'Running' if self._caspar_running else 'Stopped'}\n"
            )
            self._console_text.insert(tk.END, "=" * 60 + "\n\n")

            sys.stdout = _ConsoleRedirector(self._console_text)
            sys.stderr = _ConsoleRedirector(self._console_text)

            self._log_handler = _TkLogHandler(self._console_text)
            self._log_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S"
            ))
            logging.getLogger().addHandler(self._log_handler)
            logging.getLogger().setLevel(logging.INFO)

            self._redraw_btn(self._btn_console, "Close Console", BTN_BLUE)
            self._btn_console.bind("<Button-1>", lambda e: self._toggle_console())
        else:
            self._close_console()

    def _close_console(self):
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None
        if self._console_window:
            try:
                self._console_window.destroy()
            except Exception:
                pass
        self._console_window = None
        self._console_text = None
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        self._redraw_btn(self._btn_console, "Open Console", BTN_GRAY)
        self._btn_console.bind("<Button-1>", lambda e: self._toggle_console())

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
                pystray.MenuItem("Show Window",        lambda: self._show_from_tray()),
                pystray.MenuItem("Open Web UI",        lambda: self._open_browser()),
                pystray.MenuItem("Restart All Channels", lambda: self._restart_all()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit",               lambda: self._quit()),
            )
            self._tray_icon = pystray.Icon(
                "ElliotsCasperController",
                self._make_tray_image(),
                "Elliott's Casper Controller",
                menu,
            )
            threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_from_tray(self):
        self.root.deiconify()
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None

    def _on_close(self):
        if messagebox.askokcancel("Quit", "Quit Elliott's Casper Controller?\n\nThe web server will stop.",
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
    app = CasperControllerGUI()
    app.run()


def main():
    launch()


if __name__ == "__main__":
    main()
