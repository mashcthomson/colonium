from __future__ import annotations

from colonia.models import BrowserInstance, ColoniaConfig

ACTIVE_POOL = frozenset({"alpha", "beta", "gamma", "delta", "epsilon"})
RESERVE_POOL = frozenset({"zeta", "eta", "theta"})
SKIP_BY_DEFAULT = frozenset({"alpha"})

RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "usage limit",
    "too many requests",
    "quota",
    "429",
    "capacity",
)


def is_rate_limit_error(message: str | None) -> bool:
    if not message:
        return False
    lower = message.lower()
    return any(m in lower for m in RATE_LIMIT_MARKERS)


class BrowserPoolManager:
    def __init__(self, cfg: ColoniaConfig):
        self.cfg = cfg

    def active_browsers(self) -> list[BrowserInstance]:
        return [
            b
            for b in self.cfg.browsers
            if (
                b.enabled
                and b.name not in SKIP_BY_DEFAULT
                and (b.pool == "active" or b.name in ACTIVE_POOL)
            )
        ]

    def reserve_browsers(self) -> list[BrowserInstance]:
        return [
            b
            for b in self.cfg.browsers
            if b.enabled and (b.pool == "reserve" or b.name in RESERVE_POOL)
        ]

    def select_browsers(
        self, names: list[str], *, include_all_eight: bool = False
    ) -> list[BrowserInstance]:
        enabled = [b for b in self.cfg.browsers if b.enabled]
        if names and names != ["all"]:
            wanted = set(names)
            return [b for b in enabled if b.name in wanted]
        fanout = [b for b in enabled if b.name not in SKIP_BY_DEFAULT]
        if include_all_eight:
            return fanout
        active = self.active_browsers()
        return active if active else fanout[:5]

    def pick_reserve(self, session_id: str, failed_browser: str, store) -> BrowserInstance | None:
        used = {failed_browser} | store.reserve_browsers_used(session_id)
        for browser in self.reserve_browsers():
            if browser.name not in used:
                return browser
        return None
