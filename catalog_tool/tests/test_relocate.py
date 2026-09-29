import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_store import Catalog


class RelocateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.old = self.base / "old"
        self.new = self.base / "new"
        (self.old / "data").mkdir(parents=True)
        (self.old / ".catalog-index/maps").mkdir(parents=True)
        self.source = self.old / "data/example.xlsx"
        book = Workbook()
        book.active.append(["项目", "成交额"])
        book.active.append(["样品", 88])
        book.save(self.source)
        self.mapping = self.old / ".catalog-index/maps/example.local.json"
        self.mapping.write_text(json.dumps({"version": 1, "tables": [{
            "sheet": "Sheet", "range": "A2:B2", "header_row": 1, "extend_rows": True,
            "fields": {"name": "A"}, "prices": {"quote": "B"},
            "expect": {"A1": "项目", "B1": "成交额"}}]}), encoding="utf-8")
        store = Catalog(self.old / ".catalog-index")
        store.index([self.source], mapping_path=self.mapping)
        self.old_id = store.search()["items"][0]["id"]
        store.close()
        self.old.rename(self.new)
        self.store = Catalog(self.new / ".catalog-index")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_preview_and_apply_relocate_maps_then_regenerate_ids(self):
        preview = self.store.relocate(self.old, self.new)
        self.assertEqual(preview["sources"], 1)
        self.assertFalse(preview["applied"])
        self.assertEqual(self.store.sources()["items"][0]["path"], str(self.source))
        self.store.relocate(self.old, self.new, apply=True)
        result = self.store.search(price_field="quote")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["price"]["value"], 88)
        self.assertNotEqual(result["items"][0]["id"], self.old_id)
        self.assertEqual(self.store.stale_sources(), [])
        self.assertEqual(self.store.index()["skipped"], 1)
        item = self.store.details([result["items"][0]["id"]])[0]
        self.assertEqual(item["source_path"], str(self.new / "data/example.xlsx"))

    def test_changed_content_or_map_aborts_without_replacing_registration(self):
        target = self.new / "data/example.xlsx"
        original = target.read_bytes()
        target.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "hash|changed"):
            self.store.relocate(self.old, self.new, apply=True)
        target.write_bytes(original)
        changed_map = self.new / ".catalog-index/maps/example.local.json"
        mapping = json.loads(changed_map.read_text())
        mapping["tables"][0]["prices"] = {"another_quote": "B"}
        changed_map.write_text(json.dumps(mapping), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "config|mapping"):
            self.store.relocate(self.old, self.new, apply=True)
        self.assertEqual(self.store.sources()["items"][0]["path"], str(self.source))

    def test_mid_write_failure_rolls_back_old_records_and_fts(self):
        with patch.object(self.store, "_insert", side_effect=ValueError("injected failure")):
            with self.assertRaisesRegex(ValueError, "injected failure"):
                self.store.relocate(self.old, self.new, apply=True)
        self.assertEqual(self.store.db.execute("SELECT id FROM products").fetchone()[0], self.old_id)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM products_fts").fetchone()[0], 1)

    def test_existing_destination_registration_is_not_overwritten(self):
        self.store.index([self.new / "data/example.xlsx"], mapping_path=self.new / ".catalog-index/maps/example.local.json")
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.store.relocate(self.old, self.new, apply=True)
        self.assertEqual(self.store.stats()["sources"], 2)


if __name__ == "__main__":
    unittest.main()
