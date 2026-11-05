"""Durable parameterized SQLite store; JSON archives remain available for audits."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, body TEXT NOT NULL)")
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def save(self, call):
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO calls (id,created_at,body) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                       (call["call_id"], call["created_at"], json.dumps(call)))

    def load(self):
        with closing(self.connect()) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM calls ORDER BY created_at")]
