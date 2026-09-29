"""Compact assistant-facing commands for a local XLSX product catalogue."""

import argparse
import json
import sqlite3
import sys
from zipfile import BadZipFile
from pathlib import Path

from catalog_store import Catalog

ROOT = Path(__file__).resolve().parents[1]
DETAIL_FIELDS = ("name", "model", "variant", "prices", "features", "category", "category_origin", "brand", "supplier",
                 "source_file", "sheet", "row", "end_row", "issues")
EXTRA_FIELDS = ("source_path", "field_cells", "source_cells", "images", "raw_field_names", "unmapped_fields")


def view_details(items, fields=None, raw_fields=(), max_chars=400, text_offset=0):
    """Keep selected evidence bounded; full records go straight to the PPT builder."""
    fields = fields or DETAIL_FIELDS
    if set(fields) - set(DETAIL_FIELDS + EXTRA_FIELDS) or len(raw_fields) > 10:
        raise ValueError("Unknown detail field or too many raw fields (maximum 10)")
    if not 20 <= max_chars <= 4000 or text_offset < 0:
        raise ValueError("Invalid detail text budget")
    result = []
    for item in items:
        truncated = {}

        def bounded(value, key):
            if isinstance(value, str) and (len(value) > max_chars or text_offset and (key == "features" or key.startswith("raw_fields."))):
                start = text_offset if key == "features" or key.startswith("raw_fields.") else 0
                truncated[key] = {"total_chars": len(value), "offset": start, "more": start + max_chars < len(value)}
                return value[start:start + max_chars]
            if isinstance(value, dict):
                return {k: bounded(v, f"{key}.{k}") for k, v in value.items()}
            if isinstance(value, list):
                return [bounded(v, f"{key}.{i}") for i, v in enumerate(value)]
            return value

        entry = {"id": item["id"]}
        for key in fields:
            value = list(item["raw_fields"]) if key == "raw_field_names" else item.get(key)
            if key == "images" and len(value or []) > 8:
                entry["image_count"] = len(value)
                value = value[:8]
            entry[key] = bounded(value, key)
        if raw_fields:
            absent = set(raw_fields) - set(item["raw_fields"])
            if absent:
                raise ValueError(f"Raw fields absent for {item['id']}: {sorted(absent)}; request raw_field_names first")
            entry["raw_fields"] = {key: bounded(item["raw_fields"][key], f"raw_fields.{key}") for key in raw_fields}
        if truncated:
            entry["text_windows"] = truncated
        result.append(entry)
    return result


