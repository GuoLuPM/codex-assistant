import argparse
import base64
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from present import add_parser, invocation


class PresentationAdapterTests(unittest.TestCase):
    def parse(self, *args):
        parser = argparse.ArgumentParser()
        parser.add_argument("--index-dir", type=Path, default=Path(".catalog-index"))
        parser.add_argument("--config", type=Path)
        add_parser(parser.add_subparsers())
        return parser.parse_args(["ppt", *args])

    def test_paths_prices_and_arrays_are_data_in_encoded_powershell(self):
        args = self.parse("--ids", "p_1", "p_2", "--price-fields", "成本价", "报价'$(literal)",
                          "--output", "outputs/报价 ' $ (空格).pptx")
        script = base64.b64decode(invocation(args)).decode("utf-16-le")
        encoded = re.search(r"FromBase64String\('([^']+)'\)", script).group(1)
        parameters = json.loads(base64.b64decode(encoded).decode("utf-8"))["parameters"]
        self.assertEqual(parameters["ProductIds"], args.ids)
        self.assertEqual(parameters["PriceFields"], args.price_fields)
        self.assertEqual(parameters["OutputFile"], str(args.output.resolve()))
        self.assertNotIn("$(literal)", script)

    def test_map_cannot_be_applied_to_an_existing_id_selection(self):
        with self.assertRaisesRegex(ValueError, "requires --input"):
            invocation(self.parse("--ids", "p_1", "--map", "source.local.json"))


if __name__ == "__main__":
    unittest.main()
