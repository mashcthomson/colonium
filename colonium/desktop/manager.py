from __future__ import annotations

import json
import os
import sys
import time
from typing import Protocol

from colonium.config import load_config
from colonium.desktop.linux import DesktopState, LinuxDesktopManager
from colonium.models import ColoniumConfig, DesktopMode


class DesktopManager(Protocol):
    def load_state(self) -> DesktopState | None: ...

    def start(self, force: bool = False) -> DesktopState: ...

    def stop(self) -> bool: ...

    def status(self) -> dict: ...

    def browser_env(self) -> dict[str, str]: ...


class CurrentDesktopManager:
    """Use the host OS desktop without Linux-specific isolation helpers."""

    STATE_FILE = "desktop.json"

    def __init__(self, cfg: ColoniumConfig | None = None):
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
            display=raw.get("display", ""),
            pid=raw.get("pid"),
            workspace_index=raw.get("workspace_index"),
            started_at=raw.get("started_at", 0),
            wm_pid=raw.get("wm_pid"),
        )

    def start(self, force: bool = False) -> DesktopState:
        _ = force
        if self.cfg.desktop.mode != DesktopMode.CURRENT:
            raise RuntimeError(
                f"{self.cfg.desktop.mode.value} desktop mode is only supported on Linux. "
                "Use --mode current or set desktop.mode to current in ~/.colonium/config.json."
            )
        state = DesktopState(
            mode=DesktopMode.CURRENT,
            display=os.environ.get("DISPLAY", ""),
            pid=None,
            workspace_index=None,
            started_at=time.time(),
            wm_pid=None,
        )
        self._save_state(state)
        return state

    def stop(self) -> bool:
        if not self.state_path.exists():
            return False
        self.state_path.unlink()
        return True

    def status(self) -> dict:
        state = self.load_state()
        if state is None:
            return {
                "configured_mode": self.cfg.desktop.mode.value,
                "running": False,
                "display": None,
                "hint": "Run: colonium desktop start --mode current",
            }
        return {
            "configured_mode": self.cfg.desktop.mode.value,
            "running": state.mode == DesktopMode.CURRENT,
            "active_mode": state.mode.value,
            "display": state.display or None,
            "pid": None,
            "wm_pid": None,
            "workspace_index": None,
            "resolution": f"{self.cfg.desktop.width}x{self.cfg.desktop.height}",
            "view_hint": "Colonium browsers will open on the current desktop.",
        }

    def browser_env(self) -> dict[str, str]:
        return os.environ.copy()


def create_desktop_manager(cfg: ColoniumConfig | None = None) -> DesktopManager:
    resolved = cfg or load_config()
    if sys.platform.startswith("linux"):
        return LinuxDesktopManager(resolved)
    return CurrentDesktopManager(resolved)
