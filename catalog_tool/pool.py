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
            if result.get('products_added'):
                result['normalization'] = pool.derive(file_id=result['file_id'])
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
            if result.get('added'):
                result['normalization'] = pool.derive(file_id=args.file)
        elif args.command == "annotate":
            result = pool.annotate(json.loads(args.records.read_text(encoding="utf-8-sig")))
        elif args.command in ('enrich', 'vocabulary', 'source-update', 'link', 'offer-terms'):
            method = {'enrich': pool.enrich, 'vocabulary': pool.vocabulary, 'source-update': pool.update_sources,
                      'link': pool.link_products, 'offer-terms': pool.set_offer_terms}[args.command]
            result = method(json.loads(args.records.read_text(encoding='utf-8-sig')))
        elif args.command == 'derive':
            result = pool.derive(args.ids, args.file)
        elif args.command == 'quality':
            result = pool.quality(args.price_field)
        elif args.command == 'review-queue':
            result = pool.review_queue(field=args.field, limit=args.limit, offset=args.offset)
        elif args.command == 'retrieve':
            result = pool.retrieve(json.loads(args.plan.read_text(encoding='utf-8-sig')))
        elif args.command == 'history':
            result = pool.meta.history(args.kind, args.id, args.event, args.limit, args.offset, args.max_chars, args.text_offset)
        elif args.command == "search":
            keys = ("query", "price_field", "minimum", "maximum", "category", "brand", "supplier", "scope", "exclude", "has_image", "limit", "offset", "sort")
            result = pool.search(**{k: getattr(args, k) for k in keys}, constraints={"tags": args.tag, "tag_mode": args.tag_mode, "tag_origin": args.tag_origin, "file_id": args.file,
                'latest': args.latest, 'include_history': args.include_history, 'series': args.series, 'product_group': args.group,
                'exclude_categories': args.exclude_category, 'price_labels': args.price_label})
        elif args.command == "show":
            if len(args.ids) > 10:
                raise ValueError("show accepts at most 10 IDs")
            items = pool.details(args.ids, verify_fresh=True)
            result = view_details(items, args.fields, args.raw_fields, args.max_chars, args.text_offset)
            for compact, item in zip(result, items):
                compact["tags"] = item["tags"][:10]
                if args.metadata:
                    profile = item['metadata']
                    fields = args.metadata_field or list(profile['facts'])[:8]
                    if len(fields) > 8 or set(fields) - set(profile['facts']):
                        raise ValueError('Request at most eight existing metadata fields')
                    compact['metadata'] = {'revision': profile['revision'], 'fact_count': len(profile['facts']),
                        'field_names': list(profile['facts']), 'facts': {field: {k: v[:args.max_chars] if isinstance(v, str) else v
                            for k, v in profile['facts'][field].items()} for field in fields}}
                    compact['quote_source'] = {k: item['quote_source'][k] for k in ('revision', 'series', 'issued_on', 'status', 'superseded_by')}
                    compact['product_group'] = item['product_group']
                    compact['offer_terms'] = {field: {'revision': terms['revision'], 'terms': {k: v['value'] for k, v in terms['terms'].items()}}
                                              for field, terms in item['offer_terms'].items()}
                else:
                    compact['metadata_revision'] = item['metadata']['revision']
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
        elif args.command == "sessions":
            result = Selections(pool).recent(args.query, args.state, args.limit, args.offset)
        elif args.command == "rename":
            result = Selections(pool).rename(args.session, args.title)
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
