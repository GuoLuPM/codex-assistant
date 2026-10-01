"""Shared command executor. CLI and workspace consume the same parser and facts."""
import json
from pathlib import Path
from catalog import DETAIL_FIELDS, EXTRA_FIELDS, view_details
from pool_store import Pool, encoded
from pool_selection import Selections
from pool_owner import pool_lock, operation, ensure_receipts

ROOT = Path(__file__).resolve().parents[1]


def execute(args, operation_id=None):
    config_path = args.config or ROOT / "catalog.local.json"
    if args.config and not args.config.is_file():
        raise ValueError("Explicit config file missing")
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
    with pool_lock(args.index_dir):
        pool = Pool(args.index_dir, config)
        try:
            Selections(pool)  # schema initialization precedes the atomic effect
            if args.command == "ppt":
                return Selections(pool).seal(args.session, operation_id=operation_id)
            if operation_id:
                payload = {k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()}
                return operation(pool.db, operation_id, payload, lambda: execute_namespace(pool, args))
            return execute_namespace(pool, args)
        finally:
            pool.close()


def execute_namespace(pool, args):
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
    return result
