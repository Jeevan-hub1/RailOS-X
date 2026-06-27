"""
RailOS Edge Node Circular Event Buffer (Task 5.2)
Thread-safe circular buffer backed by SQLite for 24h NVMe persistence.
On full: overwrites oldest entry, logs to overflow_log table.
Satisfies: Req 2 C2, Design §5.2
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

BUFFER_DB_PATH  = os.environ.get("BUFFER_DB_PATH", "/data/buffer/events.db")
MAX_BUFFER_ROWS = int(os.environ.get("MAX_BUFFER_ROWS", str(24 * 3600 * 10)))  # ~10 events/sec × 24h


class CircularBuffer:
    def __init__(self, db_path: str = BUFFER_DB_PATH, max_rows: int = MAX_BUFFER_ROWS) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._max_rows = max_rows
        self._lock     = threading.Lock()
        self._conn     = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id       TEXT    UNIQUE NOT NULL,
                    timestamp_utc  TEXT    NOT NULL,
                    payload        TEXT    NOT NULL,
                    acked          INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp_utc);
                CREATE TABLE IF NOT EXISTS overflow_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    evicted_id  TEXT    NOT NULL,
                    evicted_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                );
            """)
            self._conn.commit()

    def write(self, event: dict[str, Any]) -> None:
        """Write an event to the buffer. Evicts oldest unacked entry if full."""
        event_id    = event.get("eventId", str(time.time_ns()))
        ts_utc      = event.get("timestamp_utc", "")
        payload_str = json.dumps(event)

        with self._lock:
            current = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE acked=0"
            ).fetchone()[0]

            if current >= self._max_rows:
                # Evict oldest unacked entry
                oldest = self._conn.execute(
                    "SELECT event_id FROM events WHERE acked=0 ORDER BY timestamp_utc ASC LIMIT 1"
                ).fetchone()
                if oldest:
                    self._conn.execute(
                        "INSERT INTO overflow_log (evicted_id) VALUES (?)", (oldest[0],)
                    )
                    self._conn.execute(
                        "DELETE FROM events WHERE event_id=?", (oldest[0],)
                    )
                    log.debug("Buffer overflow: evicted event_id=%s", oldest[0])

            self._conn.execute(
                "INSERT OR IGNORE INTO events (event_id, timestamp_utc, payload) VALUES (?,?,?)",
                (event_id, ts_utc, payload_str),
            )
            self._conn.commit()

    def read_oldest(self, n: int = 100) -> list[dict[str, Any]]:
        """Return up to n oldest unacked events ordered by sensor timestamp."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, payload FROM events WHERE acked=0 ORDER BY timestamp_utc ASC LIMIT ?",
                (n,),
            ).fetchall()
        return [{"_buffer_event_id": r[0], **json.loads(r[1])} for r in rows]

    def ack(self, event_id: str) -> None:
        """Mark an event as acknowledged and remove it from the buffer."""
        with self._lock:
            self._conn.execute(
                "UPDATE events SET acked=1 WHERE event_id=?", (event_id,)
            )
            self._conn.execute(
                "DELETE FROM events WHERE event_id=? AND acked=1", (event_id,)
            )
            self._conn.commit()

    def capacity_pct(self) -> float:
        """Return current fill percentage (0.0–100.0)."""
        with self._lock:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE acked=0"
            ).fetchone()[0]
        return min(100.0, (count / self._max_rows) * 100.0)

    def overflow_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM overflow_log").fetchone()[0]
