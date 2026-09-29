"""Codex-driven product pool: add, inspect, import, tag, search, choose, and export."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from catalog import DETAIL_FIELDS, EXTRA_FIELDS, view_details
from pool_store import Pool, encoded
from pool_selection import Selections

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=ROOT / "data/product-pool")
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="Snapshot a file; identical bytes never duplicate products")
    add.add_argument("input", type=Path)
    add.add_argument("--map", type=Path)
    listing = commands.add_parser("files", help="Page registered files, import status and counts")
    listing.add_argument("--limit", type=int, default=10)
    listing.add_argument("--offset", type=int, default=0)
    inspect = commands.add_parser("inspect", help="Bounded source evidence; use refs to import individual records")
    inspect.add_argument("--file", required=True)
    inspect.add_argument("--page", type=int)
    inspect.add_argument("--ref")
    inspect.add_argument("--offset", type=int, default=0)
    inspect.add_argument("--limit", type=int, default=20)
    inspect.add_argument("--max-chars", type=int, default=240)
    inspect.add_argument("--text-offset", type=int, default=0)
    render = commands.add_parser("render", help="Render a PDF page for Codex visual reading")
    render.add_argument("--file", required=True)
    render.add_argument("--page", type=int, required=True)
    observe = commands.add_parser("observe", help="Record an explicit visual transcription, never claim native verification")
    observe.add_argument("--file", required=True)
    observe.add_argument("--image-ref", required=True)
    observe.add_argument("--text-file", type=Path, required=True)
    observe.add_argument("--reviewer", required=True)
    importing = commands.add_parser("import", help="Append evidence-backed records from a local JSON array")
    importing.add_argument("--file", required=True)
    importing.add_argument("--records", type=Path, required=True)
    annotate = commands.add_parser("annotate", help="Add transparent scenario/audience/material/etc tags with evidence")
    annotate.add_argument("--records", type=Path, required=True)
    search = commands.add_parser("search", help="Bounded factual AND query plus price/category/tag filters")
    search.add_argument("--query", default="")
    search.add_argument("--price-field")
    search.add_argument("--min-price", type=float, dest="minimum")
    search.add_argument("--max-price", type=float, dest="maximum")
    for key in ("category", "brand", "supplier"):
        search.add_argument("--" + key)
    search.add_argument("--scope", choices=["name", "all"], default="name")
    search.add_argument("--exclude", action="append", default=[])
    search.add_argument("--has-image", action="store_true")
    search.add_argument("--sort", choices=["relevance", "price-asc", "price-desc"], default="relevance")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--tag", action="append", default=[])
    search.add_argument("--tag-mode", choices=["all", "any"], default="all")
    search.add_argument("--tag-origin", choices=["source", "inferred"])
    search.add_argument("--file")
    show = commands.add_parser("show")
    show.add_argument("--ids", nargs="+", required=True)
    show.add_argument("--fields", nargs="+", choices=DETAIL_FIELDS + EXTRA_FIELDS)
    show.add_argument("--raw-fields", nargs="+", default=[])
    show.add_argument("--max-chars", type=int, default=400)
    show.add_argument("--text-offset", type=int, default=0)
    commands.add_parser("stats")
    facets = commands.add_parser("facets")
    facets.add_argument("--field", choices=["category", "brand", "supplier", "price", "tag"], default="tag")
    facets.add_argument("--kind")
    facets.add_argument("--query", default="")
    facets.add_argument("--limit", type=int, default=20)
    facets.add_argument("--offset", type=int, default=0)
    choose = commands.add_parser("choose", help="Freeze candidates/prices and write selection HTML")
    choose.add_argument("--ids", nargs="+", required=True)
    choose.add_argument("--price-fields", nargs="+", required=True)
    choose.add_argument("--title", default="请选择产品")
    for name in ("selection", "open", "close", "serve"):
        commands.add_parser(name).add_argument("--session", required=True)
    stage = commands.add_parser("stage", help="Internal: source-verified data for the shared PPT builder")
    stage.add_argument("--ids", nargs="+", required=True)
    stage.add_argument("--work-dir", type=Path, required=True)
    stage.add_argument("--price-fields", nargs="+")
    ppt = commands.add_parser("ppt", help="Export exactly the user's selected snapshot and displayed prices")
    ppt.add_argument("--session", required=True)
    for key in ("output", "style", "runtime-root", "skill-dir"):
        ppt.add_argument("--" + key, type=Path)
    args = parser.parse_args(argv)
    pool = None
    try:
        if args.command == "serve":
            from pool_server import serve
            serve(args.index_dir, args.session)
            return 0
        config_path = args.config or ROOT / "catalog.local.json"
        if args.config and not args.config.is_file():
            raise ValueError("Explicit config file missing")
        config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
        pool = Pool(args.index_dir, config)
        if args.command == "add":
            result = pool.add(args.input, args.map)
        elif args.command == "files":
            result = pool.files(args.limit, args.offset)
        elif args.command == "inspect":
            from pool_documents import inspect_evidence
            if args.text_offset < 0:
                raise ValueError("Negative text offset")
            entries = pool.evidence(args.file)
            if args.ref:
                entries = [e for e in entries if e["id"] == args.ref]
                if not entries:
                    raise ValueError("Unknown evidence ref")
            if args.text_offset:
                if not args.ref:
                    raise ValueError("text-offset requires one --ref")
                entries = [{**e, "text": e.get("text", "")[args.text_offset:], "text_offset": args.text_offset} for e in entries]
            result = inspect_evidence(entries, args.page, args.offset, args.limit, args.max_chars)
        elif args.command == "render":
            result = pool.preview(args.file, args.page)
        elif args.command == "observe":
            result = pool.observe(args.file, args.image_ref, args.text_file.read_text(encoding="utf-8-sig"), args.reviewer)
        elif args.command == "import":
            result = pool.import_records(args.file, json.loads(args.records.read_text(encoding="utf-8-sig")))
        elif args.command == "annotate":
            result = pool.annotate(json.loads(args.records.read_text(encoding="utf-8-sig")))
        elif args.command == "search":
            keys = ("query", "price_field", "minimum", "maximum", "category", "brand", "supplier", "scope", "exclude", "has_image", "limit", "offset", "sort")
            result = pool.search(**{k: getattr(args, k) for k in keys}, constraints={"tags": args.tag, "tag_mode": args.tag_mode, "tag_origin": args.tag_origin, "file_id": args.file})
        elif args.command == "show":
            if len(args.ids) > 10:
                raise ValueError("show accepts at most 10 IDs")
            items = pool.details(args.ids, verify_fresh=True)
            result = view_details(items, args.fields, args.raw_fields, args.max_chars, args.text_offset)
            for compact, item in zip(result, items):
                compact["tags"] = item["tags"][:10]
        elif args.command == "facets":
            result = (pool.tag_facets(args.kind, args.query, args.limit, args.offset) if args.field == "tag"
                      else pool.facets(args.field, args.query, args.limit, args.offset))
        elif args.command == "stats":
            result = pool.stats()
            result["files"] = pool.files(1)["total"]
            result["tags"] = pool.tag_facets(limit=1)["total"]
            result["tagged_products"] = pool.db.execute("SELECT count(DISTINCT product_id) FROM pool_tags").fetchone()[0]
        elif args.command == "choose":
            result = Selections(pool).create(args.ids, args.price_fields, args.title)
        elif args.command == "selection":
            result = Selections(pool).state(args.session)
        elif args.command == "open":
            from pool_server import open_session
            result = open_session(args.index_dir, args.session)
        elif args.command == "close":
            Selections(pool).session(args.session)
            with pool.db:
                pool.db.execute("UPDATE pool_sessions SET state='closed',revision=revision+1 WHERE id=?", (args.session,))
            result = {"closed": args.session}
        elif args.command == "stage":
            result = pool.stage(args.ids, args.work_dir, args.price_fields)
        elif args.command == "ppt":
            from present import run
            state = Selections(pool).seal(args.session)
            args.ids, args.price_fields = state["selected_ids"], state["price_fields"]
            args.input = args.map = None
            pool.close()
            pool = None
            return run(args, catalog_script=Path(__file__))
        print(encoded(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(encoded({"error": str(error)}), file=sys.stderr)
        return 2
    finally:
        if pool:
            pool.close()


if __name__ == "__main__":
    sys.exit(main())
