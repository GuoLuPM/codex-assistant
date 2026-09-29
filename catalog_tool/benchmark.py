"""Reproducible synthetic scale check. Prints one JSON result; keeps no reports."""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from openpyxl import Workbook
from catalog_store import Catalog


def benchmark(rows):
    with tempfile.TemporaryDirectory(prefix="catalog-benchmark-") as folder:
        root = Path(folder)
        source = root / "synthetic.xlsx"
        book = Workbook(write_only=True)
        sheet = book.create_sheet("products")
        sheet.append(["产品名称", "供货价", "零售价", "品类", "功能特点"])
        for i in range(rows):
            sheet.append([f"样本{i:06d} {'耳机' if i % 5 == 0 else '商品'}", i % 300 + 1,
                          i % 300 + 20, f"类别{i % 100}", "仅用于测试的合成描述"])
        book.save(source)
        store = Catalog(root / "index")
        try:
            cold = store.index([source])
            warm = store.index([source])
            timings, payload = [], None
            for _ in range(30):
                start = time.perf_counter()
                payload = store.search(query="耳机", price_field="agent_price", minimum=80, maximum=150)
                timings.append((time.perf_counter() - start) * 1000)
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            return {"synthetic_rows": rows, "categories": 100, "index_ms": cold["elapsed_ms"],
                    "unchanged_refresh_ms": warm["elapsed_ms"], "search_p50_ms": round(statistics.median(timings), 2),
                    "search_p95_ms": round(sorted(timings)[28], 2), "matches": payload["total"],
                    "returned": len(payload["items"]), "response_chars": len(encoded),
                    "index_mb": round((root / "index/catalog.sqlite3").stat().st_size / 1024**2, 2)}
        finally:
            store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    args = parser.parse_args()
    if not 100 <= args.rows <= 100000:
        parser.error("rows must be 100..100000")
    print(json.dumps(benchmark(args.rows), ensure_ascii=False, separators=(",", ":")))
