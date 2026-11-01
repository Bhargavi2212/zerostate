"""Append-only, hash-chained audit log (SQLite). One global chain: each row stores the hash of the
row before it, so editing or removing any row breaks every hash after it."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

GENESIS = "0" * 64
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL,
    payload_json TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def row_hash(ts: str, session: str, kind: str, payload_json: str, prev_hash: str) -> str:
    body = canonical({"ts": ts, "session": session, "kind": kind, "payload": payload_json, "prev_hash": prev_hash})
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        self.db.executescript(SCHEMA)

    def append(self, session: str, kind: str, payload: dict, ts: str | None = None) -> dict:
        ts = ts or datetime.now(UTC).isoformat()
        payload_json = canonical(payload)
        self.db.execute("BEGIN IMMEDIATE")  # read the chain head and insert atomically
        try:
            last = self.db.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev = last[0] if last else GENESIS
            h = row_hash(ts, session, kind, payload_json, prev)
            self.db.execute("INSERT INTO events (ts, session, kind, payload_json, prev_hash, hash) VALUES (?,?,?,?,?,?)",
                            (ts, session, kind, payload_json, prev, h))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"ts": ts, "session": session, "kind": kind, "payload": payload, "hash": h}

    def events(self, session: str | None = None) -> list[dict]:
        q = "SELECT id, ts, session, kind, payload_json, prev_hash, hash FROM events"
        rows = self.db.execute(q + (" WHERE session = ? ORDER BY id" if session else " ORDER BY id"),
                               (session,) if session else ()).fetchall()
        return [{"id": r[0], "ts": r[1], "session": r[2], "kind": r[3], "payload": json.loads(r[4]),
                 "prev_hash": r[5], "hash": r[6]} for r in rows]

    def verify(self) -> tuple[bool, int | None]:
        """Recompute the whole chain. Returns (ok, id of the first bad row)."""
        prev = GENESIS
        for rid, ts, session, kind, payload_json, prev_hash, h in self.db.execute(
                "SELECT id, ts, session, kind, payload_json, prev_hash, hash FROM events ORDER BY id"):
            if prev_hash != prev or row_hash(ts, session, kind, payload_json, prev_hash) != h:
                return False, rid
            prev = h
        return True, None

    def close(self) -> None:
        self.db.close()
