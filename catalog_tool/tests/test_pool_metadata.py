import json
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pool_store import Pool


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        book = Workbook()
        book.active.append(['名称', '零售价', '产品说明'])
        book.active.append(['远行保温杯', 120, '品牌：远行\n容量：0.5L\n材质：不锈钢'])
        book.active.append(['茶点礼盒', '80/100', '两种规格，附礼盒'])
        source = self.root / 'products.xlsx'
        book.save(source)
        self.pool = Pool(self.root / 'pool')
        self.file = self.pool.add(source)['file_id']
        self.ids = {r['name']: r['id'] for r in self.pool.search()['items']}

    def tearDown(self):
        self.pool.close()
        self.tmp.cleanup()

    def fact(self, field, value, quote, **extra):
        return dict(field=field, value=value, quote=quote, origin='source', reason='核对商品原文', **extra)

    def test_evidence_revision_and_atomic_batch_preserve_original(self):
        pid = self.ids['远行保温杯']
        before = self.pool.db.execute('select payload_hash from pool_members where product_id=?', (pid,)).fetchone()[0]
        entry = {'id': pid, 'revision': 0, 'facts': [self.fact('brand', '远行', '远行')]}
        self.assertEqual(self.pool.enrich([entry])['updated'], 1)
        self.assertEqual(self.pool.enrich([entry])['unchanged'], 1)
        self.assertEqual(self.pool.details([pid])[0]['metadata']['revision'], 1)
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.pool.enrich([{'id': pid, 'revision': 0, 'facts': [self.fact('supplier', '远行', '远行')]}])
        bad = {'id': self.ids['茶点礼盒'], 'revision': 0, 'facts': [self.fact('brand', '远行', '远行')]}
        with self.assertRaisesRegex(ValueError, 'own source'):
            self.pool.enrich([{'id': pid, 'revision': 1, 'facts': [self.fact('supplier', '远行', '远行')]}, bad])
        self.assertNotIn('supplier', self.pool.details([pid])[0]['metadata']['facts'])
        self.assertEqual(self.pool.db.execute('select payload_hash from pool_members where product_id=?', (pid,)).fetchone()[0], before)
        self.assertEqual(self.pool.db.execute("select count(*) from pool_events where entity_type='product'", ()).fetchone()[0], 1)

    def test_units_need_real_quantity_and_derivation_is_idempotent(self):
        pid = self.ids['远行保温杯']
        self.pool.enrich([{'id': pid, 'revision': 0, 'facts': [self.fact('attr.capacity', 500, '容量：0.5L', unit='ml')]}])
        with self.assertRaisesRegex(ValueError, 'quantity'):
            self.pool.enrich([{'id': pid, 'revision': 1, 'facts': [self.fact('attr.capacity', 800, '容量：0.5L', unit='ml')]}])
        first = self.pool.derive()
        self.assertGreaterEqual(first['updated'], 1)
        self.assertEqual(self.pool.derive()['updated'], 0)
        facts = self.pool.details([pid])[0]['metadata']['facts']
        self.assertEqual(facts['brand']['value'], '远行')
        self.assertEqual(facts['attr.capacity']['number'], 500)
        self.assertEqual(facts['attr.capacity']['unit'], 'ml')
        self.assertFalse(self.pool.details([self.ids['茶点礼盒']])[0]['metadata']['facts'].get('brand'))

    def test_quality_queue_and_aliases_are_bounded_and_portable(self):
        quality = self.pool.quality('零售价')
        self.assertEqual(quality['products'], 2)
        self.assertEqual(quality['price']['numeric'], 1)
        self.assertEqual(quality['price']['unusable'], 1)
        queue = self.pool.review_queue(field='brand', limit=1)
        self.assertEqual(queue['total'], 2)
        self.assertEqual(len(queue['items']), 1)
        self.pool.vocabulary([{'kind': 'query', 'terms': ['便携电源', '移动电源'], 'reason': '等价叫法'}])
        self.assertEqual(set(self.pool.aliases('query', '便携电源')), {'便携电源', '移动电源'})
        self.pool.close()
        self.pool = Pool(self.root / 'pool')
        self.assertEqual(set(self.pool.aliases('query', '移动电源')), {'便携电源', '移动电源'})

    def test_incorrect_overlay_can_be_cleared_with_audited_idempotent_change(self):
        pid = self.ids['远行保温杯']
        self.pool.enrich([{'id': pid, 'revision': 0, 'facts': [self.fact('brand', '远行', '远行')]}])
        change = {'id': pid, 'revision': 1, 'facts': [self.fact('brand', None, '远行')]}
        self.assertEqual(self.pool.enrich([change])['updated'], 1)
        self.assertNotIn('brand', self.pool.details([pid])[0]['metadata']['facts'])
        self.assertEqual(self.pool.enrich([change])['unchanged'], 1)
        self.assertEqual(self.pool.meta.history('product', pid)['total'], 2)


if __name__ == '__main__':
    unittest.main()