def discover(paths):
    result = set()
    ignored = {".git", "node_modules", "outputs"}
    for value in paths:
        path = Path(value).resolve()
        if not path.exists():
            raise ValueError(f"Source path not found: {path}")
        if path.is_file():
            candidates = [path]
        else:
            # Prune internal folders without traversing dependency junctions.
            import os
            candidates = []
            for folder, directories, files in os.walk(path, followlinks=False):
                directories[:] = [name for name in directories if name not in ignored
                                  and not name.startswith(".catalog") and not (Path(folder) / name).is_symlink()]
                candidates.extend(Path(folder) / name for name in files if name.lower().endswith(".xlsx"))
        for candidate in candidates:
            if candidate.suffix.lower() != ".xlsx":
                raise ValueError(f"Expected .xlsx source: {candidate.name}")
            if not candidate.name.startswith("~$"):
                result.add(candidate)
    return sorted(result, key=str)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=ROOT / ".catalog-index")
    parser.add_argument("--config", type=Path, help="Local schema/category config; auto-detects catalog.local.json")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="Incrementally import files/directories, or refresh registered sources")
    index.add_argument("paths", nargs="*")
    index.add_argument("--verify-hash", action="store_true")
    index.add_argument("--rebuild", action="store_true", help="Reparse sources and repair cached images")
    index.add_argument("--map", type=Path, dest="mapping_path", help="Reviewed source-coordinate mapping, registered for reuse")
    inspect = commands.add_parser("inspect", help="Read bounded sheet metadata or a cell range before mapping")
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--sheet")
    inspect.add_argument("--range", default="A1:P8", dest="cell_range")
    inspect.add_argument("--limit", type=int, default=10)
    inspect.add_argument("--offset", type=int, default=0)
    inspect.add_argument("--max-cells", type=int, default=80)
    inspect.add_argument("--max-chars", type=int, default=100)
    search = commands.add_parser("search", help="Bounded results; spaces mean AND; name/model only by default")
    search.add_argument("--query", default="")
    search.add_argument("--price-field")
    search.add_argument("--source", type=Path, help="Restrict to one registered source path")
    search.add_argument("--min-price", type=float, dest="minimum")
    search.add_argument("--max-price", type=float, dest="maximum")
    for field in ("category", "brand", "supplier"):
        search.add_argument("--" + field)
    search.add_argument("--scope", choices=["name", "all"], default="name")
    search.add_argument("--exclude", action="append", default=[])
    search.add_argument("--has-image", action="store_true")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--sort", choices=["relevance", "price-asc", "price-desc"], default="relevance")
    show = commands.add_parser("show", help="Source-verified details for up to 10 selected IDs")
    show.add_argument("--ids", nargs="+", required=True)
    show.add_argument("--fields", nargs="+", choices=DETAIL_FIELDS + EXTRA_FIELDS)
    show.add_argument("--raw-fields", nargs="+", default=[])
    show.add_argument("--max-chars", type=int, default=400)
    show.add_argument("--text-offset", type=int, default=0)
    stage = commands.add_parser("stage", help="Internal step for PPT generation; validates source/image hashes")
    stage.add_argument("--ids", nargs="+", required=True)
    stage.add_argument("--work-dir", type=Path, required=True)
    stage.add_argument("--price-fields", nargs="+")
    stage_source = commands.add_parser("stage-source", help="Internal step: stage all products in one indexed source")
    stage_source.add_argument("--input", type=Path, required=True)
    stage_source.add_argument("--work-dir", type=Path, required=True)
    stage_source.add_argument("--price-fields", nargs="+")
    commands.add_parser("stats", help="Counts, categories and exact available price fields")
    sources = commands.add_parser("sources", help="Page registered source paths, mappings and freshness")
    sources.add_argument("--limit", type=int, default=10)
    sources.add_argument("--offset", type=int, default=0)
    facets = commands.add_parser("facets", help="Find categories/brands/suppliers without dumping all values")
    facets.add_argument("--field", choices=["category", "brand", "supplier", "price"], default="category")
    facets.add_argument("--query", default="")
    facets.add_argument("--limit", type=int, default=20)
    facets.add_argument("--offset", type=int, default=0)
    remove = commands.add_parser("remove-source", help="Unregister one source; never deletes its workbook")
    remove.add_argument("path")
    relocate = commands.add_parser("relocate", help="Validate moved sources/maps; use --apply to update registrations atomically")
    relocate.add_argument("--from", type=Path, dest="old_root", required=True)
    relocate.add_argument("--to", type=Path, dest="new_root", default=ROOT)
    relocate.add_argument("--apply", action="store_true")
    from present import add_parser, run as present
    add_parser(commands)
    args = parser.parse_args(argv)
    store = None
    try:
        if args.command == "ppt":
            return present(args)
        if args.command == "inspect":
            from inspect_source import inspect_source
            result = inspect_source(args.source, args.sheet, args.cell_range, args.limit, args.offset, args.max_cells, args.max_chars)
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0
        config_path = args.config or ROOT / "catalog.local.json"
        if args.config and not config_path.is_file():
            raise ValueError(f"Config missing: {config_path}")
        if not config_path.is_file():
            config_path = Path(__file__).with_name("catalog.example.json")
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        store = Catalog(args.index_dir, config)
        if args.command == "index":
            paths = discover(args.paths)
            if args.paths and not paths:
                raise ValueError("No XLSX files found in the supplied paths")
            result = store.index(paths, verify_hash=args.verify_hash, rebuild=args.rebuild, mapping_path=args.mapping_path)
        elif args.command == "search":
            keys = ("query", "price_field", "minimum", "maximum", "category", "brand", "supplier", "source",
                    "scope", "exclude", "has_image", "limit", "offset", "sort")
            result = store.search(**{key: getattr(args, key) for key in keys})
        elif args.command == "show":
            if len(args.ids) > 10:
                raise ValueError("show accepts at most 10 IDs; read only shortlisted products")
            items = store.details(args.ids, verify_fresh=True)
            result = view_details(items, args.fields, args.raw_fields, args.max_chars, args.text_offset)
        elif args.command == "stage":
            result = store.stage(args.ids, args.work_dir, args.price_fields)
        elif args.command == "stage-source":
            ids = [row[0] for row in store.db.execute(
                "SELECT id FROM products WHERE source_path=? ORDER BY sheet,source_row", (str(args.input.resolve()),))]
            result = store.stage(ids, args.work_dir, args.price_fields)
        elif args.command == "stats":
            result = store.stats()
        elif args.command == "sources":
            result = store.sources(args.limit, args.offset)
        elif args.command == "facets":
            result = store.facets(args.field, args.query, args.limit, args.offset)
        elif args.command == "relocate":
            result = store.relocate(args.old_root, args.new_root, args.apply)
        else:
            store.remove_source(args.path)
            result = {"removed": Path(args.path).name}
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ValueError, OSError, sqlite3.Error, BadZipFile) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
