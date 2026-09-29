"""Frozen candidate sessions. The browser can only change selection membership."""

import json
import secrets
import time
from pathlib import Path

from catalog_store import resolve_price
from pool_store import encoded


class Selections:
    def __init__(self, pool):
        self.pool = pool
        self.db = pool.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS pool_sessions (
            id TEXT PRIMARY KEY, token TEXT NOT NULL, title TEXT NOT NULL,
            price_fields TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS pool_choices (
            session_id TEXT NOT NULL REFERENCES pool_sessions(id),
            product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
            payload_hash TEXT NOT NULL, snapshot TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(session_id,product_id));
        """)
        if 'context_hash' not in {row[1] for row in self.db.execute('PRAGMA table_info(pool_choices)')}:
            self.db.execute('ALTER TABLE pool_choices ADD COLUMN context_hash TEXT')

    def create(self, ids, price_fields, title="请选择产品"):
        if not ids or len(ids) > 100 or len(ids) != len(set(ids)):
            raise ValueError("Choose 1..100 distinct candidate IDs")
        if not price_fields or len(price_fields) > 2 or len(price_fields) != len(set(price_fields)):
            raise ValueError("Choose 1..2 explicit customer-facing price fields")
        if not isinstance(title, str) or not 1 <= len(title) <= 160:
            raise ValueError("Invalid selection title")
        items = self.pool.details(ids, verify_fresh=True)
        snapshots = []
        for item in items:
            prices = [resolve_price(item["prices"], role) for role in price_fields]
            if any(p is None or p.get("error") for p in prices):
                raise ValueError("Display price absent/ambiguous/error; select a valid shared price role")
            image = item.get("product_image") or item.get("package_image")
            snapshot = {"id": item["id"], "name": item["name"], "model": item.get("model"), "variant": item.get("variant"),
                        "features": item["features"], "prices": prices, "category": item["category"],
                        "source_file": item["source_file"], "locator": f"{item['sheet']} / {item['row']}",
                        "image": str(Path(image).relative_to(self.pool.root)) if image else None,
                        "tags": item["tags"]}
            member = self.db.execute("SELECT payload_hash FROM pool_members WHERE product_id=?", (item["id"],)).fetchone()
            snapshots.append((item["id"], member[0], snapshot, self.pool.selection_context(item["id"])))
        session_id = "s_" + secrets.token_hex(12)
        with self.db:
            self.db.execute("INSERT INTO pool_sessions(id,token,title,price_fields,created_at) VALUES (?,?,?,?,?)",
                            (session_id, secrets.token_urlsafe(32), title, encoded(price_fields), time.time()))
            self.db.executemany("INSERT INTO pool_choices(session_id,product_id,position,payload_hash,snapshot,context_hash) VALUES (?,?,?,?,?,?)",
                                [(session_id, product_id, position, signature, encoded(snapshot), context)
                                 for position, (product_id, signature, snapshot, context) in enumerate(snapshots)])
        directory = self.pool.root / "sessions" / session_id
        directory.mkdir(parents=True, exist_ok=True)
        template = Path(__file__).with_name("pool_select.html").read_text(encoding="utf-8")
        (directory / "index.html").write_text(template, encoding="utf-8")
        return {"session_id": session_id, "candidates": len(ids), "html": str(directory / "index.html"), "next": "open --session " + session_id}

    def session(self, session_id):
        row = self.db.execute("SELECT * FROM pool_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("Unknown selection session")
        return dict(row)

    def state(self, session_id, include_items=False):
        session = self.session(session_id)
        rows = self.db.execute("SELECT * FROM pool_choices WHERE session_id=? ORDER BY position", (session_id,)).fetchall()
        result = {"session_id": session_id, "title": session["title"], "revision": session["revision"],
                  "state": session["state"], "candidates": len(rows), "selected_ids": [r["product_id"] for r in rows if r["selected"]],
                  "price_fields": json.loads(session["price_fields"])}
        if include_items:
            result["items"] = [{**json.loads(r["snapshot"]), "selected": bool(r["selected"])} for r in rows]
        return result

    def select(self, session_id, ids, revision):
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            raise ValueError("Invalid selected IDs")
        candidates = {r[0] for r in self.db.execute("SELECT product_id FROM pool_choices WHERE session_id=?", (session_id,))}
        if not set(ids) <= candidates:
            raise ValueError("Selection includes products outside this session")
        with self.db:
            updated = self.db.execute("UPDATE pool_sessions SET revision=revision+1 WHERE id=? AND revision=? AND state='open'", (session_id, revision))
            if updated.rowcount != 1:
                raise ValueError("Selection revision conflict or session sealed; reload current choices")
            self.db.execute("UPDATE pool_choices SET selected=0 WHERE session_id=?", (session_id,))
            self.db.executemany("UPDATE pool_choices SET selected=1 WHERE session_id=? AND product_id=?", [(session_id, i) for i in ids])
        return self.state(session_id)

    def seal(self, session_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.state(session_id)
            if state["state"] == "closed":
                raise ValueError("Selection session is closed; create a new selection")
            if not state["selected_ids"]:
                raise ValueError("No products selected; let the user select in HTML first")
            self.verify(session_id, selected_only=True)
            self.db.execute("UPDATE pool_sessions SET state='sealed' WHERE id=?", (session_id,))
        return self.state(session_id)

    def verify(self, session_id, selected_only=False):
        condition = ' AND c.selected=1' if selected_only else ''
        rows = list(self.db.execute('''SELECT c.product_id,c.context_hash,c.payload_hash AS frozen,m.payload_hash AS current
            FROM pool_choices c JOIN pool_members m ON m.product_id=c.product_id WHERE c.session_id=?''' + condition, (session_id,)))
        for row in rows:
            if row['frozen'] != row['current']:
                raise ValueError('Selected product changed since presentation of choices')
            current = self.pool.selection_context(row['product_id'])
            if row['context_hash'] is not None and row['context_hash'] != current:
                raise ValueError('Selected quote/recommendation context changed; create a fresh selection')
        self.pool.details([row['product_id'] for row in rows], verify_fresh=True)
