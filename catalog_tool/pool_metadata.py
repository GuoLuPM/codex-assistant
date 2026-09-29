"""Evidence-backed search overlays; immutable source payloads remain the authority."""

import hashlib
import json
import math
import re
import time

from catalog_store import normalize


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


UNITS = {
    'ml': ('ml', 1), '毫升': ('ml', 1), 'l': ('ml', 1000), '升': ('ml', 1000),
    'g': ('g', 1), '克': ('g', 1), 'kg': ('g', 1000), '千克': ('g', 1000),
    'mm': ('mm', 1), '毫米': ('mm', 1), 'cm': ('mm', 10), '厘米': ('mm', 10), 'm': ('mm', 1000), '米': ('mm', 1000),
    'w': ('W', 1), '瓦': ('W', 1), 'kw': ('W', 1000), '千瓦': ('W', 1000),
    'mah': ('mAh', 1), '毫安时': ('mAh', 1), 'ah': ('mAh', 1000), '安时': ('mAh', 1000),
    'db': ('dB', 1), '分贝': ('dB', 1), 'h': ('h', 1), '小时': ('h', 1), 'min': ('h', 1 / 60), '分钟': ('h', 1 / 60),
}
QUANTITY = re.compile(r'(\d+(?:\.\d+)?)\s*(' + '|'.join(sorted(UNITS, key=len, reverse=True)) + r')(?![a-z])', re.I)


def quantity(value, unit):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('Attribute quantity must be a finite nonnegative number')
    key = normalize(unit)
    if key not in UNITS:
        raise ValueError('Unsupported unit; retain raw facts instead of guessing conversion')
    canonical, multiplier = UNITS[key]
    number = value * multiplier
    if not math.isfinite(number):
        raise ValueError('Attribute quantity overflow')
    return number, canonical


def own_text(item):
    fields = ['name', 'model', 'variant', 'features']
    for field in ('brand', 'supplier', 'category'):
        if item.get(field + '_origin', 'source') in ('source', 'sheet'):
            fields.append(field)
    # Search quotes in values, never in JSON keys/escapes or a derived category.
    values = [str(item.get(key) or '') for key in fields]
    def visit(value):
        if isinstance(value, dict):
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
        elif value is not None:
            values.append(str(value))
    visit(item.get('raw_fields', {}))
    return '\n'.join(values)


