import json
import sys
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pool_store import Pool


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        book = Workbook()
        book.active.append(['名称', '零售价', '规格'])
        for row in [('移动电源 A', 80, '自带线'), ('便携电源 B', 180, '自带线'),
                    ('保温杯', 120, '容量：0.5L\n不锈钢'), ('零食礼盒', 90, '礼盒'), ('未知物品', '80/100', '礼盒')]:
            book.active.append(list(row))
        source = self.root / 'products.xlsx'
        book.save(source)
        self.pool = Pool(self.root / 'pool')
        self.pool.add(source)
        self.ids = {x['name']: x['id'] for x in self.pool.search()['items']}
        entries = []
        for name, category in [('移动电源 A', '数码/移动电源'), ('便携电源 B', '数码/移动电源'), ('保温杯', '家居/杯壶'), ('零食礼盒', '食品/零食')]:
            entries.append({'id': self.ids[name], 'revision': 0, 'facts': [{'field': 'category', 'value': category, 'quote': name, 'origin': 'inferred', 'reason': '按品名判断产品类别'}]})
        self.pool.enrich(entries)
        self.pool.derive()

    def tearDown(self):
        self.pool.close()
        self.tmp.cleanup()

    def test_shared_budget_survives_synonyms_and_tag_fallback(self):
        self.pool.vocabulary([{'kind': 'query', 'terms': ['充电宝', '移动电源', '便携电源'], 'reason': '常用等价称呼'}])
        result = self.pool.retrieve({'version': 1, 'hard': {'price_field': '零售价', 'maximum': 100},
                                     'lanes': [{'query': '充电宝'}, {'tags': ['occasion:新年']}], 'limit': 10})
        self.assertEqual([p['id'] for p in result['items']], [self.ids['移动电源 A']])
        self.assertIn('自带线', result['items'][0]['facts_excerpt'])
        self.assertTrue(any(lane['query'].get('query') == '移动电源' for lane in result['lanes']))
        self.assertEqual(result['coverage']['price']['unusable'], 1)
        self.assertIn('incomplete_metadata', result['warnings'])
        with self.assertRaisesRegex(ValueError, 'lane'):
            self.pool.retrieve({'version': 1, 'hard': {'price_field': '零售价', 'maximum': 100}, 'lanes': [{'maximum': 200}]})

    def test_negative_categories_and_converted_attribute_do_not_admit_unknowns(self):
        result = self.pool.retrieve({'version': 1, 'hard': {'price_field': '零售价', 'maximum': 150,
                                      'exclude_categories': ['数码', '食品'],
                                      'attributes': [{'field': 'attr.capacity', 'minimum': 0.5, 'unit': 'L'}]}, 'lanes': [{}]})
        self.assertEqual([p['id'] for p in result['items']], [self.ids['保温杯']])
        self.assertIn('容量：0.5L', result['items'][0]['facts_excerpt'])
        too_big = self.pool.search(constraints={'attributes': [{'field': 'attr.capacity', 'minimum': 501, 'unit': 'ml'}]})
        self.assertEqual(too_big['total'], 0)

    def test_search_facets_details_share_enriched_metadata_and_result_bounds(self):
        pid = self.ids['保温杯']
        profile = self.pool.details([pid])[0]['metadata']
        self.pool.enrich([{'id': pid, 'revision': profile['revision'], 'facts': [{'field': 'brand', 'value': '保温杯', 'quote': '保温杯', 'origin': 'source', 'reason': '合成品牌字段示例'}]}])
        self.assertEqual(self.pool.search(brand='保温杯')['total'], 1)
        self.assertEqual(self.pool.facets('brand')['items'][0]['value'], '保温杯')
        self.assertEqual(self.pool.search(category='食品')['total'], 1)
        result = self.pool.retrieve({'version': 1, 'hard': {}, 'lanes': [{}], 'limit': 2, 'per_lane': 2})
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(result['truncated'])
        self.assertNotEqual(result['items'][0]['category'], result['items'][1]['category'])
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.pool.retrieve({'version': 1, 'hard': {}, 'lanes': [{}], 'limit': 999})

    def test_legacy_misclassified_price_needs_an_explicit_source_label(self):
        # Reproduce a database created by the old broad price aliases. Source
        # values and labels are unchanged; the stored role is the old mistake.
        pid = self.ids['移动电源 A']
        row = self.pool.db.execute('SELECT pk,payload FROM products WHERE id=?', (pid,)).fetchone()
        payload = json.loads(row['payload'])
        payload['prices']['reference_price_b'] = payload['prices'].pop('retail_price')
        with self.pool.db:
            self.pool.db.execute('UPDATE products SET payload=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), pid))
            self.pool.db.execute("UPDATE prices SET field='reference_price_b' WHERE product_pk=? AND field='retail_price'", (row['pk'],))
        plan = {'version': 1, 'hard': {'price_field': 'reference_price_b', 'maximum': 100}, 'lanes': [{}]}
        result = self.pool.retrieve(plan)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['coverage']['price']['basis_conflicts'], 1)
        self.assertIn('legacy_price_role_conflicts_use_verified_source_labels', result['warnings'])
        plan['hard']['price_labels'] = ['零售价']
        verified = self.pool.retrieve(plan)['items']
        self.assertEqual([p['id'] for p in verified], [pid])
        self.assertEqual(verified[0]['price']['label'], '零售价')


if __name__ == '__main__': unittest.main()
