"""Reviewed source lineage and quote contexts, independent of upload timestamps."""

import datetime
import hashlib
import json
import re

from catalog_store import normalize, resolve_price
from pool_metadata import event, own_text, packed


def ensure_schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS pool_source_state (
        file_id TEXT PRIMARY KEY REFERENCES pool_documents(id), revision INTEGER NOT NULL,
        series TEXT, issued_on TEXT, status TEXT NOT NULL CHECK(status IN ('active','withdrawn','superseded')),
        superseded_by TEXT REFERENCES pool_documents(id), reason TEXT NOT NULL, evidence TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS pool_source_series ON pool_source_state(series,status,issued_on);
      CREATE TABLE IF NOT EXISTS pool_product_links (
        product_id TEXT PRIMARY KEY REFERENCES products(id), group_id TEXT NOT NULL,
        reason TEXT NOT NULL, evidence TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS pool_product_group ON pool_product_links(group_id,product_id);
      CREATE TABLE IF NOT EXISTS pool_offer_terms (
        product_id TEXT NOT NULL REFERENCES products(id), field TEXT NOT NULL, revision INTEGER NOT NULL,
        terms TEXT NOT NULL, PRIMARY KEY(product_id,field));
    ''')


class Lifecycle:
    def __init__(self, pool):
        self.pool, self.db = pool, pool.db

    def source_state(self, file_id):
        self.pool.document(file_id)
        row = self.db.execute('SELECT * FROM pool_source_state WHERE file_id=?', (file_id,)).fetchone()
        return dict(row) if row else dict(file_id=file_id, revision=0, series=None, issued_on=None, status='active', superseded_by=None, reason='', evidence='[]')

    def _write_source(self, state, before):
        self.db.execute('''INSERT INTO pool_source_state VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(file_id)
            DO UPDATE SET revision=excluded.revision,series=excluded.series,issued_on=excluded.issued_on,
            status=excluded.status,superseded_by=excluded.superseded_by,reason=excluded.reason,evidence=excluded.evidence''',
            tuple(state[k] for k in ('file_id', 'revision', 'series', 'issued_on', 'status', 'superseded_by', 'reason', 'evidence')))
        event(self.db, 'source', state['file_id'], state['revision'], 'source_state', {'before': before, 'after': state})

    def update_sources(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 50:
            raise ValueError('Source updates accept 1..50 records')
        checked, prepared = set(), []
        # Resolve evidence before opening the write transaction: native evidence caching owns a transaction.
        for record in records:
            if not isinstance(record, dict) or set(record) != {'id', 'revision', 'changes', 'reason', 'evidence'}:
                raise ValueError('Source update requires id/revision/changes/reason/evidence')
            fid = record['id']
            if fid in checked or type(record['revision']) is not int:
                raise ValueError('Duplicate source ID or invalid revision')
            checked.add(fid)
            document = self.pool.document(fid)
            self.pool.source(fid)
            changes, reason, evidence = record['changes'], record['reason'], record['evidence']
            if not isinstance(changes, dict) or not changes or set(changes) - {'series', 'issued_on', 'status', 'supersedes'}:
                raise ValueError('Unknown source changes')
            if not isinstance(reason, str) or not 1 <= len(reason) <= 500 or not isinstance(evidence, list) or len(evidence) > 10:
                raise ValueError('Source update requires bounded reason and evidence')
            quoted, entries = [], None
            for ref in evidence:
                if not isinstance(ref, dict) or set(ref) != {'ref', 'quote'} or not isinstance(ref['quote'], str) or not 1 <= len(ref['quote']) <= 1000:
                    raise ValueError('Invalid source evidence reference')
                if ref['ref'] == 'filename':
                    text = document['name']
                else:
                    if entries is None: entries = {e['id']: e for e in self.pool.evidence(fid)}
                    text = entries.get(ref['ref'], {}).get('text', '')
                if ref['quote'] not in text:
                    raise ValueError('Source evidence quote is absent')
                quoted.append(ref['quote'])
            date = changes.get('issued_on')
            if date is not None:
                if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                    raise ValueError('Use an explicit YYYY-MM-DD issue date')
                parsed = datetime.date.fromisoformat(date)
                pattern = rf'(?<!\d){parsed.year}[-/.年]0?{parsed.month}[-/.月]0?{parsed.day}(?:日)?(?!\d)'
                if not any(re.search(pattern, normalize(q)) for q in quoted):
                    raise ValueError('Missing matching issue date evidence; never use upload time')
            if 'series' in changes and changes['series'] is not None and (not isinstance(changes['series'], str) or not 1 <= len(changes['series'].strip()) <= 120):
                raise ValueError('Invalid source series')
            if changes.get('status', 'active') not in ('active', 'withdrawn'):
                raise ValueError('Use supersedes to retire a replaced source')
            prepared.append((record, document))
        with self.db:
            for record, document in prepared:
                before = self.source_state(record['id'])
                if record['revision'] != before['revision']:
                    raise ValueError('Source revision conflict; reread before changing lineage')
                changes = record['changes']
                after = {**before, **{k: v for k, v in changes.items() if k != 'supersedes'},
                         'revision': before['revision'] + 1, 'reason': record['reason'], 'evidence': packed(record['evidence'])}
                if after['status'] == 'active': after['superseded_by'] = None
                replacement = changes.get('supersedes')
                if replacement:
                    if not isinstance(replacement, dict) or set(replacement) != {'id', 'revision'} or replacement['id'] == record['id']:
                        raise ValueError('supersedes requires a different source ID and its revision')
                    previous = self.source_state(replacement['id'])
                    if previous['revision'] != replacement['revision']:
                        raise ValueError('Superseded source revision conflict')
                    if document['status'] != 'ready':
                        raise ValueError('A partial/pending import cannot supersede a complete source')
                    if (after['status'] != 'active' or not after['series'] or after['series'] != previous['series']
                            or not after['issued_on'] or not previous['issued_on'] or after['issued_on'] <= previous['issued_on']):
                        raise ValueError('Replacement needs matching reviewed series and a strictly newer sourced date')
                    retired = {**previous, 'revision': previous['revision'] + 1, 'status': 'superseded', 'superseded_by': record['id'], 'reason': record['reason']}
                    self._write_source(retired, previous)
                self._write_source(after, before)
        return {'updated': len(prepared)}

    def search_clauses(self, constraints):
        where, params = [], []
        for key in ('include_history', 'latest'):
            if key in constraints and type(constraints[key]) is not bool:
                raise ValueError(key + ' must be boolean')
        if constraints.get('latest') and constraints.get('include_history'):
            raise ValueError('latest and include_history cannot be combined')
        if not constraints.get('include_history'):
            where.append("NOT EXISTS (SELECT 1 FROM pool_source_state ss WHERE ss.file_id=p.source_path AND ss.status<>'active')")
        if constraints.get('latest'):
            where.append('''EXISTS (SELECT 1 FROM pool_source_state ss JOIN pool_documents sd ON sd.id=ss.file_id
                WHERE ss.file_id=p.source_path AND ss.status='active' AND ss.series IS NOT NULL AND ss.issued_on IS NOT NULL AND sd.status='ready'
                AND NOT EXISTS (SELECT 1 FROM pool_source_state other WHERE other.series=ss.series AND other.status='active'
                    AND other.file_id<>ss.file_id AND (other.issued_on IS NULL OR other.issued_on>=ss.issued_on)))''')
        if constraints.get('series'):
            where.append('EXISTS (SELECT 1 FROM pool_source_state ss WHERE ss.file_id=p.source_path AND ss.series=?)')
            params.append(constraints['series'])
        return where, params

    def link_products(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 50:
            raise ValueError('Link accepts 1..50 reviewed groups')
        with self.db:
            for record in records:
                if not isinstance(record, dict) or set(record) != {'group', 'ids', 'reason', 'evidence'}:
                    raise ValueError('Product group needs group/ids/reason/evidence')
                group, ids, reason, evidence = (record[k] for k in ('group', 'ids', 'reason', 'evidence'))
                if not isinstance(group, str) or not 1 <= len(group) <= 120 or not isinstance(ids, list) or not 2 <= len(ids) <= 100 or len(ids) != len(set(ids)):
                    raise ValueError('Invalid product group or member IDs')
                if not isinstance(reason, str) or not 1 <= len(reason) <= 500 or not isinstance(evidence, dict) or set(evidence) != set(ids):
                    raise ValueError('Group needs a reason and own evidence for every product')
                existing = [r[0] for r in self.db.execute('SELECT product_id FROM pool_product_links WHERE group_id=?', (group,))]
                if not set(existing) <= set(ids):
                    raise ValueError('Include all existing members when extending a product group')
                items = self.pool.details(ids, verify_fresh=True)
                identity = {field: set() for field in ('brand', 'model', 'variant')}
                attrs = {}
                for item in items:
                    quote = evidence[item['id']]
                    if not isinstance(quote, str) or not 1 <= len(quote) <= 1000 or quote not in own_text(item):
                        raise ValueError('Group evidence must quote each product own source')
                    for field in identity:
                        value = item['metadata']['facts'].get(field, {}).get('value') or item.get(field)
                        if value: identity[field].add(normalize(value))
                    for field, fact in item['metadata']['facts'].items():
                        if field.startswith('attr.'):
                            attrs.setdefault(field, set()).add((str(fact['value']), fact['unit']))
                    previous = self.db.execute('SELECT group_id FROM pool_product_links WHERE product_id=?', (item['id'],)).fetchone()
                    if previous and previous[0] != group:
                        raise ValueError('Product already belongs to another group; do not silently merge identities')
                if any(len(values) > 1 for values in [*identity.values(), *attrs.values()]):
                    raise ValueError('Conflicting brand/model/variant/attributes; these are not one SKU')
                if any(not (item['metadata']['facts'].get('brand', {}).get('value') or item.get('brand')) or not item.get('model') for item in items):
                    raise ValueError('Grouping needs a known matching brand and model for every product')
                self.db.executemany('INSERT INTO pool_product_links VALUES (?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET reason=excluded.reason,evidence=excluded.evidence',
                                    [(pid, group, reason, evidence[pid]) for pid in ids])
                event(self.db, 'group', group, 1, 'reviewed_link', record)
        return {'groups': len(records)}

    def product_group(self, product_id):
        row = self.db.execute('SELECT group_id FROM pool_product_links WHERE product_id=?', (product_id,)).fetchone()
        return row[0] if row else None

    def offer_terms(self, product_id, field=None):
        rows = self.db.execute('SELECT field,revision,terms FROM pool_offer_terms WHERE product_id=?' + (' AND field=?' if field else ''), (product_id, field) if field else (product_id,))
        return {r['field']: {'revision': r['revision'], 'terms': json.loads(r['terms'])} for r in rows}

    def set_offer_terms(self, records):
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError('Quote terms accept 1..100 entries')
        with self.db:
            for record in records:
                if not isinstance(record, dict) or set(record) != {'id', 'field', 'revision', 'terms'} or type(record['revision']) is not int:
                    raise ValueError('Quote terms require id/field/revision/terms')
                item = self.pool.details([record['id']], verify_fresh=True)[0]
                if record['field'] not in item['prices']:
                    raise ValueError('Quote terms require a canonical price field from the product prices, not a label alias')
                terms = record['terms']
                if not isinstance(terms, dict) or not terms or set(terms) - {'currency', 'unit', 'tax', 'shipping', 'moq'}:
                    raise ValueError('Unknown/empty quote terms')
                for key, fact in terms.items():
                    if not isinstance(fact, dict) or set(fact) != {'value', 'quote'}:
                        raise ValueError('Quote terms require value/quote evidence')
                    value, quote = fact['value'], fact['quote']
                    if not isinstance(quote, str) or not 1 <= len(quote) <= 1000 or quote not in own_text(item):
                        raise ValueError('Quote terms need product-owned evidence')
                    if key == 'currency':
                        supported = {'CNY': ('CNY', 'RMB', '人民币'), 'USD': ('USD', '美元'), 'EUR': ('EUR', '欧元'), 'HKD': ('HKD', '港币', '港元')}
                        valid = value in supported and any(normalize(v) in normalize(quote) for v in supported[value])
                    elif key in ('tax', 'shipping'):
                        word = '税' if key == 'tax' else '运'
                        excluded = any(t in quote for t in ('不含' + word, '未含' + word, '未' + word))
                        valid = value == 'excluded' and excluded or value == 'included' and '含' + word in quote and not excluded
                    elif key == 'moq':
                        # A quantity elsewhere in the product is not an order minimum.
                        amount = re.escape(str(value))
                        valid = type(value) is int and value > 0 and re.search(
                            r'(?:起订量|起订数量|最低订货量|最小订货量|\bMOQ\b)\s*[：:]?\s*' + amount + r'(?![\d.])'
                            r'|(?<![\d.])' + amount + r'\s*(?:件|只|个|套|箱|盒|台|包)?\s*起订', quote, re.I)
                    else:
                        valid = isinstance(value, str) and 1 <= len(value) <= 40 and value in quote
                    if not valid: raise ValueError('Quote term value is not established by its evidence')
                old = self.offer_terms(record['id'], record['field']).get(record['field'], {'revision': 0, 'terms': {}})
                after = {**old['terms'], **terms}
                if after == old['terms']: continue
                if old['revision'] != record['revision']:
                    raise ValueError('Quote terms revision conflict')
                revision = old['revision'] + 1
                self.db.execute('INSERT INTO pool_offer_terms VALUES (?,?,?,?) ON CONFLICT(product_id,field) DO UPDATE SET revision=excluded.revision,terms=excluded.terms',
                                (record['id'], record['field'], revision, packed(after)))
                event(self.db, 'offer', record['id'] + ':' + record['field'], revision, 'terms', {'before': old, 'after': after})
        return {'processed': len(records)}

    def selection_context(self, product_id):
        row = self.db.execute('SELECT source_path FROM products WHERE id=?', (product_id,)).fetchone()
        if not row: raise ValueError('Unknown selected product')
        source = self.source_state(row[0])
        if source['status'] != 'active':
            raise ValueError('Selected quote source is withdrawn/superseded; choose a current quote')
        value = {'source': source, 'profile': self.pool.meta.profile(product_id), 'tags': self.pool.tags(product_id),
                 'terms': self.offer_terms(product_id), 'group': self.product_group(product_id)}
        return hashlib.sha256(packed(value).encode()).hexdigest()
