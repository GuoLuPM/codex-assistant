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


def make_parser():
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
    for name in ('enrich', 'vocabulary', 'source-update', 'link', 'offer-terms'):
        commands.add_parser(name).add_argument('--records', type=Path, required=True)
    derive = commands.add_parser('derive', help='Extract only explicit labeled metadata; ambiguous facts stay unknown')
    target = derive.add_mutually_exclusive_group()
    target.add_argument('--ids', nargs='+')
    target.add_argument('--file')
    quality = commands.add_parser('quality', help='Missing metadata, unparseable prices and unknown source versions')
    quality.add_argument('--price-field')
    queue = commands.add_parser('review-queue', help='Bounded missing metadata queue for Codex')
    queue.add_argument('--field', choices=['brand', 'category', 'supplier'], default='category')
    queue.add_argument('--limit', type=int, default=20)
    queue.add_argument('--offset', type=int, default=0)
    retrieval = commands.add_parser('retrieve', help='Run a bounded multi-lane plan, preserving all shared hard filters')
    retrieval.add_argument('--plan', type=Path, required=True)
    history = commands.add_parser('history', help='Audit summaries; request one event for bounded evidence text')
    history.add_argument('--kind', choices=['product', 'source', 'offer', 'group', 'vocabulary'])
    history.add_argument('--id')
    history.add_argument('--event', type=int)
    history.add_argument('--limit', type=int, default=10)
    history.add_argument('--offset', type=int, default=0)
    history.add_argument('--max-chars', type=int, default=1000)
    history.add_argument('--text-offset', type=int, default=0)
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
    search.add_argument('--latest', action='store_true')
    search.add_argument('--include-history', action='store_true')
    search.add_argument('--series')
    search.add_argument('--group', help='Page all source offers for a reviewed product group')
    search.add_argument('--exclude-category', action='append', default=[])
    search.add_argument('--price-label', action='append', default=[])
    show = commands.add_parser("show")
    show.add_argument("--ids", nargs="+", required=True)
    show.add_argument("--fields", nargs="+", choices=DETAIL_FIELDS + EXTRA_FIELDS)
    show.add_argument("--raw-fields", nargs="+", default=[])
    show.add_argument("--max-chars", type=int, default=400)
    show.add_argument("--text-offset", type=int, default=0)
    show.add_argument('--metadata', action='store_true', help='Include evidence-backed search metadata and quote context')
    show.add_argument('--metadata-field', action='append', default=[], help='Project at most eight search facts with --metadata')
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
    sessions = commands.add_parser("sessions", help="Find previous selections by title; bounded summaries without access tokens")
    sessions.add_argument("--query", default="")
    sessions.add_argument("--state", choices=["open", "sealed", "closed"])
    sessions.add_argument("--limit", type=int, default=10)
    sessions.add_argument("--offset", type=int, default=0)
    for name in ("selection", "open", "close", "serve"):
        commands.add_parser(name).add_argument("--session", required=True)
    rename = commands.add_parser("rename", help="Change a selection title without changing candidates or choices")
    rename.add_argument("--session", required=True)
    rename.add_argument("--title", required=True)
    stage = commands.add_parser("stage", help="Internal: source-verified data for the shared PPT builder")
    stage.add_argument("--ids", nargs="+", required=True)
    stage.add_argument("--work-dir", type=Path, required=True)
    stage.add_argument("--price-fields", nargs="+")
    ppt = commands.add_parser("ppt", help="Export exactly the user's selected snapshot and displayed prices")
    ppt.add_argument("--session", required=True)
    for key in ("output", "style", "runtime-root", "skill-dir"):
        ppt.add_argument("--" + key, type=Path)
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from pool_server import serve
            serve(args.index_dir, args.session)
            return 0
        from pool_commands import execute
        result = execute(args)
        if args.command == "ppt":
            from present import run
            args.ids, args.price_fields = result["selected_ids"], result["price_fields"]
            args.input = args.map = None
            return run(args, catalog_script=Path(__file__))
        print(encoded(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        print(encoded({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
