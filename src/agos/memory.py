from __future__ import annotations
from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from .schema import Json

@dataclass(frozen=True)
class MemoryEntry: namespace: str; key: str; value: Json
class MemoryStore:
    def put(self, actor: str, namespace: str, key: str, value: Json) -> None: raise NotImplementedError
    def get(self, actor: str, namespace: str, key: str) -> Json | None: raise NotImplementedError
class InMemoryMemoryStore(MemoryStore):
    def __init__(self): self._data: dict[tuple[str,str], Json] = {}
    def _permit(self, actor: str, namespace: str) -> None:
        if namespace.startswith("private:") and namespace != f"private:{actor}": raise PermissionError("private memory denied")
        if not (namespace.startswith("private:") or namespace.startswith("shared:")): raise PermissionError("invalid memory namespace")
    def put(self, actor: str, namespace: str, key: str, value: Json) -> None:
        self._permit(actor, namespace); self._data[(namespace, key)] = value
    def get(self, actor: str, namespace: str, key: str) -> Json | None:
        self._permit(actor, namespace); return self._data.get((namespace, key))

class SQLiteMemoryStore(MemoryStore):
    """Local durable memory with the same namespace permission model.

    This is intentionally a single-host SQLite backend, not a shared service.
    """
    def __init__(self, path: str | Path = ":memory:") -> None:
        # Runtime invokes tools through a worker thread; calls remain serial in the
        # local executor, so permit that thread to use this single local connection.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS memory "
            "(namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "PRIMARY KEY(namespace, key))"
        )
    def close(self) -> None: self.db.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    @staticmethod
    def _permit(actor: str, namespace: str) -> None:
        if namespace.startswith("private:") and namespace != f"private:{actor}":
            raise PermissionError("private memory denied")
        if not (namespace.startswith("private:") or namespace.startswith("shared:")):
            raise PermissionError("invalid memory namespace")
    def put(self, actor: str, namespace: str, key: str, value: Json) -> None:
        self._permit(actor, namespace)
        self.db.execute(
            "INSERT INTO memory(namespace,key,value) VALUES (?,?,?) "
            "ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value",
            (namespace, key, json.dumps(value, sort_keys=True)),
        )
        self.db.commit()
    def get(self, actor: str, namespace: str, key: str) -> Json | None:
        self._permit(actor, namespace)
        row = self.db.execute(
            "SELECT value FROM memory WHERE namespace=? AND key=?", (namespace, key)
        ).fetchone()
        return json.loads(row[0]) if row else None
