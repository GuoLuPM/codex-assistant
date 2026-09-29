"""Bounded retrieval plans: immutable hard filters, explicit alternative routes."""

import itertools
import json
import math
import re
import time
from collections import defaultdict, deque

from catalog_store import normalize, parse_price
from pool_metadata import own_text, packed, quantity


CONSTRAINT_KEYS = {'tags', 'tag_mode', 'tag_origin', 'tag_groups', 'file_id', 'category', 'categories', 'brand', 'supplier',
                   'exclude_categories', 'attributes', 'latest', 'include_history', 'series', 'price_labels', 'price_terms', 'price_field', 'product_group'}


def field_sql(field):
    if field not in ('category', 'brand', 'supplier'):
        raise ValueError('Unknown metadata filter field')
    return f"COALESCE((SELECT value FROM pool_metadata m WHERE m.product_id=p.id AND m.field='{field}'),p.{field})"


def strings(value, maximum=12):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(v, str) or not 1 <= len(v) <= 160 for v in value):
        raise ValueError('Expected a bounded array of nonempty strings')
    return value


def category_clause(pool, category):
    if not isinstance(category, str) or not 1 <= len(category) <= 160:
        raise ValueError('Invalid category')
    terms, clauses, params = pool.aliases('category', category), [], []
    column = 'pool_norm(' + field_sql('category') + ')'
    for term in terms:
        term = normalize(term)
        clauses.append(f'''({column}=? OR substr({column},1,?)=? OR EXISTS
            (SELECT 1 FROM pool_tags ct WHERE ct.product_id=p.id AND ct.kind='category'
             AND (pool_norm(ct.value)=? OR substr(pool_norm(ct.value),1,?)=?)))''')
        params.extend([term, len(term) + 1, term + '/', term, len(term) + 1, term + '/'])
    return '(' + ' OR '.join(clauses) + ')', params


