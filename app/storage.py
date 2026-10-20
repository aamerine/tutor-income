"""SQLite persistence for the plan.

Each save appends a new version rather than overwriting, so an accidental
edit can be recovered from the database. Only the newest KEEP_VERSIONS are kept.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .schemas import Plan

KEEP_VERSIONS = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saved_at TEXT NOT NULL,
    body TEXT NOT NULL
)
"""


class PlanStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def load(self) -> tuple[Plan, str] | None:
        """The newest saved plan and its save time, or None if nothing is saved."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT body, saved_at FROM plan_versions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return Plan.model_validate_json(row[0]), row[1]

    def save(self, plan: Plan) -> str:
        saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO plan_versions (saved_at, body) VALUES (?, ?)",
                (saved_at, plan.model_dump_json()),
            )
            conn.execute(
                "DELETE FROM plan_versions WHERE id NOT IN "
                "(SELECT id FROM plan_versions ORDER BY id DESC LIMIT ?)",
                (KEEP_VERSIONS,),
            )
        return saved_at

    def version_count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM plan_versions").fetchone()[0]
