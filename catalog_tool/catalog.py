"""Compact assistant-facing commands for a local XLSX product catalogue."""

import argparse
import json
import sqlite3
import sys
from zipfile import BadZipFile
from pathlib import Path

from catalog_store import Catalog

ROOT = Path(__file__).resolve().parents[1]


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
    search = commands.add_parser("search", help="Bounded results; spaces mean AND; name/model only by default")
    search.add_argument("--query", default="")
    search.add_argument("--price-field")
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
    stage = commands.add_parser("stage", help="Internal step for PPT generation; validates source/image hashes")
    stage.add_argument("--ids", nargs="+", required=True)
    stage.add_argument("--work-dir", type=Path, required=True)
    stage.add_argument("--price-fields", nargs="+")
    stage_source = commands.add_parser("stage-source", help="Internal step: stage all products in one indexed source")
    stage_source.add_argument("--input", type=Path, required=True)
    stage_source.add_argument("--work-dir", type=Path, required=True)
    stage_source.add_argument("--price-fields", nargs="+")
    commands.add_parser("stats", help="Counts, categories and exact available price fields")
    facets = commands.add_parser("facets", help="Find categories/brands/suppliers without dumping all values")
    facets.add_argument("--field", choices=["category", "brand", "supplier"], default="category")
    facets.add_argument("--query", default="")
    facets.add_argument("--limit", type=int, default=20)
    facets.add_argument("--offset", type=int, default=0)
    remove = commands.add_parser("remove-source", help="Unregister one source; never deletes its workbook")
    remove.add_argument("path")
    args = parser.parse_args(argv)
    store = None
    try:
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
            result = store.index(paths, verify_hash=args.verify_hash, rebuild=args.rebuild)
        elif args.command == "search":
            keys = ("query", "price_field", "minimum", "maximum", "category", "brand", "supplier",
                    "scope", "exclude", "has_image", "limit", "offset", "sort")
            result = store.search(**{key: getattr(args, key) for key in keys})
        elif args.command == "show":
            if len(args.ids) > 10:
                raise ValueError("show accepts at most 10 IDs; read only shortlisted products")
            items = store.details(args.ids, verify_fresh=True)
            result = [{key: item[key] for key in (
                "id", "name", "model", "prices", "features", "category", "category_origin", "brand", "supplier",
                "source_file", "source_path", "sheet", "row", "source_cells", "raw_fields", "issues")} for item in items]
        elif args.command == "stage":
            result = store.stage(args.ids, args.work_dir, args.price_fields)
        elif args.command == "stage-source":
            ids = [row[0] for row in store.db.execute(
                "SELECT id FROM products WHERE source_path=? ORDER BY sheet,source_row", (str(args.input.resolve()),))]
            result = store.stage(ids, args.work_dir, args.price_fields)
        elif args.command == "stats":
            result = store.stats()
        elif args.command == "facets":
            result = store.facets(args.field, args.query, args.limit, args.offset)
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
