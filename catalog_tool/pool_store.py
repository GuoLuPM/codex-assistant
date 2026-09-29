"""Persistent content-addressed product pool; Codex supplies source-backed semantics."""

import copy
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from catalog_store import Catalog, check_sources, normalize, sha


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


class Pool(Catalog):
    def __init__(self, root, config=None):
        super().__init__(root, config)
        if (not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='pool_documents'").fetchone()
                and self.db.execute("SELECT count(*) FROM products").fetchone()[0]):
            self.close()
            raise ValueError("This is a legacy index; use a separate pool directory and adopt its sources")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS pool_documents (
            id TEXT PRIMARY KEY, hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            object_path TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS pool_aliases (
            document_id TEXT NOT NULL REFERENCES pool_documents(id), path TEXT NOT NULL,
            PRIMARY KEY(document_id,path));
          CREATE TABLE IF NOT EXISTS pool_members (
            product_id TEXT PRIMARY KEY REFERENCES products(id),
            document_id TEXT NOT NULL REFERENCES pool_documents(id), record_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL, UNIQUE(document_id,record_key));
          CREATE TABLE IF NOT EXISTS pool_tags (
            product_id TEXT NOT NULL REFERENCES products(id), kind TEXT NOT NULL, value TEXT NOT NULL,
            origin TEXT NOT NULL CHECK(origin IN ('source','inferred')), reason TEXT NOT NULL, evidence TEXT NOT NULL,
            PRIMARY KEY(product_id,kind,value));
          CREATE INDEX IF NOT EXISTS pool_tags_lookup ON pool_tags(kind,value,origin,product_id);
          CREATE TABLE IF NOT EXISTS pool_observations (
            document_id TEXT NOT NULL REFERENCES pool_documents(id), id TEXT NOT NULL,
            image_ref TEXT NOT NULL, text TEXT NOT NULL, reviewer TEXT NOT NULL,
            PRIMARY KEY(document_id,id));
          CREATE TABLE IF NOT EXISTS pool_evidence (
            document_id TEXT PRIMARY KEY REFERENCES pool_documents(id), entries TEXT NOT NULL);
        """)

    def document(self, file_id):
        row = self.db.execute("SELECT * FROM pool_documents WHERE id=?", (file_id,)).fetchone()
        if not row:
            raise ValueError("Unknown file_id; use files")
        return dict(row)

    def source(self, file_id, verify=True):
        document = self.document(file_id)
        path = (self.root / document["object_path"]).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("Pool original missing or outside pool")
        if verify and sha(path) != document["hash"]:
            raise ValueError("Pool original hash changed; restore the exact original")
        return path

    def files(self, limit=10, offset=0):
        if not 1 <= limit <= 50 or offset < 0:
            raise ValueError("Invalid pagination")
        rows = self.db.execute("""SELECT d.id AS file_id,d.name,d.status,
            (SELECT count(*) FROM pool_members m WHERE m.document_id=d.id) AS products
            FROM pool_documents d ORDER BY d.created_at,d.id LIMIT ? OFFSET ?""", (limit, offset))
        return {"total": self.db.execute("SELECT count(*) FROM pool_documents").fetchone()[0],
                "items": [dict(r) for r in rows], "offset": offset, "limit": limit}

    def add(self, source, mapping_path=None):
        source = Path(source).resolve()
        if not source.is_file():
            raise ValueError(f"Input file missing: {source}")
        content_hash = sha(source)
        file_id = "d_" + content_hash
        old = self.db.execute("SELECT * FROM pool_documents WHERE id=?", (file_id,)).fetchone()
        if old:
            self.source(file_id)
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO pool_aliases VALUES (?,?)", (file_id, str(source)))
            if old["status"] != "pending" or not mapping_path:
                return {"file_id": file_id, "status": "duplicate" if old["status"] != "pending" else "needs_mapping",
                        "products_added": 0, "document_status": old["status"],
                        "next": "search" if old["status"] == "ready" else "inspect to continue the incomplete source"}
        else:
            target = self.root / "objects" / content_hash / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(".incoming-" + uuid.uuid4().hex)
            try:
                shutil.copyfile(source, temporary)
                if sha(temporary) != content_hash or sha(source) != content_hash:
                    raise ValueError("Input changed during snapshot")
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            with self.db:
                self.db.execute("INSERT INTO pool_documents VALUES (?,?,?,?,?,?)", (
                    file_id, content_hash, source.name, target.relative_to(self.root).as_posix(), "pending", time.time()))
                self.db.execute("INSERT INTO pool_aliases VALUES (?,?)", (file_id, str(source)))
        source_copy = self.source(file_id)
        if source_copy.suffix.lower() != ".xlsx":
            return {"file_id": file_id, "status": "needs_mapping", "products_added": 0,
                    "next": "inspect, then import source-backed records"}
        from extract import read_products
        schema, _, _ = self._source_schema(source, mapping_path)
        try:
            items, skipped = read_products(source_copy, self.root / "assets", schema)
        except ValueError as error:
            return {"file_id": file_id, "status": "needs_mapping", "products_added": 0,
                    "diagnostic": str(error)[:600], "next": "inspect XLSX and add again with --map"}
        pairs = []
        for item in items:
            key = encoded([item["sheet"], item["row"], item["source_cells"], item.get("variant")])
            pairs.append((key, item))
        result = self._commit(file_id, pairs, status="ready")
        if mapping_path:
            (source_copy.parent / "mapping.local.json").write_text(encoded(schema["mapping"]), encoding="utf-8")
        return {"file_id": file_id, "status": "ready", "products_added": result["added"], "skipped_sheets": skipped}

    def _commit(self, file_id, pairs, status="partial"):
        document = self.document(file_id)
        source = self.source(file_id)
        stat = source.stat()
        added = skipped = 0
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?)", (
                file_id, document["hash"], stat.st_size, stat.st_mtime_ns, "pool-v1", time.time(), None))
            for key, raw in pairs:
                item = copy.deepcopy(raw)
                item["id"] = "p_" + digest([document["hash"], key])[:32]
                item["source_path"], item["source_file"], item["source_hash"] = file_id, document["name"], document["hash"]
                for image in item["images"]:
                    image["path"] = Path(image["path"]).resolve().relative_to(self.root).as_posix()
                for role in ("product_image", "package_image"):
                    if item[role]:
                        item[role] = Path(item[role]).resolve().relative_to(self.root).as_posix()
                item = self._decorate(item)
                signature = digest(item)
                old = self.db.execute("SELECT payload_hash FROM pool_members WHERE document_id=? AND record_key=?", (file_id, key)).fetchone()
                if old:
                    if old[0] != signature:
                        raise ValueError(f"Record conflict for {key}; inspect existing evidence instead of overwriting")
                    skipped += 1
                    continue
                self._insert(item)
                self.db.execute("INSERT INTO pool_members VALUES (?,?,?,?)", (item["id"], file_id, key, signature))
                added += 1
            self.db.execute("UPDATE pool_documents SET status=? WHERE id=?", (status, file_id))
        return {"file_id": file_id, "added": added, "skipped": skipped}

    def _native_evidence(self, file_id):
        from pool_documents import read_evidence
        source = self.source(file_id)
        cached = self.db.execute("SELECT entries FROM pool_evidence WHERE document_id=?", (file_id,)).fetchone()
        if cached:
            entries = json.loads(cached[0])
        else:
            entries = read_evidence(source, self.root / "assets", allow_empty=True)
            self._save_evidence(file_id, entries)
        for entry in entries:
            if entry.get("path"):
                entry["path"] = str(self.root / entry["path"])
        return entries

    def _save_evidence(self, file_id, entries):
        entries = copy.deepcopy(entries)
        for entry in entries:
            if entry.get("path"):
                entry["path"] = Path(entry["path"]).resolve().relative_to(self.root).as_posix()
        with self.db:
            self.db.execute("INSERT INTO pool_evidence VALUES (?,?) ON CONFLICT(document_id) DO UPDATE SET entries=excluded.entries",
                            (file_id, encoded(entries)))

    def preview(self, file_id, page):
        from pool_documents import render_page
        preview = render_page(self.source(file_id), self.root / "assets", page)
        entries = [e for e in self._native_evidence(file_id) if e["id"] != preview["id"]]
        self._save_evidence(file_id, [*entries, preview])
        return preview

    def evidence(self, file_id):
        entries = self._native_evidence(file_id)
        if not entries:
            raise ValueError("No native evidence extracted; PDF may require render then visual observation")
        image_pages = {e["id"]: e["page"] for e in entries if e["kind"] == "image"}
        for row in self.db.execute("SELECT * FROM pool_observations WHERE document_id=?", (file_id,)):
            entries.append({"id": row["id"], "kind": "text", "text": row["text"],
                            "locator": f"visual observation of {row['image_ref']}", "page": image_pages[row["image_ref"]],
                            "verification": "visual", "reviewer": row["reviewer"]})
        return entries

    def observe(self, file_id, image_ref, text, reviewer):
        evidence = {e["id"]: e for e in self.evidence(file_id)}
        if image_ref not in evidence or evidence[image_ref]["kind"] != "image":
            raise ValueError("Observation requires an existing image ref")
        if not text.strip() or len(text) > 20000 or not reviewer.strip():
            raise ValueError("Observation requires bounded text and named reviewer")
        observation_id = "visual-" + digest([image_ref, text])[:20]
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO pool_observations VALUES (?,?,?,?,?)", (file_id, observation_id, image_ref, text, reviewer))
        return {"ref": observation_id, "verification": "visual", "warning": "Model transcription, not machine-verified text"}

    def import_records(self, file_id, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError("Import accepts 1..100 records per bounded batch")
        entries = {e["id"]: e for e in self.evidence(file_id)}

        def fact(ref):
            if not isinstance(ref, dict) or set(ref) - {"ref", "quote"} or not isinstance(ref.get("ref"), str):
                raise ValueError("Facts require {ref, quote?}; free values are not accepted")
            entry = entries.get(ref["ref"])
            if not entry or entry["kind"] != "text":
                raise ValueError("Unknown text evidence ref")
            value = ref.get("quote", entry["text"])
            if not isinstance(value, str) or not value.strip() or value not in entry["text"]:
                raise ValueError("Fact quote must occur verbatim in cited evidence")
            return value, entry

        pairs = []
        for record in records:
            if not isinstance(record, dict) or set(record) - {"key", "fields", "prices", "features", "images"}:
                raise ValueError("Unknown record keys")
            fields = record.get("fields", {})
            if not isinstance(fields, dict) or "name" not in fields or set(fields) - {"name", "model", "variant", "category", "brand", "supplier"}:
                raise ValueError("Record requires a sourced name; unknown field")
            if (not isinstance(record.get("prices", {}), dict) or not isinstance(record.get("features", []), list)
                    or not isinstance(record.get("images", []), list)):
                raise ValueError("prices must be an object; features/images must be arrays, alongside fields")
            key = record.get("key")
            if not isinstance(key, str) or not 1 <= len(key) <= 200:
                raise ValueError("Record key must be a stable source locator (1..200 characters)")
            cells, raw, refs, issues = {}, {}, {}, []

            def get(value, field):
                text, entry = fact(value)
                cells[field], refs[field], raw[field] = entry["locator"], [entry["locator"]], text
                if entry.get("verification") == "visual":
                    issues.append("视觉转录:未经原生文本校验")
                return text

            values = {name: get(ref, name) for name, ref in fields.items()}
            prices = {}
            for role, price in record.get("prices", {}).items():
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", role) or not isinstance(price, dict) or set(price) != {"label", "value"}:
                    raise ValueError("Price needs a canonical role, sourced label and sourced value")
                prices[role] = {"label": get(price["label"], role + ".label"), "value": get(price["value"], role)}
            features = [get(ref, f"feature.{i}") for i, ref in enumerate(record.get("features", []))]
            name_entry = fact(fields["name"])[1]
            item = {"name": values["name"], **{k: values.get(k) for k in ("model", "variant", "category", "brand", "supplier")},
                    "serial": None, "sheet": name_entry["locator"], "row": name_entry.get("page", 1), "end_row": name_entry.get("page", 1),
                    "features": "\n".join(features), "prices": prices, "raw_fields": raw, "source_cells": cells, "field_cells": refs,
                    "issues": issues, "unmapped_fields": [], "images": [], "product_image": None, "package_image": None,
                    "product_image_sha256": None, "package_image_sha256": None}
            for image_id in record.get("images", []):
                if not isinstance(image_id, str):
                    raise ValueError("Image refs must be strings from inspect")
                entry = entries.get(image_id)
                if not entry or entry["kind"] != "image":
                    raise ValueError("Unknown source image ref")
                item["images"].append({**entry, "role": "product_image", "cell": entry["locator"]})
                if not item["product_image"]:
                    item["product_image"], item["product_image_sha256"] = entry["path"], entry["sha256"]
            pairs.append((key, item))
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("Duplicate record key in batch")
        return self._commit(file_id, pairs)

    def stale_sources(self):
        stale = []
        for row in self.db.execute("SELECT path,size,mtime FROM sources"):
            try:
                stat = self.source(row["path"], verify=False).stat()
                if (stat.st_size, stat.st_mtime_ns) != (row["size"], row["mtime"]):
                    stale.append(row["path"])
            except (OSError, ValueError):
                stale.append(row["path"])
        return stale

    def details(self, ids, verify_fresh=False):
        items = super().details(ids, verify_fresh=False)
        for item in items:
            file_id = item["source_path"]
            item["file_id"] = file_id
            item["source_path"] = str(self.source(file_id, verify=False))
            for role in ("product_image", "package_image"):
                if item[role]:
                    item[role] = str(self.root / item[role])
            for image in item["images"]:
                image["path"] = str(self.root / image["path"])
            item["tags"] = self.tags(item["id"])
        if verify_fresh:
            check_sources(items)
            for item in items:
                for role in ("product_image", "package_image"):
                    if item[role] and (not Path(item[role]).is_file() or sha(item[role]) != item[role + "_sha256"]):
                        raise ValueError("Pool image cache changed or missing; restore original image")
        return items

    def tags(self, product_id):
        return [dict(r) for r in self.db.execute("SELECT kind,value,origin,reason,evidence FROM pool_tags WHERE product_id=? ORDER BY kind,value", (product_id,))]

    def annotate(self, entries):
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise ValueError("Annotate accepts 1..100 entries")
        prepared = []
        for tag in entries:
            if set(tag) != {"id", "kind", "value", "origin", "reason", "evidence"}:
                raise ValueError("Tag requires id/kind/value/origin/reason/evidence")
            item = self.details([tag["id"]], verify_fresh=True)[0]
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", tag["kind"]) or not 1 <= len(tag["value"]) <= 120:
                raise ValueError("Invalid tag kind/value")
            original = "\n".join(str(item.get(k) or "") for k in ("name", "model", "variant", "features", "category")) + encoded(item["raw_fields"])
            if not tag["evidence"] or tag["evidence"] not in original or len(tag["evidence"]) > 1000:
                raise ValueError("Tag evidence must quote the product's own source facts")
            if tag["origin"] not in {"source", "inferred"} or not tag["reason"] or len(tag["reason"]) > 500:
                raise ValueError("Invalid tag origin/reason")
            if tag["origin"] == "source" and normalize(tag["value"]) not in normalize(tag["evidence"]):
                raise ValueError("Source tag must occur in evidence; semantic interpretation requires inferred")
            prepared.append(tuple(tag[k] for k in ("id", "kind", "value", "origin", "reason", "evidence")))
        with self.db:
            self.db.executemany("""INSERT INTO pool_tags VALUES (?,?,?,?,?,?) ON CONFLICT(product_id,kind,value)
                DO UPDATE SET origin=excluded.origin,reason=excluded.reason,evidence=excluded.evidence""", prepared)
        return {"annotated": len(prepared)}

    def _search_constraints(self, constraints):
        if set(constraints) - {"tags", "tag_mode", "file_id", "tag_origin", "category"}:
            raise ValueError("Unknown pool search constraints")
        where, params, clauses = [], [], []
        if constraints.get("category"):
            category = constraints["category"]
            where.append("""(p.category=? OR substr(p.category,1,?)=? OR EXISTS
                (SELECT 1 FROM pool_tags ct WHERE ct.product_id=p.id AND ct.kind='category'
                 AND (ct.value=? OR substr(ct.value,1,?)=?)))""")
            params.extend([category, len(category)+1, category+"/", category, len(category)+1, category+"/"])
        if constraints.get("file_id"):
            where.append("p.source_path=?")
            params.append(constraints["file_id"])
        tags = constraints.get("tags", [])
        if len(tags) > 12 or constraints.get("tag_mode", "all") not in {"all", "any"}:
            raise ValueError("Invalid tag query")
        for tag in tags:
            kind, sep, value = tag.partition(":")
            if not sep or not kind or not value:
                raise ValueError("Tag query uses kind:value")
            clause = "EXISTS (SELECT 1 FROM pool_tags t WHERE t.product_id=p.id AND t.kind=? AND t.value=?"
            params.extend([kind, value])
            if constraints.get("tag_origin"):
                if constraints["tag_origin"] not in {"source", "inferred"}:
                    raise ValueError("Invalid tag origin")
                clause += " AND t.origin=?"
                params.append(constraints["tag_origin"])
            clauses.append(clause + ")")
        if clauses:
            where.append("(" + (" AND " if constraints.get("tag_mode", "all") == "all" else " OR ").join(clauses) + ")")
        return where, params

    def search(self, **kwargs):
        constraints = dict(kwargs.get("constraints") or {})
        if kwargs.get("category"):
            constraints["category"] = kwargs.pop("category")
        kwargs["constraints"] = constraints
        result = super().search(**kwargs)
        for item in result["items"]:
            tags = self.tags(item["id"])
            item["tags"] = [{k: t[k] for k in ("kind", "value", "origin")} for t in tags[:5]]
            item["tag_count"] = len(tags)
        return result

    def tag_facets(self, kind=None, query="", limit=20, offset=0):
        if not 1 <= limit <= 50 or offset < 0 or len(query) > 160:
            raise ValueError("Invalid tag pagination")
        base = " FROM pool_tags WHERE instr(value,?)>0" + (" AND kind=?" if kind else "") + " GROUP BY kind,value,origin"
        params = [query] + ([kind] if kind else [])
        total = self.db.execute("SELECT count(*) FROM (SELECT 1" + base + ")", params).fetchone()[0]
        rows = self.db.execute("SELECT kind,value,origin,count(*) AS count" + base + " ORDER BY count DESC,kind,value LIMIT ? OFFSET ?", [*params, limit, offset])
        return {"total": total, "items": [dict(r) for r in rows], "limit": limit, "offset": offset}

    def facets(self, field, query="", limit=20, offset=0):
        if field != "category":
            return super().facets(field, query, limit, offset)
        if not 1 <= limit <= 50 or offset < 0 or len(query) > 160:
            raise ValueError("Invalid category pagination")
        base = """ FROM (SELECT id AS product_id,category AS value FROM products
            UNION ALL SELECT product_id,value FROM pool_tags WHERE kind='category')
            WHERE value<>'' AND instr(value,?)>0 GROUP BY value"""
        total = self.db.execute("SELECT count(*) FROM (SELECT 1" + base + ")", (query,)).fetchone()[0]
        rows = self.db.execute("SELECT value,count(DISTINCT product_id) AS count" + base + " ORDER BY count DESC,value LIMIT ? OFFSET ?", (query, limit, offset))
        return {"field": "category", "total": total, "items": [dict(row) for row in rows], "limit": limit, "offset": offset}

    def stats(self):
        result = super().stats()
        result["category_count"] = self.facets("category", limit=1)["total"]
        return result
