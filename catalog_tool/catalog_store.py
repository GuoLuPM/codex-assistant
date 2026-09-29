"""Local incremental product index; all model-facing results are bounded JSON."""

import fnmatch
import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from collections import Counter

IMPORT_VERSION = 5  # Distinct commercial price bases; legacy pools keep immutable payloads.

def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold()).strip()


def parse_price(value):
    if value is None or isinstance(value, bool):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"^[¥￥]\s*|\s*元$", "", text)
    if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text):
        return None
    number = float(text.replace(",", ""))
    return number if math.isfinite(number) else None


def grams(text, query=False):
    """Unicode character grams make 1/2-character Chinese queries indexable."""
    text = normalize(text)
    sizes = [min(2, len(text))] if query else [1, 2]
    return sorted({"g" + "".join(f"{ord(c):06x}" for c in text[i:i + size])
                   for size in sizes if size for i in range(len(text) - size + 1)})


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_sources(items):
    sources = {item["source_path"]: item["source_hash"] for item in items if item.get("source_path")}
    for source, expected in sources.items():
        path = Path(source)
        if not path.is_file() or sha(path) != expected:
            raise ValueError(f"Source changed or missing (stale selection): {path.name}; run index and search again")


def resolve_price(prices, field):
    if field in prices:
        return prices[field]
    matches = [price for price in prices.values() if price["label"] == field]
    return matches[0] if len(matches) == 1 else None


