"""Launch, monitor, and stop the CasparCG server process."""
import os
import subprocess
import threading
import time
from typing import Optional

import psutil

from elliotts_casper_controller.amcp_client import AMCPClient

# Console colour: black bg (0), cyan text (B)
_CONSOLE_COLOR = "0B"


class _AdoptedProcess:
    """Minimal Popen-compatible wrapper around an existing process found via psutil."""
    def __init__(self, pid: int):
        self._pid = pid
        try:
            self._psutil = psutil.Process(pid)
        except psutil.NoSuchProcess:
            self._psutil = None

    def poll(self):
        if self._psutil is None:
            return 0
        try:
            return None if self._psutil.is_running() else 0
        except psutil.NoSuchProcess:
            return 0

    @property
    def pid(self) -> int:
        return self._pid


class CasparProcessManager:
    def __init__(self, exe_path: str, amcp_port: int = 5250, startup_delay: int = 8,
                 window_title: str = "PCR3 CasparCG - NDI Server",
                 config_filename: str = "casparcg.config"):
        self.exe_path = exe_path
        self.amcp_port = amcp_port
        self.startup_delay = startup_delay
        self.window_title = window_title
        self.config_filename = config_filename
        self._process: Optional[subprocess.Popen] = None
        self._client = AMCPClient(port=amcp_port)
        self._console_hwnd = None  # conhost HWND, found after startup

    def start(self) -> bool:
        """Launch CasparCG using self.config_filename. Caller must pre-write the config."""
        if self.is_running():
            return True
        try:
            exe_name = os.path.basename(self.exe_path)
            safe_title = self.window_title.replace('"', "'").replace('&', 'and')
            cmd = f'cmd /k "color {_CONSOLE_COLOR} && title {safe_title} && {exe_name} {self.config_filename}"'

            # Launch hidden — the console window is shown only on demand via show_console().
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

            self._console_hwnd = None
            self._process = subprocess.Popen(
                cmd,
                cwd=self._exe_dir(),
                startupinfo=si,
                # Each instance must get its own fresh console, independent of
                # our Python process's current console attachment (AttachConsole
                # from a previous instance's thread would otherwise be inherited).
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            # Poll AMCP every second — move on as soon as it responds.
            # 90s hard timeout handles slow cold starts without hanging forever.
            deadline = time.time() + 90
            while time.time() < deadline:
                time.sleep(1)
                if self._client.ping():
                    threading.Thread(
                        target=self._rename_console_after_delay,
                        daemon=True,
                    ).start()
                    return True
            return False
        except Exception:
            return False

    def show_console(self) -> bool:
        """Make the CasparCG console window visible. Returns True if the HWND was found."""
        import ctypes
        # Primary: find by window title — most reliable since we set it via SetConsoleTitleW
        if not self._console_hwnd:
            hwnd = ctypes.windll.user32.FindWindowW(None, self.window_title)
            if hwnd:
                self._console_hwnd = hwnd
        # Fallback: walk process tree to find conhost HWND
        if not self._console_hwnd and self._process:
            self._console_hwnd = self._find_conhost_hwnd(self._process.pid)
        if self._console_hwnd:
            ctypes.windll.user32.ShowWindow(self._console_hwnd, 5)   # SW_SHOW
            ctypes.windll.user32.SetForegroundWindow(self._console_hwnd)
            return True
        return False

    def hide_console(self) -> bool:
        """Hide the CasparCG console window. Returns True if the HWND was found."""
        if self._console_hwnd:
            import ctypes
            ctypes.windll.user32.ShowWindow(self._console_hwnd, 0)   # SW_HIDE
            return True
        return False

    def adopt_existing(self) -> bool:
        """Find a running CasparCG process and adopt it so we can control it.

        Searches for casparcg.exe, uses its parent cmd.exe as the root process
        (matching how we launch it). Returns True if adopted.
        """
        if not self._client.ping():
            return False
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if "casparcg" not in proc.name().lower():
                    continue
                # Prefer the parent cmd.exe so kill_tree works the same way
                try:
                    parent = proc.parent()
                    root = parent if parent and "cmd" in parent.name().lower() else proc
                except Exception:
                    root = proc
                self._process = _AdoptedProcess(root.pid)
                self._console_hwnd = None
                threading.Thread(
                    target=self._rename_console_after_delay, daemon=True
                ).start()
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False

    @staticmethod
    def _kill_caspar_on_port(port: int) -> None:
        """Kill the CasparCG process (and its cmd parent) listening on a specific AMCP port."""
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                for conn in proc.connections(kind="inet"):
                    if conn.laddr.port == port and conn.status == "LISTEN":
                        try:
                            parent = proc.parent()
                            if parent and "cmd" in parent.name().lower():
                                CasparProcessManager._kill_tree(parent.pid)
                            else:
                                CasparProcessManager._kill_tree(proc.pid)
                        except Exception:
                            CasparProcessManager._kill_tree(proc.pid)
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(0.3)

    @staticmethod
    def _kill_all_caspar_instances() -> None:
        """Kill every casparcg.exe (and its cmd.exe parent) found on this machine."""
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if "casparcg" in proc.name().lower():
                    try:
                        parent = proc.parent()
                        if parent and "cmd" in parent.name().lower():
                            CasparProcessManager._kill_tree(parent.pid)
                        else:
                            CasparProcessManager._kill_tree(proc.pid)
                    except Exception:
                        CasparProcessManager._kill_tree(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(1.5)

    def stop(self) -> None:
        """Stop CasparCG: send BYE then immediately kill the process tree."""
        self._client.send("BYE")
        time.sleep(0.2)  # brief grace period for graceful shutdown
        if self._process and self._process.poll() is None:
            self._kill_tree(self._process.pid)
        self._process = None

    def is_running(self) -> bool:
        """Check if OUR process is still alive and AMCP responds."""
        if self._process and self._process.poll() is None:
            return self._client.ping()
        # Don't fall back to scanning all processes — that would detect
        # other CasparCG instances that we don't own.
        return False

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    def _rename_console_after_delay(self, delay: float = 2.0) -> None:
        """Set console appearance after CasparCG finishes its own startup.

        Two independent mechanisms:
        1. Custom icon via WM_SETICON — CasparCG never changes the icon,
           so it persists permanently in the taskbar and Alt-Tab view.
        2. AttachConsole + SetConsoleTitleW — the same kernel32 path that
           CasparCG uses, so we compete on equal footing. Called every 1 s.

        Note: SetWindowTextW silently fails on console windows from another
        process (conhost owns the window, not the client). Only AttachConsole
        + SetConsoleTitleW is authoritative for the title.
        """
        time.sleep(delay)
        if not self._process:
            return
        try:
            self._run_console_appearance(self._process.pid, self.window_title)
        except Exception:
            pass

    def _run_console_appearance(self, root_pid: int, title: str) -> None:
        import ctypes
        import ctypes.wintypes

        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # --- Find child PIDs (conhost + casparcg) ---
        conhost_pid  = None
        caspar_pid   = root_pid
        for _ in range(10):
            try:
                for child in psutil.Process(root_pid).children(recursive=True):
                    name = child.name().lower()
                    if 'conhost' in name:
                        conhost_pid = child.pid
                    if 'caspar' in name:
                        caspar_pid  = child.pid
                if conhost_pid and caspar_pid != root_pid:
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.5)

        # --- Set custom icon on console window via conhost HWND ---
        # WM_SETICON is permanent — CasparCG never overrides the window icon.
        if conhost_pid:
            # Find the HWND even though the window is hidden (visible_only=False).
            hwnd = self._find_hwnd_for_pid(conhost_pid, visible_only=False)
            self._console_hwnd = hwnd  # store so show_console/hide_console can use it

            icon_path = self._find_icon()
            if icon_path:
                try:
                    LR_LOADFROMFILE = 0x10
                    IMAGE_ICON      = 1
                    WM_SETICON      = 0x0080
                    ICON_SMALL, ICON_BIG = 0, 1

                    if hwnd:
                        for icon_size, icon_type in [(16, ICON_SMALL), (32, ICON_BIG)]:
                            hIcon = user32.LoadImageW(
                                None, icon_path, IMAGE_ICON,
                                icon_size, icon_size, LR_LOADFROMFILE,
                            )
                            if hIcon:
                                user32.SendMessageW(hwnd, WM_SETICON, icon_type, hIcon)
                except Exception:
                    pass

        # AttachConsole/SetConsoleTitleW removed: it modifies the Python process's
        # console attachment globally, causing later Popen calls to inherit the wrong
        # console and silently fail to start. The cmd /k title command in the launch
        # string already sets the window title; show_console() falls back to
        # _find_conhost_hwnd() if FindWindowW by title doesn't match.

    @staticmethod
    def _find_hwnd_for_pid(pid: int, visible_only: bool = True):
        """Return the first HWND whose owning process is `pid`."""
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _cb(hwnd, _):
            wpid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid and (not visible_only or user32.IsWindowVisible(hwnd)):
                found.append(hwnd)
            return True

        user32.EnumWindows(_cb, 0)
        return found[0] if found else None

    def _find_conhost_hwnd(self, root_pid: int):
        """Walk the process tree to find conhost's HWND (visible or hidden)."""
        try:
            for child in psutil.Process(root_pid).children(recursive=True):
                if 'conhost' in child.name().lower():
                    hwnd = self._find_hwnd_for_pid(child.pid, visible_only=False)
                    if hwnd:
                        return hwnd
        except psutil.NoSuchProcess:
            pass
        return None

    @staticmethod
    def _find_icon() -> str | None:
        """Locate esc_icon.ico bundled with the app."""
        import sys
        candidates = []
        if getattr(sys, 'frozen', False):
            candidates.append(os.path.join(sys._MEIPASS, 'static', 'esc_icon.ico'))
        candidates.append(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'static', 'esc_icon.ico')
        )
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def _kill_tree(pid: int) -> None:
        """Kill a process and all its children (cmd.exe + casparcg.exe)."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            parent.terminate()
            psutil.wait_procs([parent] + children, timeout=5)
            # Force-kill anything still alive
            for proc in [parent] + children:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except psutil.NoSuchProcess:
            pass

    def _exe_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.exe_path))
