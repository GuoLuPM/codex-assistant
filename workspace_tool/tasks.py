"""Operational task/event state, never a second product database.

SQLite connections belong to individual operations. Version 1 is additive.
Effects are referenced from the owning business database, not guessed from text.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Conflict(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class TaskStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("工作台数据版本较新，请更新程序。")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL REFERENCES tasks(id),
                    event_key TEXT, payload TEXT NOT NULL, UNIQUE(task,event_key));
                CREATE INDEX IF NOT EXISTS task_events ON events(task,seq);
                CREATE TABLE IF NOT EXISTS actions (task TEXT NOT NULL REFERENCES tasks(id), id TEXT NOT NULL,
                    hash TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(task,id));
                CREATE TABLE IF NOT EXISTS refs (task TEXT NOT NULL REFERENCES tasks(id), kind TEXT NOT NULL, id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(task,kind,id));
                CREATE TABLE IF NOT EXISTS usage (thread TEXT PRIMARY KEY, payload TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, title="新办一件事", profile="normal"):
        if profile not in ("normal", "low"):
            raise ValueError("无效档位")
        tid = "task_" + secrets.token_hex(12)
        snapshot = {"task_id": tid, "revision": 0, "title": title[:60], "state": "ready", "thread_id": None,
                    "active_turn_id": None, "pending_requests": [], "blocks": [], "artifact_ids": [],
                    "last_event_seq": 0, "model_profile": profile, "error": None}
        with self.db() as db:
            db.execute("INSERT INTO tasks VALUES (?,?,?)", (tid, encoded(snapshot), time.time()))
        return snapshot

    @staticmethod
    def _snapshot(db, tid):
        row = db.execute("SELECT snapshot FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise ValueError("找不到这件事，请从最近记录中重新打开。")
        return json.loads(row[0])

    def snapshot(self, tid):
        with self.db() as db:
            return self._snapshot(db, tid)

    def recent(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid limit")
        with self.db() as db:
            return [{k: s[k] for k in ("task_id", "title", "state", "model_profile")} for s in
                    (json.loads(row[0]) for row in db.execute("SELECT snapshot FROM tasks ORDER BY updated DESC LIMIT ?", (limit,)))]

    def accept_action(self, action):
        tid, ident = action["task_id"], action["request_id"]
        if not isinstance(ident, str) or not 1 <= len(ident) <= 100:
            raise ValueError("无效操作编号")
        signature = fingerprint(action)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT hash,receipt FROM actions WHERE task=? AND id=?", (tid, ident)).fetchone()
            if existing:
                if existing[0] != signature:
                    raise Conflict("这次操作的内容已经变化，请重新操作。")
                return json.loads(existing[1])
            state = self._snapshot(db, tid)
            if type(action.get("expected_revision")) is not int or state["revision"] != action["expected_revision"]:
                raise Conflict("页面状态已更新，请重新操作。")
            if action["kind"] == "message" and (state["active_turn_id"] or state["state"] in ("running", "awaiting_user")):
                raise Conflict("我正在处理上一条，请等一下，或先点停止。")
            receipt = {"request_id": ident, "state": "accepted", "result": None}
            db.execute("INSERT INTO actions VALUES (?,?,?,?)", (tid, ident, signature, encoded(receipt)))
            state["revision"] += 1
            db.execute("UPDATE tasks SET snapshot=?,updated=? WHERE id=?", (encoded(state), time.time(), tid))
            return receipt

    def finish_action(self, tid, ident, state, result=None):
        if state not in ("pending", "completed", "failed"):
            raise ValueError("Invalid receipt state")
        receipt = {"request_id": ident, "state": state, "result": result}
        with self.db() as db:
            if db.execute("UPDATE actions SET receipt=? WHERE task=? AND id=?", (encoded(receipt), tid, ident)).rowcount != 1:
                raise ValueError("Unknown action")
        return receipt

    def action(self, tid, ident):
        with self.db() as db:
            row = db.execute("SELECT receipt FROM actions WHERE task=? AND id=?", (tid, ident)).fetchone()
            return json.loads(row[0]) if row else None

    def record(self, tid, kind, data, *, key=None):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if key is not None:
                row = db.execute("SELECT payload FROM events WHERE task=? AND event_key=?", (tid, key)).fetchone()
                if row:
                    return json.loads(row[0])
            state = self._snapshot(db, tid)
            self.reduce(state, kind, data)
            state["revision"] += 1
            cursor = db.execute("INSERT INTO events(task,event_key,payload) VALUES (?,?,?)", (tid, key, "{}"))
            state["last_event_seq"] = cursor.lastrowid
            event = {"task_id": tid, "seq": cursor.lastrowid, "type": kind, "revision": state["revision"], "data": data}
            db.execute("UPDATE events SET payload=? WHERE seq=?", (encoded(event), cursor.lastrowid))
            db.execute("UPDATE tasks SET snapshot=?,updated=? WHERE id=?", (encoded(state), time.time(), tid))
            return event

    @staticmethod
    def reduce(state, kind, data):
        if kind == "thread":
            state["thread_id"] = data["thread_id"]
        elif kind == "title":
            state["title"] = data["title"][:60]
        elif kind == "turn_started":
            state.update(state="running", active_turn_id=data.get("turn_id"), error=None)
        elif kind == "turn_ended":
            status = data["status"]
            state.update(state={"completed": "ready", "interrupted": "interrupted", "failed": "failed"}.get(status, "failed"),
                         active_turn_id=None, pending_requests=[], error=data.get("message"))
        elif kind == "error":
            state.update(state="failed", active_turn_id=None, error=data["message"])
        elif kind == "question":
            state["pending_requests"] = [r for r in state["pending_requests"] if r["request_id"] != data["request_id"]] + [data]
            state["state"] = "awaiting_user"
        elif kind == "answered":
            state["pending_requests"] = [r for r in state["pending_requests"] if r["request_id"] != data["request_id"]]
            state["state"] = "awaiting_user" if state["pending_requests"] else "running"
        elif kind in ("text_delta", "text_done", "user_message"):
            block = next((b for b in state["blocks"] if b["block_id"] == data["block_id"]), None)
            if block is None:
                block = {"block_id": data["block_id"], "kind": "text", "body": {"text": "", "role": "user" if kind == "user_message" else "assistant"}, "actions": []}
                state["blocks"].append(block)
            block["body"]["text"] = block["body"]["text"] + data["delta"] if kind == "text_delta" else data["text"]
            block["body"]["complete"] = kind != "text_delta"
            if data.get("input_ids"):
                block["body"]["input_ids"] = data["input_ids"]
        elif kind == "block":
            index = next((i for i, b in enumerate(state["blocks"]) if b["block_id"] == data["block_id"]), None)
            if index is None:
                state["blocks"].append(data)
            else:
                state["blocks"][index] = data
        elif kind == "artifact":
            if not data.get("verification_ref"):
                raise ValueError("Artifact requires verification receipt")
            if data["artifact_id"] not in state["artifact_ids"]:
                state["artifact_ids"].append(data["artifact_id"])
            state["state"] = "completed"
        elif kind not in ("progress", "usage", "selection", "input"):
            raise ValueError("Unknown task event")

    def events_after(self, tid, seq, limit=200):
        self.snapshot(tid)
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE task=? AND seq>? ORDER BY seq LIMIT ?", (tid, seq, min(limit, 500)))]

    def add_ref(self, tid, kind, ident, payload):
        with self.db() as db:
            self._snapshot(db, tid)
            old = db.execute("SELECT payload FROM refs WHERE task=? AND kind=? AND id=?", (tid, kind, ident)).fetchone()
            if old and json.loads(old[0]) != payload:
                raise Conflict("Reference is immutable")
            db.execute("INSERT OR IGNORE INTO refs VALUES (?,?,?,?)", (tid, kind, ident, encoded(payload)))

    def ref(self, tid, kind, ident):
        with self.db() as db:
            row = db.execute("SELECT payload FROM refs WHERE task=? AND kind=? AND id=?", (tid, kind, ident)).fetchone()
            if not row:
                raise ValueError("这份资料不属于当前任务。")
            return json.loads(row[0])

    def refs(self, tid, kind):
        with self.db() as db:
            return [{"id": r[0], **json.loads(r[1])} for r in db.execute("SELECT id,payload FROM refs WHERE task=? AND kind=?", (tid, kind))]

    def recover(self):
        with self.db() as db:
            states = [json.loads(r[0]) for r in db.execute("SELECT snapshot FROM tasks")]
        for state in states:
            if state["state"] in ("running", "awaiting_user"):
                self.record(state["task_id"], "turn_ended", {"status": "interrupted", "message": "上次连接已中断，您可以接着说。已保存的资料和选择还在。"})
