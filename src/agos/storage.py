from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Protocol
from .schema import Json

class StateStore(Protocol):
    """Persistence contract used by the local runtime.

    Implementations must provide durable JSON checkpoints, ordered events, and
    successful idempotency results. Distributed consistency is not implied.
    """
    def checkpoint(self, run_id: str, state: dict[str, Json]) -> None: ...
    def load(self, run_id: str) -> dict[str, Json] | None: ...
    def event(self, run_id: str, event: dict[str, Json]) -> None: ...
    def events(self, run_id: str) -> list[dict[str, Json]]: ...
    def idempotent(self, key: str) -> Json | None: ...
    def remember_idempotent(self, key: str, value: Json) -> None: ...


class SQLiteStateStore:
    """Local durable state. JSON serialization rejects non-serializable outputs."""
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, event TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    def close(self) -> None: self.db.close()
    def __del__(self):
        try: self.db.close()
        except Exception: pass
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def checkpoint(self, run_id: str, state: dict[str, Json]) -> None:
        encoded=json.dumps(state, sort_keys=True); self.db.execute("INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state", (run_id,encoded)); self.db.commit()
    def load(self, run_id: str) -> dict[str, Json] | None:
        row=self.db.execute("SELECT state FROM runs WHERE id=?",(run_id,)).fetchone(); return json.loads(row[0]) if row else None
    def event(self, run_id: str, event: dict[str, Json]) -> None:
        self.db.execute("INSERT INTO events(run_id,event) VALUES (?,?)",(run_id,json.dumps(event,sort_keys=True))); self.db.commit()
    def events(self, run_id: str) -> list[dict[str, Json]]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT event FROM events WHERE run_id=? ORDER BY seq",(run_id,))]
    def idempotent(self, key: str) -> Json | None:
        row=self.db.execute("SELECT value FROM idempotency WHERE key=?",(key,)).fetchone(); return json.loads(row[0]) if row else None
    def remember_idempotent(self, key: str, value: Json) -> None:
        self.db.execute("INSERT OR IGNORE INTO idempotency VALUES (?,?)",(key,json.dumps(value,sort_keys=True))); self.db.commit()