def ensure_schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS pool_profiles (
        product_id TEXT PRIMARY KEY REFERENCES products(id), revision INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS pool_metadata (
        product_id TEXT NOT NULL REFERENCES products(id), field TEXT NOT NULL, value TEXT NOT NULL,
        number REAL, unit TEXT, origin TEXT NOT NULL CHECK(origin IN ('source','inferred')),
        quote TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(product_id,field));
      CREATE INDEX IF NOT EXISTS pool_metadata_text ON pool_metadata(field,value,product_id);
      CREATE INDEX IF NOT EXISTS pool_metadata_number ON pool_metadata(field,unit,number,product_id);
      CREATE TABLE IF NOT EXISTS pool_events (
        id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL,
        event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL);
      CREATE INDEX IF NOT EXISTS pool_events_entity ON pool_events(entity_type,entity_id,revision);
      CREATE TABLE IF NOT EXISTS pool_vocabulary (
        kind TEXT NOT NULL, term TEXT NOT NULL, group_key TEXT NOT NULL, display TEXT NOT NULL,
        reason TEXT NOT NULL, PRIMARY KEY(kind,term));
      CREATE INDEX IF NOT EXISTS pool_vocabulary_group ON pool_vocabulary(kind,group_key);
    ''')


def event(db, kind, key, revision, action, payload):
    db.execute('INSERT INTO pool_events(entity_type,entity_id,revision,event_type,payload,created_at) VALUES (?,?,?,?,?,?)',
               (kind, key, revision, action, packed(payload), time.time()))


class Metadata:
    def __init__(self, pool):
        self.pool, self.db = pool, pool.db

    def profile(self, product_id):
        row = self.db.execute('SELECT revision FROM pool_profiles WHERE product_id=?', (product_id,)).fetchone()
        facts = {}
        for record in self.db.execute('SELECT * FROM pool_metadata WHERE product_id=? ORDER BY field', (product_id,)):
            fact = {k: record[k] for k in ('value', 'number', 'unit', 'origin', 'quote', 'reason')}
            if fact['number'] is not None:
                fact['value'] = fact['number']
            facts[record['field']] = fact
        return {'revision': row[0] if row else 0, 'facts': facts}

    def clean_fact(self, fact, item):
        if not isinstance(fact, dict) or set(fact) - {'field', 'value', 'unit', 'origin', 'quote', 'reason'}:
            raise ValueError('Unknown metadata keys')
        field = fact.get('field', '')
        if not isinstance(field, str) or not re.fullmatch(r'(?:brand|category|supplier|attr\.[a-z][a-z0-9_]{0,39})', field):
            raise ValueError('Metadata field must be brand/category/supplier or attr.name')
        quote, reason, origin = fact.get('quote'), fact.get('reason'), fact.get('origin')
        if not isinstance(quote, str) or not 1 <= len(quote) <= 1000 or quote not in own_text(item):
            raise ValueError("Metadata quote must occur in this product's own source facts")
        if origin not in ('source', 'inferred') or not isinstance(reason, str) or not 1 <= len(reason) <= 500:
            raise ValueError('Metadata needs explicit origin and reason')
        value = fact.get('value')
        number = unit = None
        if 'value' in fact and value is None:
            if 'unit' in fact: raise ValueError('Clearing a fact does not accept a unit')
            return dict(field=field, value=None, number=None, unit=None, origin=origin, quote=quote, reason=reason)
        if 'unit' in fact:
            if not field.startswith('attr.') or origin != 'source':
                raise ValueError('Measured attributes require source origin')
            number, unit = quantity(value, fact['unit'])
            matches = [quantity(float(m[1]), m[2]) for m in QUANTITY.finditer(normalize(quote))]
            if not any(u == unit and math.isclose(n, number, rel_tol=1e-9, abs_tol=1e-9) for n, u in matches):
                raise ValueError('Attribute quantity must occur in quoted evidence; no computed/guessed values')
            value = str(number)
        elif not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
            raise ValueError('Text metadata needs a bounded nonempty string')
        else:
            value = value.strip()
            if (origin == 'source' or field != 'category') and normalize(value) not in normalize(quote):
                raise ValueError('Factual metadata value must occur in its quote; only category interpretation may differ')
        return dict(field=field, value=value, number=number, unit=unit, origin=origin, quote=quote, reason=reason)

    def enrich(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError('Enrich accepts 1..100 product entries')
        seen, checked = set(), set()
        updated = unchanged = 0
        invalidated_groups = set()
        with self.db:
            for record in records:
                if not isinstance(record, dict) or set(record) != {'id', 'revision', 'facts'} or type(record['revision']) is not int:
                    raise ValueError('Metadata entry requires id/revision/facts')
                pid = record['id']
                if not isinstance(pid, str) or pid in seen:
                    raise ValueError('Duplicate/invalid metadata product ID')
                seen.add(pid)
                row = self.db.execute('SELECT payload FROM products WHERE id=?', (pid,)).fetchone()
                if not row:
                    raise ValueError('Unknown metadata product ID')
                item = json.loads(row[0])
                if item['source_path'] not in checked:
                    self.pool.source(item['source_path'])
                    checked.add(item['source_path'])
                if not isinstance(record['facts'], list) or not 1 <= len(record['facts']) <= 20:
                    raise ValueError('Provide 1..20 metadata facts per product')
                facts = [self.clean_fact(f, item) for f in record['facts']]
                if len({f['field'] for f in facts}) != len(facts):
                    raise ValueError('Duplicate metadata field')
                old = self.profile(pid)
                before = {r['field']: dict(r) for r in self.db.execute('SELECT field,value,number,unit,origin,quote,reason FROM pool_metadata WHERE product_id=?', (pid,))}
                changes = [f for f in facts if (f['field'] in before if f['value'] is None else before.get(f['field']) != f)]
                if not changes:
                    unchanged += 1
                    continue
                if record['revision'] != old['revision']:
                    raise ValueError('Metadata revision conflict; reread before editing')
                revision = old['revision'] + 1
                identity_changed = any((f['field'] in ('brand', 'category') or f['field'].startswith('attr.')) and
                    any(before.get(f['field'], {}).get(k) != f[k] for k in ('value', 'number', 'unit')) for f in changes)
                if identity_changed:
                    linked = self.db.execute('SELECT group_id FROM pool_product_links WHERE product_id=?', (pid,)).fetchone()
                    if linked:
                        group = linked[0]
                        members = [dict(r) for r in self.db.execute('SELECT * FROM pool_product_links WHERE group_id=?', (group,))]
                        self.db.execute('DELETE FROM pool_product_links WHERE group_id=?', (group,))
                        event(self.db, 'group', group, revision, 'identity_changed_requires_review', {'product_id': pid, 'before': members})
                        invalidated_groups.add(group)
                self.db.execute('INSERT INTO pool_profiles VALUES (?,?) ON CONFLICT(product_id) DO UPDATE SET revision=excluded.revision', (pid, revision))
                self.db.executemany('DELETE FROM pool_metadata WHERE product_id=? AND field=?',
                                    [(pid, f['field']) for f in changes if f['value'] is None])
                self.db.executemany('''INSERT INTO pool_metadata VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(product_id,field)
                    DO UPDATE SET value=excluded.value,number=excluded.number,unit=excluded.unit,
                    origin=excluded.origin,quote=excluded.quote,reason=excluded.reason''',
                    [(pid, *(f[k] for k in ('field', 'value', 'number', 'unit', 'origin', 'quote', 'reason'))) for f in changes if f['value'] is not None])
                event(self.db, 'product', pid, revision, 'enrich', {'before': [before.get(f['field']) for f in changes], 'after': changes})
                updated += 1
        return {'updated': updated, 'unchanged': unchanged, 'groups_requiring_review': sorted(invalidated_groups)}

    def derive(self, ids=None, file_id=None):
        if ids is not None and (not isinstance(ids, list) or not 1 <= len(ids) <= 100):
            raise ValueError('Derive accepts 1..100 explicit IDs or all records')
        if ids and file_id: raise ValueError('Choose IDs or a file, not both')
        if file_id: self.pool.document(file_id)
        where = ' WHERE source_path=?' if file_id else ' WHERE id IN (' + ','.join('?' for _ in ids) + ')' if ids else ''
        rows = self.db.execute('SELECT id,payload FROM products' + where + ' ORDER BY id', [file_id] if file_id else ids or []).fetchall()
        labels = {'brand': '品牌|brand', 'supplier': '供应商|供货商|supplier', 'attr.capacity': '容量|capacity',
                  'attr.weight': '净重|重量|weight', 'attr.power': '功率|power', 'attr.material': '材质|material'}
        pending, updated, invalidated_groups = [], 0, set()
        for row in rows:
            item, profile = json.loads(row['payload']), self.profile(row['id'])
            facts = []
            for field, label in labels.items():
                if field in profile['facts'] or (field in ('brand', 'supplier') and item.get(field)):
                    continue
                matches = list(re.finditer(r'(?:^|\n)\s*(?:' + label + r')\s*[：:]\s*([^\n]+)', own_text(item), re.I))
                values = {m[1].strip() for m in matches}
                if len(values) != 1:
                    continue
                value = next(iter(values))
                fact = dict(field=field, value=value, origin='source', quote=matches[0][0].strip(), reason='原文明确标注的字段')
                if field.startswith('attr.') and field != 'attr.material':
                    measured = QUANTITY.fullmatch(normalize(value))
                    if not measured:
                        continue
                    fact.update(value=float(measured[1]), unit=measured[2])
                if value and len(value) <= 160:
                    facts.append(fact)
            if facts:
                pending.append({'id': row['id'], 'revision': profile['revision'], 'facts': facts})
            if len(pending) == 100:
                outcome = self.enrich(pending)
                updated += outcome['updated']
                invalidated_groups.update(outcome['groups_requiring_review'])
                pending = []
        if pending:
            outcome = self.enrich(pending)
            updated += outcome['updated']
            invalidated_groups.update(outcome['groups_requiring_review'])
        return {'scanned': len(rows), 'updated': updated, 'groups_requiring_review': sorted(invalidated_groups), 'method': 'explicit labeled source facts only'}

    def quality(self, price_field=None):
        total = self.db.execute('SELECT count(*) FROM products').fetchone()[0]
        missing = {}
        for field in ('brand', 'supplier', 'category'):
            value = f"COALESCE((SELECT value FROM pool_metadata m WHERE m.product_id=p.id AND m.field='{field}'),p.{field})"
            missing[field] = self.db.execute(f"SELECT count(*) FROM products p WHERE {value} IS NULL OR {value} IN ('','未分类')").fetchone()[0]
        result = {'scope': 'whole_pool', 'products': total, 'missing': missing,
                  'tagged_products': self.db.execute('SELECT count(DISTINCT product_id) FROM pool_tags').fetchone()[0],
                  'incomplete_files': self.db.execute("SELECT count(*) FROM pool_documents WHERE status<>'ready'").fetchone()[0],
                  'enriched_products': self.db.execute('SELECT count(*) FROM pool_profiles').fetchone()[0]}
        result['sources_without_version'] = self.db.execute('''SELECT count(*) FROM pool_documents d LEFT JOIN pool_source_state s ON s.file_id=d.id
            WHERE COALESCE(s.status,'active')='active' AND (s.series IS NULL OR s.issued_on IS NULL)''').fetchone()[0]
        result['grouped_products'] = self.db.execute('SELECT count(*) FROM pool_product_links').fetchone()[0]
        result['categories_needing_review'] = self.db.execute("""SELECT count(*) FROM products p WHERE
            NOT EXISTS (SELECT 1 FROM pool_metadata m WHERE m.product_id=p.id AND m.field='category')
            AND NOT (p.category_origin='rule' AND instr(p.category,'/')>0)""").fetchone()[0]
        result['ambiguous_quote_series'] = self.db.execute("""SELECT count(*) FROM (SELECT series FROM pool_source_state s
            WHERE status='active' AND series IS NOT NULL GROUP BY series
            HAVING count(*) FILTER (WHERE issued_on IS NULL)>0 OR
            count(*) FILTER (WHERE issued_on=(SELECT max(x.issued_on) FROM pool_source_state x WHERE x.series=s.series AND x.status='active'))>1)""").fetchone()[0]
        result['partial_newest_quotes'] = self.db.execute("""SELECT count(*) FROM pool_source_state s JOIN pool_documents d ON d.id=s.file_id
            WHERE s.status='active' AND s.series IS NOT NULL AND d.status<>'ready'
            AND s.issued_on=(SELECT max(x.issued_on) FROM pool_source_state x WHERE x.series=s.series AND x.status='active')""").fetchone()[0]
        if price_field:
            if total and not self.db.execute('SELECT 1 FROM prices WHERE field=? LIMIT 1', (price_field,)).fetchone():
                raise ValueError('Unknown price field; inspect price facets')
            numeric = self.db.execute('SELECT count(*) FROM prices WHERE field=? AND amount IS NOT NULL', (price_field,)).fetchone()[0]
            result['price'] = {'field': price_field, 'numeric': numeric, 'unusable': total - numeric}
            from extract import PRICE_ROLES
            result['price']['basis_conflicts'] = (self.db.execute('SELECT count(*) FROM prices WHERE field=? AND pool_price_basis(label) IS NOT NULL AND pool_price_basis(label)<>?', (price_field, price_field)).fetchone()[0]
                                                if price_field in PRICE_ROLES else 0)
        return result

    def history(self, kind=None, key=None, event_id=None, limit=10, offset=0, max_chars=1000, text_offset=0):
        if not 1 <= limit <= 50 or offset < 0 or not 100 <= max_chars <= 4000 or text_offset < 0:
            raise ValueError('Invalid history pagination/text budget')
        if event_id is not None:
            row = self.db.execute('SELECT * FROM pool_events WHERE id=?', (event_id,)).fetchone()
            if not row: raise ValueError('Unknown history event')
            result = dict(row)
            result['payload_chars'] = len(result['payload'])
            result['payload'] = result['payload'][text_offset:text_offset + max_chars]
            result['text_offset'] = text_offset
            result['more'] = text_offset + max_chars < result['payload_chars']
            return result
        if kind not in ('product', 'source', 'offer', 'group', 'vocabulary') or not isinstance(key, str):
            raise ValueError('History requires kind and entity ID, or one event ID')
        total = self.db.execute('SELECT count(*) FROM pool_events WHERE entity_type=? AND entity_id=?', (kind, key)).fetchone()[0]
        rows = self.db.execute('SELECT id,revision,event_type,created_at,length(payload) AS payload_chars FROM pool_events WHERE entity_type=? AND entity_id=? ORDER BY id DESC LIMIT ? OFFSET ?', (kind, key, limit, offset))
        return {'total': total, 'items': [dict(r) for r in rows], 'limit': limit, 'offset': offset}

    def review_queue(self, field='category', limit=20, offset=0):
        if field not in ('brand', 'category', 'supplier') or not 1 <= limit <= 50 or offset < 0:
            raise ValueError('Invalid review field/pagination')
        value = f"COALESCE((SELECT value FROM pool_metadata m WHERE m.product_id=p.id AND m.field='{field}'),p.{field})"
        where = (" WHERE NOT EXISTS (SELECT 1 FROM pool_metadata m WHERE m.product_id=p.id AND m.field='category')"
                 " AND NOT (p.category_origin='rule' AND instr(p.category,'/')>0)" if field == 'category'
                 else f" WHERE {value} IS NULL OR {value} IN ('','未分类')")
        total = self.db.execute('SELECT count(*) FROM products p' + where).fetchone()[0]
        rows = self.db.execute('SELECT id,name,payload FROM products p' + where + ' ORDER BY name,id LIMIT ? OFFSET ?', (limit, offset))
        items = []
        for row in rows:
            raw = json.loads(row['payload'])
            items.append({'id': row['id'], 'name': row['name'], 'model': raw.get('model'), 'facts': raw['features'][:240],
                          'revision': self.profile(row['id'])['revision']})
        return {'field': field, 'total': total, 'limit': limit, 'offset': offset, 'items': items}

    def vocabulary(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 50:
            raise ValueError('Vocabulary accepts 1..50 equivalence groups')
        with self.db:
            for record in records:
                if not isinstance(record, dict) or set(record) != {'kind', 'terms', 'reason'}:
                    raise ValueError('Vocabulary requires kind/terms/reason')
                kind, terms, reason = record['kind'], record['terms'], record['reason']
                if not isinstance(kind, str) or not re.fullmatch(r'(?:query|brand|supplier|category|tag:[a-z][a-z0-9_]*)', kind):
                    raise ValueError('Unknown vocabulary kind')
                if not isinstance(terms, list) or not 2 <= len(terms) <= 8 or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 80 for t in terms):
                    raise ValueError('Provide 2..8 bounded equivalent terms')
                normalized = {normalize(term): term.strip() for term in terms}
                if len(normalized) != len(terms) or not isinstance(reason, str) or not 1 <= len(reason) <= 500:
                    raise ValueError('Vocabulary needs distinct terms and reason')
                for term in normalized:
                    previous = self.aliases(kind, term)
                    if not {normalize(t) for t in previous} <= set(normalized):
                        raise ValueError('Include the complete existing equivalence group when extending it')
                key = hashlib.sha256(packed(sorted(normalized)).encode()).hexdigest()[:24]
                self.db.executemany('INSERT INTO pool_vocabulary VALUES (?,?,?,?,?) ON CONFLICT(kind,term) DO UPDATE SET group_key=excluded.group_key,display=excluded.display,reason=excluded.reason',
                                    [(kind, term, key, display, reason) for term, display in normalized.items()])
                event(self.db, 'vocabulary', kind + ':' + key, 1, 'equivalence', record)
        return {'groups': len(records)}

    def aliases(self, kind, term):
        row = self.db.execute('SELECT group_key FROM pool_vocabulary WHERE kind=? AND term=?', (kind, normalize(term))).fetchone()
        return [r[0] for r in self.db.execute('SELECT display FROM pool_vocabulary WHERE kind=? AND group_key=? ORDER BY term', (kind, row[0]))] if row else [term]
