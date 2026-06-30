from __future__ import annotations

import math
import http.client
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from colonia.config import load_config, resolve_profile_dir
from colonia.desktop.linux import LinuxDesktopManager
from colonia.models import BrowserInstance, ColoniaConfig


@dataclass
class LaunchedBrowser:
    browser: BrowserInstance
    pid: int
    cdp_url: str


class BrowserLauncher:
    def __init__(self, cfg: ColoniaConfig | None = None):
        self.cfg = cfg or load_config()
        self.desktop = LinuxDesktopManager(self.cfg)

    def _window_geometry(self, browser: BrowserInstance) -> tuple[int, int, int, int]:
        browsers = [b for b in self.cfg.browsers if b.enabled]
        count = max(len(browsers), 1)
        try:
            index = [b.name for b in browsers].index(browser.name)
        except ValueError:
            index = 0
        aspect_ratio = self.cfg.desktop.width / max(self.cfg.desktop.height, 1)
        cols = max(1, math.ceil(math.sqrt(count * aspect_ratio)))
        rows = max(1, math.ceil(count / cols))
        width = max(480, self.cfg.desktop.width // cols)
        height = max(360, self.cfg.desktop.height // rows)
        x = (index % cols) * width
        y = (index // cols) * height
        return width, height, x, y

    def _chrome_cmd(self, browser: BrowserInstance, profile: Path) -> list[str]:
        chrome = self.cfg.desktop.chrome_binary
        width, height, x, y = self._window_geometry(browser)
        return [
            chrome,
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={browser.cdp_port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-features=TranslateUI",
            f"--window-size={width},{height}",
            f"--window-position={x},{y}",
        ]

    def _pid_file(self, browser: BrowserInstance) -> Path:
        return self.cfg.state_dir / f"browser-{browser.name}.pid"

    def _write_pid(self, browser: BrowserInstance, pid: int) -> None:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self._pid_file(browser).write_text(str(pid), encoding="utf-8")

    def _read_pid(self, browser: BrowserInstance) -> int | None:
        p = self._pid_file(browser)
        if not p.exists():
            return None
        try:
            return int(p.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def is_cdp_alive(self, port: int) -> bool:
        if port < 1 or port > 65535:
            return False
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/json/version")
            response = conn.getresponse()
            response.read()
            return response.status == 200
        except Exception:
            return False
        finally:
            conn.close()

    def launch_one(
        self,
        browser: BrowserInstance,
        *,
        open_urls: list[str] | None = None,
        force: bool = False,
    ) -> LaunchedBrowser:
        if not browser.enabled:
            raise ValueError(f"Browser {browser.name} is disabled in config")

        if not force and self.is_cdp_alive(browser.cdp_port):
            pid = self._read_pid(browser) or 0
            return LaunchedBrowser(
                browser=browser,
                pid=pid,
                cdp_url=f"http://127.0.0.1:{browser.cdp_port}",
            )

        profile = resolve_profile_dir(self.cfg, browser)
        profile.mkdir(parents=True, exist_ok=True)

        cmd = self._chrome_cmd(browser, profile)
        if open_urls:
            cmd.extend(open_urls)

        env = self.desktop.browser_env()
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._write_pid(browser, proc.pid)

        for _ in range(60):
            if self.is_cdp_alive(browser.cdp_port):
                break
            if proc.poll() is not None:
                raise RuntimeError(f"Chrome for {browser.name} exited (code {proc.returncode})")
            time.sleep(0.25)
        else:
            raise RuntimeError(
                f"CDP port {browser.cdp_port} for {browser.name} did not open in time"
            )

        if self.cfg.desktop.mode.value == "workspace":
            self._move_to_workspace(proc.pid)

        return LaunchedBrowser(
            browser=browser,
            pid=proc.pid,
            cdp_url=f"http://127.0.0.1:{browser.cdp_port}",
        )

    def _move_to_workspace(self, pid: int) -> None:
        import shutil

        if shutil.which("wmctrl") is None:
            return
        time.sleep(0.5)
        idx = self.cfg.desktop.workspace_index
        subprocess.run(
            ["wmctrl", "-i", "-r", str(pid), "-t", str(idx)],
            capture_output=True,
            check=False,
        )

    def launch_all(
        self,
        *,
        names: list[str] | None = None,
        login_urls: bool = False,
        force: bool = False,
    ) -> list[LaunchedBrowser]:
        from colonia.models import SERVICE_URLS

        targets = [b for b in self.cfg.browsers if b.enabled and (names is None or b.name in names)]
        urls = list(SERVICE_URLS.values()) if login_urls else None
        launched: list[LaunchedBrowser] = []
        for browser in targets:
            launched.append(self.launch_one(browser, open_urls=urls, force=force))
            time.sleep(0.5)
        return launched

    def health(self) -> list[dict]:
        rows = []
        for browser in self.cfg.browsers:
            pid = self._read_pid(browser)
            cdp = self.is_cdp_alive(browser.cdp_port)
            rows.append(
                {
                    "name": browser.name,
                    "enabled": browser.enabled,
                    "cdp_port": browser.cdp_port,
                    "cdp_alive": cdp,
                    "pid": pid,
                    "profile": str(resolve_profile_dir(self.cfg, browser)),
                    "cdp_url": f"http://127.0.0.1:{browser.cdp_port}",
                }
            )
        return rows

    def stop_all(self) -> int:
        stopped = 0
        import os
        import signal

        for browser in self.cfg.browsers:
            pid = self._read_pid(browser)
            if pid:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    stopped += 1
                except OSError:
                    pass
            pf = self._pid_file(browser)
            if pf.exists():
                pf.unlink()
        return stopped