def search_constraints(pool, constraints):
    if not isinstance(constraints, dict) or set(constraints) - CONSTRAINT_KEYS:
        raise ValueError('Unknown pool search constraints')
    where, params = pool.lifecycle.search_clauses(constraints)
    categories = strings(constraints.get('categories', []))
    if constraints.get('category'):
        categories = [constraints['category'], *categories]
    for category in categories:
        clause, values = category_clause(pool, category)
        where.append(clause); params.extend(values)
    excluded = strings(constraints.get('exclude_categories', []))
    if excluded:
        # Negation requires a known normalized category, not an arbitrary worksheet heading.
        where.append("(EXISTS (SELECT 1 FROM pool_metadata mc WHERE mc.product_id=p.id AND mc.field='category') OR EXISTS (SELECT 1 FROM pool_tags ct WHERE ct.product_id=p.id AND ct.kind='category') OR instr(p.category,'/')>0)")
    for category in excluded:
        clause, values = category_clause(pool, category)
        where.append('NOT ' + clause); params.extend(values)
    for field in ('brand', 'supplier'):
        if constraints.get(field):
            if not isinstance(constraints[field], str): raise ValueError('Invalid ' + field)
            values = [normalize(v) for v in pool.aliases(field, constraints[field])]
            where.append('pool_norm(' + field_sql(field) + ') IN (' + ','.join('?' for _ in values) + ')')
            params.extend(values)
    if constraints.get('file_id'):
        where.append('p.source_path=?'); params.append(constraints['file_id'])
    if constraints.get('product_group'):
        group = constraints['product_group']
        if not isinstance(group, str) or not 1 <= len(group) <= 120: raise ValueError('Invalid product group')
        where.append('EXISTS (SELECT 1 FROM pool_product_links gl WHERE gl.product_id=p.id AND gl.group_id=?)')
        params.append(group)
    groups = constraints.get('tag_groups', [])
    if not isinstance(groups, list) or len(groups) > 8:
        raise ValueError('Invalid tag groups')
    groups = [{'tags': constraints.get('tags', []), 'mode': constraints.get('tag_mode', 'all'), 'origin': constraints.get('tag_origin')}, *groups]
    for group in groups:
        if not isinstance(group, dict) or set(group) - {'tags', 'mode', 'origin'}:
            raise ValueError('Invalid tag group')
        tags = strings(group.get('tags', []))
        if group.get('mode', 'all') not in ('all', 'any') or group.get('origin') not in (None, 'source', 'inferred'):
            raise ValueError('Invalid tag mode/origin')
        clauses = []
        for tag in tags:
            kind, separator, value = tag.partition(':')
            if not separator or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', kind) or not value:
                raise ValueError('Tag query uses kind:value')
            values = [normalize(v) for v in pool.aliases('tag:' + kind, value)]
            clause = 'EXISTS (SELECT 1 FROM pool_tags t WHERE t.product_id=p.id AND t.kind=? AND pool_norm(t.value) IN (' + ','.join('?' for _ in values) + ')'
            params.extend([kind, *values])
            if group.get('origin'):
                clause += ' AND t.origin=?'; params.append(group['origin'])
            clauses.append(clause + ')')
        if clauses: where.append('(' + (' AND ' if group.get('mode', 'all') == 'all' else ' OR ').join(clauses) + ')')
    attributes = constraints.get('attributes', [])
    if not isinstance(attributes, list) or len(attributes) > 12:
        raise ValueError('At most 12 attribute conditions')
    for attr in attributes:
        if not isinstance(attr, dict) or set(attr) - {'field', 'value', 'minimum', 'maximum', 'unit'} or not re.fullmatch(r'attr\.[a-z][a-z0-9_]{0,39}', str(attr.get('field', ''))):
            raise ValueError('Invalid attribute condition')
        clause = "EXISTS (SELECT 1 FROM pool_metadata ma WHERE ma.product_id=p.id AND ma.field=? AND ma.origin='source'"
        params.append(attr['field'])
        if 'value' in attr:
            if set(attr) != {'field', 'value'} or not isinstance(attr['value'], str) or not attr['value']:
                raise ValueError('Text attribute requires field/value only')
            clause += ' AND ma.number IS NULL AND pool_norm(ma.value)=?'; params.append(normalize(attr['value']))
        else:
            if 'unit' not in attr or not {'minimum', 'maximum'} & set(attr):
                raise ValueError('Numeric attribute requires explicit unit and bounds')
            if 'minimum' in attr and 'maximum' in attr and attr['minimum'] > attr['maximum']:
                raise ValueError('Attribute minimum exceeds maximum')
            for key, operator in (('minimum', '>='), ('maximum', '<=')):
                if key in attr:
                    number, unit = quantity(attr[key], attr['unit'])
                    clause += f' AND ma.unit=? AND ma.number{operator}?'; params.extend([unit, number])
        where.append(clause + ')')
    price_field = constraints.get('price_field')
    labels = strings(constraints.get('price_labels', []))
    terms = constraints.get('price_terms', {})
    if not isinstance(terms, dict) or set(terms) - {'currency', 'unit', 'tax', 'shipping', 'moq'}:
        raise ValueError('Unknown quote terms filter')
    if (labels or terms) and not price_field:
        raise ValueError('Quote terms/labels require an explicit price_field')
    from extract import PRICE_ROLES
    if price_field in PRICE_ROLES and not labels:
        where.append('EXISTS (SELECT 1 FROM prices basis WHERE basis.product_pk=p.pk AND basis.field=? AND (pool_price_basis(basis.label) IS NULL OR pool_price_basis(basis.label)=?))')
        params.extend([price_field, price_field])
    if labels:
        where.append('EXISTS (SELECT 1 FROM prices lp WHERE lp.product_pk=p.pk AND lp.field=? AND lp.label IN (' + ','.join('?' for _ in labels) + '))')
        params.extend([price_field, *labels])
    for key, value in terms.items():
        if key == 'moq':
            if type(value) is not int or value < 1: raise ValueError('moq filter must be a positive integer')
        elif not isinstance(value, str) or not value or len(value) > 40:
            raise ValueError('Invalid quote term filter')
        where.append("EXISTS (SELECT 1 FROM pool_offer_terms ot WHERE ot.product_id=p.id AND ot.field=? AND json_extract(ot.terms,?)=?)")
        params.extend([price_field, '$.' + key + '.value', value])
    return where, params


