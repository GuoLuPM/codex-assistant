"""Compare generated slide text with extracted workbook values."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from pptx import Presentation


def compact(value):
    return re.sub(r"\s+", "", str(value))


def verify(work_dir: Path, output: Path):
    products = {item["row"]: item for item in json.loads((work_dir / "catalog-data.json").read_text(encoding="utf-8"))}
    manifest = json.loads((work_dir / "catalog-manifest.json").read_text(encoding="utf-8"))
    deck = Presentation(output)
    assert len(deck.slides) == len(manifest), "Slide count differs from manifest"
    parts = defaultdict(list)
    for meta, slide in zip(manifest, deck.slides):
        item = products[meta["source_row"]]
        texts = [shape.text for shape in slide.shapes if shape.has_text_frame and shape.text]
        title = re.sub(r"\s+", " ", item["name"]).strip()
        assert texts[0] == title, (meta, "product name")
        assert f"序号 {item['serial'] if item['serial'] is not None else '未提供'}" in texts, (meta, "serial")
        agent = "未提供" if item["agent_price"] is None or not str(item["agent_price"]).strip() else str(item["agent_price"])
        reference = "未提供" if item["reference_price_b"] is None or not str(item["reference_price_b"]).strip() else str(item["reference_price_b"])
        assert texts[-1] == f"代理价  {agent}\n参考价B  {reference}", (meta, "price")
        parts[item["row"]].append(texts[-2])

    for row, item in products.items():
        original = "表格未提供功能特点" if not item["features"] or not str(item["features"]).strip() else str(item["features"]).strip()
        assert compact("".join(parts[row])) == compact(original), (row, "features")
    return len(products), len(deck.slides)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    products, slides = verify(args.work_dir.resolve(), args.output.resolve())
    print(f"Verified {products} products across {slides} slides")