class Catalog:
    def __init__(self, root, config=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.signature = hashlib.sha256(json.dumps(
            {"import_version": IMPORT_VERSION, "config": self.config}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.db = sqlite3.connect(self.root / "catalog.sqlite3", timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise ValueError(f"Unsupported index schema {version}; migrate before continuing")
        if version == 1:
            self.db.execute("ALTER TABLE sources ADD COLUMN mapping_path TEXT")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
              path TEXT PRIMARY KEY, hash TEXT NOT NULL, size INTEGER, mtime INTEGER,
              config_hash TEXT, indexed_at REAL, mapping_path TEXT);
            CREATE TABLE IF NOT EXISTS products (
              pk INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
              source_path TEXT NOT NULL REFERENCES sources(path) ON DELETE CASCADE,
              sheet TEXT, source_row INTEGER, name TEXT, name_norm TEXT, all_norm TEXT,
              category TEXT, category_origin TEXT, brand TEXT, supplier TEXT,
              has_image INTEGER, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS products_source ON products(source_path);
            CREATE INDEX IF NOT EXISTS products_category ON products(category);
            CREATE INDEX IF NOT EXISTS products_brand ON products(brand);
            CREATE TABLE IF NOT EXISTS prices (
              product_pk INTEGER REFERENCES products(pk) ON DELETE CASCADE,
              field TEXT, label TEXT, amount REAL, PRIMARY KEY(product_pk, field));
            CREATE INDEX IF NOT EXISTS prices_amount ON prices(field, amount, product_pk);
            CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(name_terms, all_terms);
            PRAGMA user_version=2;
        """)

    def close(self):
        self.db.close()

    def _decorate(self, item):
        for rule in self.config.get("source_defaults", []):
            if fnmatch.fnmatch(item["source_file"], rule["match"]):
                for key in ("brand", "supplier"):
                    if not item.get(key) and rule.get(key):
                        item[key] = rule[key]
                        item[f"{key}_origin"] = "config"
        if item.get("category"):
            item["category"] = str(item["category"])
            item.setdefault("category_origin", "source")
        else:
            item["category"], item["category_origin"] = "未分类", "missing"
            for rule in self.config.get("category_rules", []):
                if any(normalize(word) in normalize(item["name"]) for word in rule["keywords"]):
                    item["category"], item["category_origin"] = rule["category"], "rule"
                    break
        for key in ("brand", "supplier"):
            item[key] = str(item.get(key) or "")
        for field, price in item["prices"].items():
            if price["value"] not in (None, "") and parse_price(price["value"]) is None:
                item["issues"].append(f"非数值价格:{price['label']}")
        return item

    def _source_schema(self, source, mapping_path=None):
        schema = dict(self.config)
        for rule in self.config.get("source_schemas", []):
            if fnmatch.fnmatch(Path(source).name, rule["match"]):
                schema.update({key: value for key, value in rule.items() if key != "match"})
        if mapping_path:
            mapping_path = str(Path(mapping_path).resolve())
            schema["mapping"] = json.loads(Path(mapping_path).read_text(encoding="utf-8-sig"))
        signature = hashlib.sha256(json.dumps(
            {"base": self.signature, "schema": schema}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return schema, signature, mapping_path

    def index(self, paths=(), verify_hash=False, rebuild=False, mapping_path=None):
        from extract import read_products
        paths = sorted({Path(p).resolve() for p in paths}, key=str)
        if not paths:
            paths = [Path(row[0]) for row in self.db.execute("SELECT path FROM sources ORDER BY path")]
        if not paths:
            raise ValueError("No sources registered; provide XLSX files or a directory")
        if mapping_path and len(paths) != 1:
            raise ValueError("--map applies to exactly one source workbook")
        started = time.perf_counter()
        result = {"updated": 0, "skipped": 0, "products_read": 0, "skipped_sheets": []}
        missing, unmapped, warnings = {"prices": 0, "details": 0, "images": 0}, {}, Counter()
        with self.db:
            for source in paths:
                if not source.is_file():
                    raise ValueError(f"Source missing: {source}; remove it from index explicitly")
                stat = source.stat()
                old = self.db.execute("SELECT * FROM sources WHERE path=?", (str(source),)).fetchone()
                schema, signature, saved_map = self._source_schema(source, mapping_path or (old["mapping_path"] if old else None))
                unchanged_config = not rebuild and old is not None and old["config_hash"] == signature
                if old and old["mapping_path"] != saved_map:
                    self.db.execute("UPDATE sources SET mapping_path=? WHERE path=?", (saved_map, str(source)))
                if unchanged_config and not verify_hash and old["size"] == stat.st_size and old["mtime"] == stat.st_mtime_ns:
                    result["skipped"] += 1
                    continue
                if unchanged_config and old["hash"] == sha(source):
                    self.db.execute("UPDATE sources SET size=?,mtime=? WHERE path=?", (stat.st_size, stat.st_mtime_ns, str(source)))
                    result["skipped"] += 1
                    continue
                try:
                    items, skipped = read_products(source, self.root / "assets", schema)
                except ValueError as error:
                    raise ValueError(f"{source.name}: {error}") from error
                self._save_source(source, stat, signature, saved_map, items)
                for item in items:
                    for kind, absent in (("prices", all(p["value"] is None for p in item["prices"].values())), ("details", not item["features"]),
                                         ("images", not item["product_image"] and not item["package_image"])):
                        missing[kind] += int(absent)
                    warnings.update(issue.split(":", 1)[0] for issue in item["issues"])
                    if item["unmapped_fields"]:
                        unmapped.setdefault((source.name, item["sheet"]), set()).update(item["unmapped_fields"])
                result["updated"] += 1
                result["products_read"] += len(items)
                result["skipped_sheets"].extend(f"{source.name}/{name}" for name in skipped)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if result["updated"]:
            result["missing_fields"] = missing
            result["warning_counts"] = dict(warnings)
            result["unmapped_group_count"] = len(unmapped)
            result["unmapped_headers"] = [{"source": key[0], "sheet": key[1], "fields": sorted(value)}
                                          for key, value in list(unmapped.items())[:10]]
        return result

    def _delete_source(self, source):
        self.db.execute("DELETE FROM products_fts WHERE rowid IN (SELECT pk FROM products WHERE source_path=?)", (str(source),))
        self.db.execute("DELETE FROM sources WHERE path=?", (str(source),))

    def _save_source(self, source, stat, signature, mapping_path, items):
        """Caller owns the transaction, including the FTS rows."""
        self._delete_source(source)
        self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)", (
            str(source), items[0]["source_hash"], stat.st_size, stat.st_mtime_ns, signature, time.time(), mapping_path))
        for item in items:
            self._insert(self._decorate(item))

    def relocate(self, old_root, new_root, apply=False):
        """Re-extract only moved sources; never patch payload strings or move user files."""
        from extract import read_products
        old_root, new_root = Path(old_root).resolve(), Path(new_root).resolve()
        if old_root == new_root or not new_root.is_dir():
            raise ValueError("Relocation requires distinct roots and an existing destination directory")

        def remap(value):
            path = Path(value).resolve()
            if not path.is_relative_to(old_root):
                return path
            target = (new_root / path.relative_to(old_root)).resolve()
            if not target.is_relative_to(new_root):
                raise ValueError("Relocation target escapes destination root")
            return target

        plans = []
        for old in self.db.execute("SELECT * FROM sources ORDER BY path").fetchall():
            if not Path(old["path"]).is_relative_to(old_root):
                continue
            source = remap(old["path"])
            mapping = remap(old["mapping_path"]) if old["mapping_path"] else None
            if self.db.execute("SELECT 1 FROM sources WHERE path=?", (str(source),)).fetchone():
                raise ValueError(f"Destination already registered: {source}; resolve it before relocating")
            if not source.is_file() or sha(source) != old["hash"]:
                raise ValueError(f"Relocated source missing or hash changed: {source}")
            _, signature, saved_map = self._source_schema(source, mapping)
            if signature != old["config_hash"]:
                raise ValueError(f"Relocated config or mapping changed: {source.name}; restore it before relocating")
            plans.append((old, source, saved_map))
        if not plans:
            raise ValueError("No registered sources under the old root")
        products = 0
        if apply:
            with self.db:
                for old, source, mapping in plans:
                    schema, signature, saved_map = self._source_schema(source, mapping)
                    if signature != old["config_hash"]:
                        raise ValueError(f"Relocated config or mapping changed: {source.name}")
                    stat = source.stat()
                    items, _ = read_products(source, self.root / "assets", schema)
                    if items[0]["source_hash"] != old["hash"]:
                        raise ValueError(f"Relocated source hash changed: {source.name}")
                    self._delete_source(old["path"])
                    self._save_source(source, stat, signature, saved_map, items)
                    products += len(items)
        return {"applied": apply, "sources": len(plans), "products_read": products,
                "ids_changed": bool(apply), "more": len(plans) > 10,
                "items": [{"from": old["path"], "to": str(source), "mapping": mapping}
                          for old, source, mapping in plans[:10]]}

    def _insert(self, item):
        title = normalize(" ".join(str(item.get(key) or "") for key in ("name", "model", "variant")))
        all_text = normalize(" ".join(str(item.get(key) or "") for key in ("name", "model", "variant", "features", "category", "brand", "supplier")))
        pk = self.db.execute("""INSERT INTO products
            (id,source_path,sheet,source_row,name,name_norm,all_norm,category,category_origin,brand,supplier,has_image,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                item["id"], item["source_path"], item["sheet"], item["row"], item["name"], title, all_text,
                item["category"], item["category_origin"], item["brand"], item["supplier"],
                int(bool(item["product_image"] or item["package_image"])), json.dumps(item, ensure_ascii=False))).lastrowid
        price_entries = {}
        labels = Counter(price["label"] for price in item["prices"].values())
        for field, price in item["prices"].items():
            keys = {field}
            if labels[price["label"]] == 1 and price["label"] not in item["prices"]:
                keys.add(price["label"])
            for key in keys:
                price_entries[key] = (price["label"], parse_price(price["value"]))
        self.db.executemany("INSERT INTO prices VALUES (?,?,?,?)",
                            [(pk, field, label, amount) for field, (label, amount) in price_entries.items()])
        self.db.execute("INSERT INTO products_fts(rowid,name_terms,all_terms) VALUES (?,?,?)",
                        (pk, " ".join(grams(title)), " ".join(grams(all_text))))

    def stale_sources(self):
        stale = []
        for source in self.db.execute("SELECT * FROM sources"):
            path = Path(source["path"])
            try:
                stat = path.stat()
                current = (stat.st_size, stat.st_mtime_ns) == (source["size"], source["mtime"])
                _, signature, _ = self._source_schema(path, source["mapping_path"])
                current = current and source["config_hash"] == signature
            except (OSError, ValueError):
                current = False
            if not current:
                stale.append(source["path"])
        return stale

    def _search_constraints(self, constraints):
        if constraints:
            raise ValueError("Additional constraints are not supported by this catalogue")
        return [], []

    def _search_order(self, terms):
        return "bm25(products_fts,8,1),p.id" if terms else "p.source_path,p.sheet,p.source_row"

    def search(self, query="", price_field=None, minimum=None, maximum=None, category=None, source=None,
               brand=None, supplier=None, scope="name", exclude=(), has_image=False,
               limit=10, offset=0, sort="relevance", constraints=None):
        started = time.perf_counter()
        if scope not in {"name", "all"} or sort not in {"relevance", "price-asc", "price-desc"}:
            raise ValueError("Unsupported scope or sort")
        if not 1 <= limit <= 50 or offset < 0:
            raise ValueError("limit must be 1..50 and offset must be nonnegative")
        terms = normalize(query).split()
        if len(query) > 160 or len(terms) > 10:
            raise ValueError("Use at most 10 query terms / 160 characters")
        if (minimum is not None or maximum is not None or sort != "relevance") and not price_field:
            raise ValueError("Explicit price-field required for price filters/sorting")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Minimum price exceeds maximum")
        stale = self.stale_sources()
        joins, where, args = [], ["1=1"], []
        if price_field:
            known = self.db.execute("SELECT 1 FROM prices WHERE field=? LIMIT 1", (price_field,)).fetchone()
            if not known:
                raise ValueError(f"Unknown price-field {price_field}; inspect stats first")
            joins.append("LEFT JOIN prices px ON px.product_pk=p.pk AND px.field=?")
            args.append(price_field)
        text_col, fts_col = ("name_norm", "name_terms") if scope == "name" else ("all_norm", "all_terms")
        if terms:
            joins.append("JOIN products_fts ON products_fts.rowid=p.pk")
            match = " AND ".join(f'"{token}"' for term in terms for token in grams(term, query=True))
            where.append("products_fts MATCH ?")
            args.append(f"{fts_col} : ({match})")
            for term in terms:
                where.append(f"instr(p.{text_col},?)>0")
                args.append(term)
        for term in exclude:
            where.append(f"instr(p.{text_col},?)=0")
            args.append(normalize(term))
        for value, operator in ((minimum, ">="), (maximum, "<=")):
            if value is not None:
                if not math.isfinite(float(value)):
                    raise ValueError("Price bounds must be finite")
                where.append(f"px.amount {operator} ?")
                args.append(float(value))
        if category:
            where.append("(p.category=? OR substr(p.category,1,?)=?)")
            args.extend([category, len(category) + 1, category + "/"])
        if source:
            where.append("p.source_path=?")
            args.append(str(Path(source).resolve()))
        for key, value in (("brand", brand), ("supplier", supplier)):
            if value:
                where.append(f"p.{key}=?")
                args.append(value)
        if has_image:
            where.append("p.has_image=1")
        if stale:
            where.append("p.source_path NOT IN (" + ",".join("?" for _ in stale) + ")")
            args.extend(stale)
        extra_where, extra_args = self._search_constraints(constraints or {})
        where.extend(extra_where)
        args.extend(extra_args)
        base = " FROM products p " + " ".join(joins) + " WHERE " + " AND ".join(where)
        total = self.db.execute("SELECT count(*)" + base, args).fetchone()[0]
        order = self._search_order(terms)
        if sort != "relevance":
            order = "px.amount IS NULL,px.amount " + ("ASC" if sort == "price-asc" else "DESC") + ",p.id"
        rows = self.db.execute("SELECT p.*" + base + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        results = []
        for row in rows:
            item = json.loads(row["payload"])
            result = {"id": item["id"], "name": item["name"], "category": item["category"],
                      "category_origin": item["category_origin"],
                      "source": [item["source_file"], item["sheet"], item["row"]]}
            for key in ("model", "variant", "brand", "supplier"):
                if item.get(key):
                    result[key] = item[key]
            if price_field:
                price = resolve_price(item["prices"], price_field)
                result["price"] = price or {"label": price_field, "value": None}
            else:
                # Canonical roles remain distinct even when source labels repeat.
                result["prices"] = item["prices"]
            if item["issues"]:
                result["warning_count"] = len(item["issues"])
            if scope == "all" and terms and any(term not in row["name_norm"] for term in terms):
                position = max(0, row["all_norm"].find(next(t for t in terms if t not in row["name_norm"])) - 15)
                result["evidence"] = row["all_norm"][position:position + 100]
            results.append(result)
        return {"total": total, "items": results, "offset": offset, "limit": limit,
                "stale_sources": [Path(x).name for x in stale],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}

    def details(self, ids, verify_fresh=False):
        if not ids or len(ids) > 1000 or len(ids) != len(set(ids)):
            raise ValueError("Select 1..1000 distinct product IDs")
        items = []
        for product_id in ids:
            row = self.db.execute("SELECT payload FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown product ID: {product_id}")
            items.append(json.loads(row[0]))
        if verify_fresh:
            check_sources(items)
            stale = set(self.stale_sources())
            if any(item["source_path"] in stale for item in items):
                raise ValueError("Selected index/config is stale; run index again")
        return items

    def stage(self, ids, work_dir, price_fields=None):
        items = self.details(ids, verify_fresh=True)
        if price_fields and (len(price_fields) > 2 or len(set(price_fields)) != len(price_fields)):
            raise ValueError("Choose at most 2 distinct display price fields")
        for item in items:
            for role in ("product_image", "package_image"):
                if item[role] and (not Path(item[role]).is_file() or sha(item[role]) != item[f"{role}_sha256"]):
                    raise ValueError(f"Cached image changed/missing: {item['id']}; reindex with --rebuild")
            prices = item["prices"]
            if price_fields:
                display = []
                for key in price_fields:
                    price = resolve_price(prices, key)
                    if price is None:
                        raise ValueError(f"Selected price field {key} absent or ambiguous for {item['id']}; choose a canonical price role")
                    display.append(price)
                item["display_prices"] = display
            else:
                item["display_prices"] = list(prices.values()) or [{"label": "价格", "value": None}]
            if len(item["display_prices"]) > 2:
                raise ValueError("More than 2 price columns; choose --price-fields explicitly")
            if any(price.get("error") for price in item["display_prices"]):
                raise ValueError(f"Selected price has a spreadsheet error for {item['id']}; repair source or choose another price role")
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "catalog-data.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"selected": len(items)}

    def stats(self):
        price_fields = self.facets("price")
        return {"products": self.db.execute("SELECT count(*) FROM products").fetchone()[0],
                "sources": self.db.execute("SELECT count(*) FROM sources").fetchone()[0],
                "category_count": self.db.execute("SELECT count(DISTINCT category) FROM products").fetchone()[0],
                "categories": self.facets("category")["items"],
                "price_field_count": price_fields["total"],
                "price_fields": price_fields["items"],
                "price_fields_more": price_fields["total"] > price_fields["limit"],
                "stale_sources": [Path(x).name for x in self.stale_sources()]}

    def sources(self, limit=10, offset=0):
        if not 1 <= limit <= 50 or offset < 0:
            raise ValueError("Invalid source pagination")
        stale = set(self.stale_sources())
        rows = self.db.execute("""SELECT s.path,s.mapping_path,count(p.pk) AS products FROM sources s
            LEFT JOIN products p ON p.source_path=s.path GROUP BY s.path ORDER BY s.path LIMIT ? OFFSET ?""", (limit, offset))
        return {"total": self.db.execute("SELECT count(*) FROM sources").fetchone()[0], "offset": offset, "limit": limit,
                "items": [{**dict(row), "stale": row["path"] in stale} for row in rows]}

    def facets(self, field, query="", limit=20, offset=0):
        if field not in {"category", "brand", "supplier", "price"}:
            raise ValueError("Facet field must be category, brand, supplier or price")
        if not 1 <= limit <= 50 or offset < 0 or len(query) > 160:
            raise ValueError("Invalid facet limit/offset/query")
        if field == "price":
            base = " FROM prices WHERE instr(field,?)>0 OR instr(label,?)>0 GROUP BY field,label"
            params = (query, query)
            projection, ordering = "field,label,count(amount) AS numeric_count", "field,label"
        else:
            base = f" FROM products WHERE {field}<>'' AND instr({field},?)>0 GROUP BY {field}"
            params = (query,)
            projection, ordering = f"{field} AS value,count(*) AS count", "count DESC,value"
        total = self.db.execute("SELECT count(*) FROM (SELECT 1" + base + ")", params).fetchone()[0]
        rows = self.db.execute("SELECT " + projection + base + " ORDER BY " + ordering + " LIMIT ? OFFSET ?",
                               (*params, limit, offset))
        return {"field": field, "total": total, "items": [dict(row) for row in rows], "offset": offset, "limit": limit}

    def remove_source(self, path):
        with self.db:
            self._delete_source(Path(path).resolve())
