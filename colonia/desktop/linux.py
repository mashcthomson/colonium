from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass

from colonia.config import load_config
from colonia.models import ColoniaConfig, DesktopMode


@dataclass
class DesktopState:
    mode: DesktopMode
    display: str
    pid: int | None
    workspace_index: int | None
    started_at: float
    wm_pid: int | None = None


class LinuxDesktopManager:
    """Manage Colonia's isolated 'Desktop 2' on Linux.

    Modes:
    - xephyr: nested X server (recommended) — like a separate Windows virtual desktop
    - workspace: move windows to an existing GNOME/KDE workspace via wmctrl
    - current: use the active display with no isolation
    """

    STATE_FILE = "desktop.json"

    def __init__(self, cfg: ColoniaConfig | None = None):
        self.cfg = cfg or load_config()
        self.state_path = self.cfg.state_dir / self.STATE_FILE

    def _save_state(self, state: DesktopState) -> None:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "mode": state.mode.value,
                    "display": state.display,
                    "pid": state.pid,
                    "workspace_index": state.workspace_index,
                    "started_at": state.started_at,
                    "wm_pid": state.wm_pid,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def load_state(self) -> DesktopState | None:
        if not self.state_path.exists():
            return None
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        return DesktopState(
            mode=DesktopMode(raw["mode"]),
            display=raw["display"],
            pid=raw.get("pid"),
            workspace_index=raw.get("workspace_index"),
            started_at=raw.get("started_at", 0),
            wm_pid=raw.get("wm_pid"),
        )

    def is_display_alive(self, display: str) -> bool:
        env = {**os.environ, "DISPLAY": display}
        try:
            subprocess.run(
                ["xdpyinfo"],
                env=env,
                capture_output=True,
                check=True,
                timeout=5,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _is_pid_alive(self, pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def effective_display(self) -> str:
        state = self.load_state()
        desktop = self.cfg.desktop
        if desktop.mode == DesktopMode.CURRENT:
            return os.environ.get("DISPLAY", ":0")
        if desktop.mode == DesktopMode.WORKSPACE:
            return os.environ.get("DISPLAY", ":0")
        if state and state.display and self.is_display_alive(state.display):
            return state.display
        return desktop.display

    def start(self, force: bool = False) -> DesktopState:
        desktop = self.cfg.desktop
        if desktop.mode == DesktopMode.CURRENT:
            display = os.environ.get("DISPLAY", ":0")
            state = DesktopState(
                mode=DesktopMode.CURRENT,
                display=display,
                pid=None,
                workspace_index=None,
                started_at=time.time(),
                wm_pid=None,
            )
            self._save_state(state)
            return state

        if desktop.mode == DesktopMode.WORKSPACE:
            return self._start_workspace_mode()

        return self._start_xephyr_mode(force=force)

    def _start_workspace_mode(self) -> DesktopState:
        if shutil.which("wmctrl") is None:
            raise RuntimeError(
                "workspace mode requires wmctrl. Install: sudo apt install wmctrl\n"
                "Or use: colonia desktop start --mode xephyr"
            )
        display = os.environ.get("DISPLAY", ":0")
        idx = self.cfg.desktop.workspace_index
        subprocess.run(
            ["wmctrl", "-s", str(idx)],
            check=False,
            capture_output=True,
        )
        state = DesktopState(
            mode=DesktopMode.WORKSPACE,
            display=display,
            pid=None,
            workspace_index=idx,
            started_at=time.time(),
            wm_pid=None,
        )
        self._save_state(state)
        return state

    def _window_manager_command(self) -> list[str] | None:
        configured = self.cfg.desktop.window_manager
        candidates = (
            [configured]
            if configured
            else [
                "openbox",
                "fluxbox",
                "metacity",
                "xfwm4",
                "matchbox-window-manager",
                "twm",
            ]
        )
        for candidate in candidates:
            if candidate and shutil.which(candidate):
                return [candidate]
        return None

    def _start_window_manager(self, display: str) -> int | None:
        cmd = self._window_manager_command()
        if cmd is None:
            return None
        env = {**os.environ, "DISPLAY": display}
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(0.3)
        return None if proc.poll() is not None else proc.pid

    def _start_xephyr_mode(self, force: bool = False) -> DesktopState:
        existing = self.load_state()
        display = self.cfg.desktop.display
        if (
            not force
            and existing
            and existing.mode == DesktopMode.XEPHYR
            and self.is_display_alive(existing.display)
            and self._is_pid_alive(existing.pid)
        ):
            return existing

        if existing and existing.pid and self._is_pid_alive(existing.pid):
            self.stop()

        xephyr = self.cfg.desktop.xephyr_binary
        if shutil.which(xephyr) is None:
            raise RuntimeError(f"{xephyr} not found. Install: sudo apt install xserver-xephyr")

        w, h = self.cfg.desktop.width, self.cfg.desktop.height
        cmd = [
            xephyr,
            display,
            "-screen",
            f"{w}x{h}",
            "-resizeable",
            "-title",
            "Colonia Desktop 2",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            if self.is_display_alive(display):
                break
            if proc.poll() is not None:
                raise RuntimeError(f"Xephyr exited immediately (code {proc.returncode})")
            time.sleep(0.1)
        else:
            proc.terminate()
            raise RuntimeError(f"Xephyr display {display} did not become ready in time")

        wm_pid = self._start_window_manager(display)

        state = DesktopState(
            mode=DesktopMode.XEPHYR,
            display=display,
            pid=proc.pid,
            workspace_index=None,
            started_at=time.time(),
            wm_pid=wm_pid,
        )
        self._save_state(state)
        return state

    def stop(self) -> bool:
        state = self.load_state()
        if state is None:
            return False
        if state.mode == DesktopMode.XEPHYR and state.pid:
            if state.wm_pid:
                try:
                    os.killpg(os.getpgid(state.wm_pid), signal.SIGTERM)
                except OSError:
                    try:
                        os.kill(state.wm_pid, signal.SIGTERM)
                    except OSError:
                        pass
            try:
                os.killpg(os.getpgid(state.pid), signal.SIGTERM)
            except OSError:
                try:
                    os.kill(state.pid, signal.SIGTERM)
                except OSError:
                    pass
            time.sleep(0.3)
        if self.state_path.exists():
            self.state_path.unlink()
        return True

    def status(self) -> dict:
        state = self.load_state()
        desktop = self.cfg.desktop
        if state is None:
            return {
                "configured_mode": desktop.mode.value,
                "running": False,
                "display": None,
                "hint": "Run: colonia desktop start",
            }
        alive = (
            state.mode != DesktopMode.XEPHYR
            or (state.pid is not None and self._is_pid_alive(state.pid))
        ) and self.is_display_alive(state.display)
        return {
            "configured_mode": desktop.mode.value,
            "running": alive,
            "active_mode": state.mode.value,
            "display": state.display,
            "pid": state.pid,
            "wm_pid": state.wm_pid,
            "workspace_index": state.workspace_index,
            "resolution": f"{desktop.width}x{desktop.height}",
            "view_hint": (
                f"Colonia Desktop 2 is on DISPLAY={state.display} "
                f"(window title: 'Colonia Desktop 2')"
                if state.mode == DesktopMode.XEPHYR
                else f"Browsers target workspace {state.workspace_index} on {state.display}"
            ),
        }

    def browser_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DISPLAY"] = self.effective_display()
        return env
