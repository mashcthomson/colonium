#!/usr/bin/env python3
"""Replicate run_single_task path for Gemini."""

from __future__ import annotations

import time

from colonium.config import load_config
from colonium.models import ServiceName
from colonium.runner import run_single_task


def main():
    cfg = load_config()
    alpha = next(b for b in cfg.browsers if b.name == "alpha")
    t0 = time.time()
    resp = run_single_task(
        browser=alpha,
        service=ServiceName.GEMINI,
        prompt="Reply with exactly one word: COLONIUM_OK",
        files=[],
        fresh_chat=False,
        session_id=None,
        timeout_ms=120_000,
    )
    print("status:", resp.status, "ms:", int((time.time() - t0) * 1000))
    print("url:", resp.url)
    print("error:", resp.error)
    print("text:", repr(resp.text[:200] if resp.text else ""))


if __name__ == "__main__":
    main()
