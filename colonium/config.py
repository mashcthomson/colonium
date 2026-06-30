from __future__ import annotations

import json
from pathlib import Path

from colonium.models import BrowserInstance, ColoniumConfig

ACTIVE_BROWSER_NAMES = ["alpha", "beta", "gamma", "delta", "epsilon"]
RESERVE_BROWSER_NAMES = ["zeta", "eta", "theta"]

DEFAULT_BROWSER_NAMES = ACTIVE_BROWSER_NAMES + RESERVE_BROWSER_NAMES

BASE_CDP_PORT = 9222


def default_browsers() -> list[BrowserInstance]:
    browsers: list[BrowserInstance] = []
    for i, name in enumerate(DEFAULT_BROWSER_NAMES):
        pool = "reserve" if name in RESERVE_BROWSER_NAMES else "active"
        browsers.append(
            BrowserInstance(
                name=name,
                cdp_port=BASE_CDP_PORT + i,
                profile_dir=f"profiles/{name}",
                enabled=True,
                pool=pool,
            )
        )
    return browsers


def default_config() -> ColoniumConfig:
    cfg = ColoniumConfig(browsers=default_browsers())
    return cfg


def config_path(data_dir: Path | None = None) -> Path:
    root = data_dir or Path.home() / ".colonium"
    return root / "config.json"


def load_config(path: Path | None = None) -> ColoniumConfig:
    p = path or config_path()
    if not p.exists():
        cfg = default_config()
        save_config(cfg, p)
        return cfg
    raw = json.loads(p.read_text(encoding="utf-8"))
    for browser in raw.get("browsers", []):
        if "pool" not in browser and browser.get("name") in RESERVE_BROWSER_NAMES:
            browser["pool"] = "reserve"
    return ColoniumConfig.model_validate(raw)


def save_config(cfg: ColoniumConfig, path: Path | None = None) -> Path:
    p = path or config_path(cfg.data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = cfg.model_dump(mode="json")
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def resolve_profile_dir(cfg: ColoniumConfig, browser: BrowserInstance) -> Path:
    profile = Path(browser.profile_dir)
    if profile.is_absolute():
        return profile
    return cfg.data_dir / profile
