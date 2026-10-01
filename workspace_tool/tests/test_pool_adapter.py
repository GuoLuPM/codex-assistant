import json
import sys
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "catalog_tool"))
from pool_store import Pool
from pool_selection import Selections
from pool_commands import execute
from pool import make_parser


class PoolSeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = self.root / "synthetic.xlsx"
        book = Workbook(); book.active.append(["名称", "零售价", "功能特点"])
        book.active.append(["合成礼盒", 88, "礼盒包装"]); book.save(source)
        self.pool = Pool(self.root / "pool")
        self.pool.add(source)
        self.pid = self.pool.search()["items"][0]["id"]
        self.choices = Selections(self.pool)

    def tearDown(self):
        self.pool.close(); self.tmp.cleanup()

    def test_choose_receipt_is_same_transaction_and_retry_returns_same_session(self):
        one = self.choices.create([self.pid], ["retail_price"], "礼盒", operation_id="choose-1")
        two = self.choices.create([self.pid], ["retail_price"], "礼盒", operation_id="choose-1")
        self.assertEqual(one, two)
        self.assertEqual(self.choices.recent()["total"], 1)
        with self.assertRaisesRegex(ValueError, "operation"):
            self.choices.create([self.pid], ["retail_price"], "changed", operation_id="choose-1")

    def test_selection_retry_never_toggles_twice_and_old_revision_rejected(self):
        sid = self.choices.create([self.pid], ["retail_price"])["session_id"]
        one = self.choices.select(sid, [self.pid], 0, operation_id="pick-1")
        two = self.choices.select(sid, [self.pid], 0, operation_id="pick-1")
        self.assertEqual(one, two)
        self.assertEqual(two["revision"], 1)
        with self.assertRaises(ValueError): self.choices.select(sid, [], 0, operation_id="pick-2")
        self.assertIsNone(self.pool.db.execute("SELECT 1 FROM pool_operations WHERE operation_id='pick-2'").fetchone())

    def test_shared_executor_matches_cli_price_contract_and_duplicate_add(self):
        parser = make_parser()
        args = parser.parse_args(["--index-dir", str(self.root / "pool"), "search", "--price-field", "retail_price", "--max-price", "90"])
        result = execute(args)
        self.assertEqual(result["items"][0]["price"]["value"], 88)
        args = parser.parse_args(["--index-dir", str(self.root / "pool"), "add", str(self.root / "synthetic.xlsx")])
        self.assertEqual(execute(args)["status"], "duplicate")

    def test_receipt_failure_rolls_back_nested_business_write(self):
        self.pool.db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON pool_operations BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END")
        self.pool.db.commit()
        with self.assertRaises(Exception):
            self.choices.create([self.pid], ["retail_price"], operation_id="failed")
        self.assertEqual(self.choices.recent()["total"], 0)

    def test_shared_executor_retries_effect_after_lost_response(self):
        args = make_parser().parse_args(["--index-dir", str(self.root / "pool"), "choose", "--ids", self.pid, "--price-fields", "retail_price"])
        one = execute(args, operation_id="lost")
        two = execute(args, operation_id="lost")
        self.assertEqual(one, two)
        self.assertEqual(self.choices.recent()["total"], 1)
