import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as SheetImage
from PIL import Image


TOOL = Path(__file__).resolve().parents[1] / "extract.py"


class ExtractTest(unittest.TestCase):
    def test_preserves_values_and_allows_missing_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            picture = root / "product.png"
            Image.new("RGB", (20, 20), "white").save(picture)
            book = Workbook()
            sheet = book.active
            sheet.title = "产品"
            sheet.append(["序号", "产品名称", "代理价", "参考价B", "功能特点", "产品图片", "包装图"])
            sheet.append([1, "A1 产品", "更新中", 12.4, "第一行\n第二行", None, None])
            sheet.append([2, "B2 产品", None, 20, "", None, None])
            sheet.add_image(SheetImage(str(picture)), "F2")
            source = root / "input.xlsx"
            book.save(source)
            work = root / "work"
            result = subprocess.run(
                [sys.executable, str(TOOL), "--input", str(source), "--work-dir", str(work)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            items = json.loads((work / "catalog-data.json").read_text(encoding="utf-8"))
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["agent_price"], "更新中")
            self.assertEqual(items[0]["reference_price_b"], 12.4)
            self.assertEqual(items[0]["features"], "第一行\n第二行")
            self.assertEqual(items[0]["source_cells"]["产品名称"], "B2")
            self.assertEqual(items[0]["source_cells"]["包装图"], "G2")
            self.assertTrue(Path(items[0]["product_image"]).is_file())
            self.assertIsNone(items[0]["package_image"])
            self.assertIsNone(items[1]["agent_price"])
            self.assertIsNone(items[1]["product_image"])


if __name__ == "__main__":
    unittest.main()