def retrieve(pool, plan):
    started = time.perf_counter()
    if not isinstance(plan, dict) or set(plan) - {'version', 'hard', 'lanes', 'limit', 'per_lane', 'diversity', 'group_products'} or type(plan.get('version')) is not int or plan['version'] != 1:
        raise ValueError('Unknown retrieval plan; version 1 required')
    hard, lanes = plan.get('hard', {}), plan.get('lanes')
    simple = {'price_field', 'minimum', 'maximum', 'category', 'brand', 'supplier', 'exclude', 'has_image', 'sort'}
    extra = {'tags', 'tag_origin', 'file_id', 'exclude_categories', 'attributes', 'latest', 'include_history', 'series', 'price_labels', 'price_terms', 'product_group'}
    if not isinstance(hard, dict) or set(hard) - simple - extra:
        raise ValueError('Unknown hard filter')
    for key in ('minimum', 'maximum'):
        if key in hard and (type(hard[key]) not in (int, float) or not math.isfinite(hard[key])):
            raise ValueError('Hard price bounds must be finite numbers')
    if 'exclude' in hard: strings(hard['exclude'])
    if 'has_image' in hard and type(hard['has_image']) is not bool: raise ValueError('has_image must be boolean')
    for key in ('price_field', 'brand', 'supplier', 'category', 'file_id', 'series'):
        if key in hard and (not isinstance(hard[key], str) or not 1 <= len(hard[key]) <= 200):
            raise ValueError('Invalid hard ' + key)
    if not isinstance(lanes, list) or not 1 <= len(lanes) <= 8:
        raise ValueError('Provide 1..8 explicit retrieval lanes')
    limit, per_lane = plan.get('limit', 10), plan.get('per_lane', 30)
    if type(limit) is not int or type(per_lane) is not int or not 1 <= limit <= 50 or not limit <= per_lane <= 50:
        raise ValueError('Retrieval limit must be 1..50; per_lane must be limit..50')
    for key in ('diversity', 'group_products'):
        if key in plan and type(plan[key]) is not bool: raise ValueError(key + ' must be boolean')
    expanded, seen = [], set()
    expansion_clipped = False
    for lane in lanes:
        if not isinstance(lane, dict) or set(lane) - {'query', 'scope', 'category', 'tags'}:
            raise ValueError('A lane may only specify query/scope/category/tags; hard filters cannot be overridden')
        query = lane.get('query', '')
        if not isinstance(query, str) or len(query) > 160 or len(query.split()) > 10:
            raise ValueError('Invalid lane query')
        choices = [pool.aliases('query', term) for term in query.split()]
        variants = list(itertools.islice(itertools.product(*choices), 5)) if choices else [()]
        if len(variants) > 4: expansion_clipped = True
        for words in variants[:4]:
            candidate = {**lane, 'query': ' '.join(words)}
            key = packed(candidate)
            if key not in seen:
                expanded.append(candidate); seen.add(key)
    if len(expanded) > 24:
        expansion_clipped = True; expanded = expanded[:24]
    items, scores, matches, reports = {}, defaultdict(float), defaultdict(list), []
    previous_cache = getattr(pool, '_freshness_snapshot', None)
    pool._freshness_snapshot = pool.stale_sources()
    try:
        for index, lane in enumerate(expanded):
            constraints = {k: v for k, v in hard.items() if k in extra}
            if lane.get('category'): constraints['categories'] = [lane['category']]
            if lane.get('tags'): constraints['tag_groups'] = [{'tags': lane['tags']}]
            query = {k: v for k, v in hard.items() if k in simple}
            query.update(query=lane['query'], scope=lane.get('scope', 'all'), constraints=constraints, limit=per_lane)
            result = pool.search(**query)
            reports.append({'query': lane, 'total': result['total'], 'returned': len(result['items'])})
            for rank, item in enumerate(result['items'], 1):
                pid = item['id']; items[pid] = item; scores[pid] += 1 / (60 + rank); matches[pid].append(index)
        ordered = sorted(items, key=lambda pid: (-scores[pid], pid))
        if hard.get('sort') in ('price-asc', 'price-desc'):
            direction = -1 if hard['sort'] == 'price-desc' else 1
            def price_order(pid):
                value = parse_price(items[pid].get('price', {}).get('value'))
                return value is None, direction * (value or 0), -scores[pid], pid
            ordered.sort(key=price_order)
        grouped, representatives = {}, []
        for pid in ordered:
            group = items[pid].get('product_group') if plan.get('group_products', True) else None
            key = 'group:' + group if group else pid
            if key not in grouped:
                grouped[key] = []; representatives.append(pid)
            grouped[key].append(pid)
        if plan.get('diversity', True) and hard.get('sort', 'relevance') == 'relevance':
            buckets = {}
            for pid in representatives:
                buckets.setdefault(items[pid]['category'].split('/')[0], deque()).append(pid)
            representatives = []
            while any(buckets.values()):
                for bucket in buckets.values():
                    if bucket: representatives.append(bucket.popleft())
        selected = []
        for pid in representatives[:limit]:
            item = items[pid]
            raw = pool.db.execute('SELECT payload FROM products WHERE id=?', (pid,)).fetchone()[0]
            # Unknown source columns still carry useful evidence. The extractor's
            # display-feature projection is not the complete factual record.
            facts = '\n'.join(dict.fromkeys(line for line in own_text(json.loads(raw)).splitlines() if line.strip()))
            item['facts_excerpt'], item['facts_length'] = facts[:240], len(facts)
            item['matched_lanes'] = matches[pid]
            group = item.get('product_group') if plan.get('group_products', True) else None
            members = grouped['group:' + group if group else pid]
            item['matching_offers'] = len(members)
            item['alternative_ids'] = [other for other in members if other != pid][:3]
            item['alternatives_more'] = len(members) > 4
            if group:
                item['alternative_offers'] = [{k: items[other].get(k) for k in ('id', 'price', 'source_file')}
                                             for other in item['alternative_ids']]
                item['offers_lookup'] = {'product_group': group, 'reuse_hard': hard, 'limit': 10, 'offset': 0}
            selected.append(item)
        coverage = pool.quality(hard.get('price_field'))
        warnings = []
        if any(coverage['missing'].values()): warnings.append('incomplete_metadata')
        if coverage['incomplete_files']: warnings.append('partial_source_imports')
        if coverage.get('price', {}).get('unusable'):
            warnings.append('unknown_or_complex_prices_excluded_from_budget' if {'minimum', 'maximum'} & set(hard) else 'some_prices_unusable_for_comparison')
        if coverage.get('price', {}).get('basis_conflicts'):
            warnings.append('legacy_price_role_conflicts_use_verified_source_labels')
        if hard.get('latest') and coverage.get('sources_without_version'): warnings.append('unknown_source_versions_excluded')
        if hard.get('latest') and coverage['ambiguous_quote_series']: warnings.append('ambiguous_quote_series_excluded')
        if hard.get('latest') and coverage['partial_newest_quotes']: warnings.append('newest_source_incomplete')
        if hard.get('exclude_categories'): warnings.append('unknown_categories_excluded_from_negative_filter')
        if hard.get('attributes'): warnings.append('unknown_attributes_do_not_satisfy_hard_conditions')
        if hard.get('price_field') and any(not {'currency', 'unit', 'tax', 'shipping'} <= set(item['offer_terms'].get(hard['price_field'], {}).get('terms', {})) for item in selected):
            warnings.append('some_quote_terms_unknown')
        clipped = expansion_clipped or any(r['total'] > r['returned'] for r in reports) or len(representatives) > limit
        if clipped: warnings.append('bounded_candidates_not_exhaustive')
        if any(item['alternatives_more'] for item in selected): warnings.append('group_offers_clipped_use_paginated_search')
        return {'items': selected, 'candidate_count': len(items), 'group_count': len(representatives), 'limit': limit,
                'lanes': reports, 'hard': hard, 'coverage': coverage, 'truncated': clipped, 'warnings': warnings,
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
    finally:
        pool._freshness_snapshot = previous_cache
