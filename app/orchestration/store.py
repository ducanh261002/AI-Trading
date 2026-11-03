import json
from uuid import uuid4

from app.db import now

TERMINAL = {"Completed", "Waiting", "Error", "Cancelled"}


class TaskStore:
    def __init__(self, database):
        self.database = database

    def initialize(self):
        with self.database.connect() as con:
            columns = {row["name"] for row in con.execute("PRAGMA table_info(tasks)")}
            additions = {"run_id": "TEXT", "tool": "TEXT", "input_json": "TEXT",
                         "depends_on": "TEXT", "attempts": "INTEGER NOT NULL DEFAULT 0",
                         "max_attempts": "INTEGER NOT NULL DEFAULT 2"}
            for name, declaration in additions.items():
                if name not in columns:
                    con.execute(f"ALTER TABLE tasks ADD COLUMN {name} {declaration}")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL, interval TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS tasks_run_id ON tasks(run_id);
            """)

    @staticmethod
    def event(con, task_id, level, message):
        con.execute("INSERT INTO events(task_id,created_at,level,message) VALUES(?,?,?,?)",
                    (task_id, now(), level, message))

    def recover(self):
        with self.database.connect() as con:
            for task in con.execute("SELECT * FROM tasks WHERE run_id IS NOT NULL AND status IN ('Working','Thinking')").fetchall():
                status = "Pending" if task["attempts"] < task["max_attempts"] else "Error"
                con.execute("UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
                            (status, "Interrupted by restart", now() if status == "Error" else None, task["id"]))
                self.event(con, task["id"], "WARNING", "Interrupted task recovered: " + status)

    def enqueue(self, symbol, interval, request_key, plan):
        with self.database.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT * FROM agent_runs WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                if existing["symbol"] != symbol or existing["interval"] != interval:
                    raise ValueError("Request key already used for a different cycle")
                return existing["id"], False
            count = con.execute("SELECT COUNT(*) FROM agent_runs WHERE status IN ('Pending','Working')").fetchone()[0]
            if count >= 4:
                raise OverflowError("Agent queue full (4 active cycles)")
            run_id = str(uuid4())
            con.execute("INSERT INTO agent_runs VALUES(?,?,?,?, 'Pending', ?, NULL)",
                        (run_id, request_key, symbol, interval, now()))
            task_ids = {agent: str(uuid4()) for agent, tool, deps in plan}
            for agent, tool, deps in plan:
                task_id = task_ids[agent]
                con.execute("""INSERT INTO tasks(id,agent_id,kind,status,created_at,run_id,tool,input_json,depends_on)
                    VALUES(?,?, 'agent_cycle', 'Pending', ?, ?, ?, ?, ?)""",
                            (task_id, agent, now(), run_id, tool, json.dumps({"symbol": symbol, "interval": interval}),
                             json.dumps([task_ids[d] for d in deps])))
                self.event(con, task_id, "INFO", "Task queued: " + tool)
            return run_id, True

    def claim(self):
        with self.database.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            candidates = con.execute("SELECT * FROM tasks WHERE run_id IS NOT NULL AND status='Pending' ORDER BY created_at,rowid").fetchall()
            for row in candidates:
                task = dict(row)
                deps = json.loads(task["depends_on"])
                if deps:
                    states = [con.execute("SELECT status FROM tasks WHERE id=?", (dep,)).fetchone() for dep in deps]
                    if any(state is None or state[0] not in TERMINAL for state in states):
                        continue
                con.execute("UPDATE tasks SET status='Working', started_at=?, finished_at=NULL, error=NULL, attempts=attempts+1 WHERE id=?", (now(), task["id"]))
                con.execute("UPDATE agent_runs SET status='Working' WHERE id=?", (task["run_id"],))
                self.event(con, task["id"], "INFO", "Task started")
                task["attempts"] += 1
                task["input"] = json.loads(task["input_json"])
                return task
        return None

    def transition(self, task_id, status, result=None, error=None):
        with self.database.connect() as con:
            con.execute("UPDATE tasks SET status=?, result=?, error=?, finished_at=? WHERE id=?",
                        (status, json.dumps(result) if result is not None else None, error,
                         now() if status in TERMINAL else None, task_id))
            self.event(con, task_id, "ERROR" if status == "Error" else "INFO", "Task " + status + (": " + error if error else ""))

    def settle(self):
        with self.database.connect() as con:
            runs = con.execute("SELECT id FROM agent_runs WHERE status IN ('Pending','Working')").fetchall()
            for run in runs:
                states = [row[0] for row in con.execute("SELECT status FROM tasks WHERE run_id=?", (run[0],))]
                if states and all(state in TERMINAL for state in states):
                    status = "Completed" if all(state == "Completed" for state in states) else "CompletedWithWarnings"
                    con.execute("UPDATE agent_runs SET status=?,finished_at=? WHERE id=?", (status, now(), run[0]))

    def run(self, run_id):
        with self.database.connect() as con:
            row = con.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["tasks"] = self.tasks(con, run_id)
            return result

    @staticmethod
    def tasks(con, run_id):
        result = []
        for row in con.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY created_at,rowid", (run_id,)):
            task = dict(row)
            for column in ("result", "input_json", "depends_on"):
                task[column] = json.loads(task[column]) if task[column] else None
            result.append(task)
        return result

    def runs(self):
        with self.database.connect() as con:
            return [dict(row) for row in con.execute("SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT 50")]

    def latest_agents(self):
        with self.database.connect() as con:
            rows = con.execute("""SELECT id,agent_id,status,tool,created_at FROM tasks
                WHERE rowid IN (SELECT MAX(rowid) FROM tasks WHERE run_id IS NOT NULL GROUP BY agent_id)""")
            result = {}
            for row in rows:
                result[row["agent_id"]] = dict(row)
            # An older running task takes precedence over a newer queued task.
            for row in con.execute("SELECT id,agent_id,status,tool,created_at FROM tasks WHERE run_id IS NOT NULL AND status IN ('Working','Thinking')"):
                result[row["agent_id"]] = dict(row)
            return result
