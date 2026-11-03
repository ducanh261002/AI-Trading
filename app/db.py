import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
                    kind TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, started_at TEXT,
                    finished_at TEXT, result TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT, created_at TEXT NOT NULL,
                    level TEXT NOT NULL, message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS safety (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    halted INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
            """)
            connection.execute("INSERT OR IGNORE INTO safety VALUES (1, 1, ?)", (now(),))
            connection.execute("UPDATE safety SET halted=1, updated_at=? WHERE id=1", (now(),))
            connection.execute("INSERT INTO events(task_id,created_at,level,message) VALUES(NULL,?, 'INFO', 'Foundation started; execution unavailable')", (now(),))

    def health(self):
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    def halted(self):
        with self.connect() as connection:
            return bool(connection.execute("SELECT halted FROM safety WHERE id=1").fetchone()[0])

    def halt(self):
        with self.connect() as connection:
            connection.execute("UPDATE safety SET halted=1, updated_at=? WHERE id=1", (now(),))
            connection.execute("INSERT INTO events(task_id,created_at,level,message) VALUES(NULL,?, 'WARNING', 'Kill switch activated')", (now(),))

    def diagnostic(self):
        task_id, timestamp = str(uuid4()), now()
        with self.connect() as connection:
            connection.execute("INSERT INTO tasks(id,agent_id,kind,status,created_at,started_at) VALUES (?, 'monitor', 'foundation_diagnostic', 'Working', ?, ?)", (task_id, timestamp, timestamp))
            connection.execute("INSERT INTO events(task_id,created_at,level,message) VALUES(?,?, 'INFO', 'Foundation diagnostic started')", (task_id, timestamp))
        try:
            result = {"database": self.health(), "mode": "paper", "execution_available": False}
            with self.connect() as connection:
                connection.execute("UPDATE tasks SET status='Completed', finished_at=?, result=? WHERE id=?", (now(), json.dumps(result), task_id))
                connection.execute("INSERT INTO events(task_id,created_at,level,message) VALUES(?,?, 'INFO', 'Foundation diagnostic completed')", (task_id, now()))
        except Exception:
            with self.connect() as connection:
                connection.execute("UPDATE tasks SET status='Error', finished_at=?, error='Diagnostic failed' WHERE id=?", (now(), task_id))
            raise
        return task_id

    def list_rows(self, table):
        if table not in {"tasks", "events"}:
            raise ValueError("Unsupported table")
        order = "created_at DESC, rowid DESC" if table == "tasks" else "id DESC"
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order} LIMIT 100")]
        if table == "tasks":
            for row in rows:
                row["result"] = json.loads(row["result"]) if row["result"] else None
        return rows
