from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from colonia.config import load_config
from colonia.models import ServiceName

SESSION_IDLE_TTL = timedelta(days=7)


@dataclass
class ThreadBinding:
    session_id: str
    browser: str
    service: str
    thread_url: str
    response_count: int
    last_used_at: datetime

    @property
    def key(self) -> str:
        return f"{self.browser}:{self.service}"


class SessionStore:
    def __init__(self, db_path: Path | None = None):
        cfg = load_config()
        self.db_path = db_path or (cfg.data_dir / "sessions.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS thread_bindings (
                    session_id TEXT NOT NULL,
                    browser TEXT NOT NULL,
                    service TEXT NOT NULL,
                    thread_url TEXT NOT NULL,
                    response_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, browser, service)
                );
                CREATE TABLE IF NOT EXISTS session_meta (
                    session_id TEXT PRIMARY KEY,
                    turn_index INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_failover (
                    session_id TEXT NOT NULL,
                    failed_browser TEXT NOT NULL,
                    reserve_browser TEXT NOT NULL,
                    PRIMARY KEY (session_id, failed_browser)
                );
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def is_expired(self, binding: ThreadBinding) -> bool:
        return self._now() - binding.last_used_at > SESSION_IDLE_TTL

    def get_binding(
        self, session_id: str, browser: str, service: ServiceName | str
    ) -> ThreadBinding | None:
        svc = service.value if isinstance(service, ServiceName) else service
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, browser, service, thread_url, response_count, last_used_at
                FROM thread_bindings
                WHERE session_id = ? AND browser = ? AND service = ?
                """,
                (session_id, browser, svc),
            ).fetchone()
        if row is None:
            return None
        binding = ThreadBinding(
            session_id=row["session_id"],
            browser=row["browser"],
            service=row["service"],
            thread_url=row["thread_url"],
            response_count=row["response_count"],
            last_used_at=self._parse_dt(row["last_used_at"]),
        )
        if self.is_expired(binding):
            self.delete_binding(session_id, browser, svc)
            return None
        return binding

    def save_binding(
        self,
        session_id: str,
        browser: str,
        service: ServiceName | str,
        thread_url: str,
        response_count: int,
    ) -> ThreadBinding:
        svc = service.value if isinstance(service, ServiceName) else service
        now = self._now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO thread_bindings
                    (session_id, browser, service, thread_url, response_count, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, browser, service) DO UPDATE SET
                    thread_url = excluded.thread_url,
                    response_count = excluded.response_count,
                    last_used_at = excluded.last_used_at
                """,
                (session_id, browser, svc, thread_url, response_count, now),
            )
        return ThreadBinding(
            session_id=session_id,
            browser=browser,
            service=svc,
            thread_url=thread_url,
            response_count=response_count,
            last_used_at=self._parse_dt(now),
        )

    def delete_binding(self, session_id: str, browser: str, service: ServiceName | str) -> None:
        svc = service.value if isinstance(service, ServiceName) else service
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM thread_bindings
                WHERE session_id = ? AND browser = ? AND service = ?
                """,
                (session_id, browser, svc),
            )

    def clear_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM thread_bindings WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_meta WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM browser_failover WHERE session_id = ?", (session_id,))

    def bump_turn(self, session_id: str) -> int:
        now = self._now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT turn_index FROM session_meta WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO session_meta (session_id, turn_index, created_at) VALUES (?, 1, ?)",
                    (session_id, now),
                )
                return 1
            turn = int(row["turn_index"]) + 1
            conn.execute(
                "UPDATE session_meta SET turn_index = ? WHERE session_id = ?",
                (turn, session_id),
            )
            return turn

    def get_turn(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT turn_index FROM session_meta WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["turn_index"]) if row else 0

    def set_failover(self, session_id: str, failed_browser: str, reserve_browser: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_failover (session_id, failed_browser, reserve_browser)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id, failed_browser) DO UPDATE SET
                    reserve_browser = excluded.reserve_browser
                """,
                (session_id, failed_browser, reserve_browser),
            )

    def reserve_browsers_used(self, session_id: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT reserve_browser FROM browser_failover WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        return {row["reserve_browser"] for row in rows}

    def resolve_browser(self, session_id: str, browser: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT reserve_browser FROM browser_failover
                WHERE session_id = ? AND failed_browser = ?
                """,
                (session_id, browser),
            ).fetchone()
        return row["reserve_browser"] if row else browser

    def purge_expired(self) -> int:
        cutoff = (self._now() - SESSION_IDLE_TTL).isoformat()
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM thread_bindings WHERE last_used_at < ?", (cutoff,))
            return cur.rowcount
