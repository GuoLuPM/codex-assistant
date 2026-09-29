"""Extract catalog rows and embedded pictures from an XLSX workbook."""

import argparse
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter


HEADERS = ["序号", "产品名称", "代理价", "参考价B", "功能特点", "产品图片", "包装图"]
IMAGE_KEYS = {"产品图片": "product_image", "包装图": "package_image"}


def extract(source: Path, work_dir: Path) -> list[dict]:
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        raise ValueError(f"XLSX file not found: {source}")
    work_dir.mkdir(parents=True, exist_ok=True)
    image_dir = work_dir / "images"
    image_dir.mkdir(exist_ok=True)

    book = openpyxl.load_workbook(source, data_only=True)
    candidates = []
    for sheet in book:
        for row in range(1, min(sheet.max_row, 15) + 1):
            headers = {str(sheet.cell(row, col).value).strip(): col for col in range(1, sheet.max_column + 1)
                       if sheet.cell(row, col).value is not None}
            if all(header in headers for header in HEADERS):
                candidates.append((sheet, row, headers))
    if len(candidates) != 1:
        raise ValueError(f"Expected one sheet with headers {HEADERS}; found {len(candidates)}")
    sheet, header_row, columns = candidates[0]

    by_row = {}
    for row in range(header_row + 1, sheet.max_row + 1):
        cells = {header: sheet.cell(row, columns[header]).value for header in HEADERS[:5]}
        if all(value is None or str(value).strip() == "" for value in cells.values()):
            continue
        if cells["产品名称"] is None or str(cells["产品名称"]).strip() == "":
            raise ValueError(f"Missing product name at {sheet.title}!B{row}")
        by_row[row] = {
            "sheet": sheet.title,
            "row": row,
            "serial": cells["序号"],
            "name": cells["产品名称"],
            "agent_price": cells["代理价"],
            "reference_price_b": cells["参考价B"],
            "features": cells["功能特点"],
            "source_cells": {header: f"{get_column_letter(columns[header])}{row}" for header in HEADERS},
            "product_image": None,
            "package_image": None,
            "product_image_sha256": None,
            "package_image_sha256": None,
        }

    for image in sheet._images:
        row = image.anchor._from.row + 1
        column = image.anchor._from.col + 1
        key = next((IMAGE_KEYS[name] for name, col in columns.items()
                    if col == column and name in IMAGE_KEYS), None)
        if row not in by_row or key is None:
            continue
        if by_row[row][key] is not None:
            raise ValueError(f"Duplicate {key} at {sheet.title} row {row}")
        data = image._data()
        suffix = "jpg" if image.format.lower() == "jpeg" else image.format.lower()
        if suffix not in {"jpg", "png"}:
            raise ValueError(f"Unsupported image format at {sheet.title} row {row}: {suffix}")
        path = image_dir / f"row-{row}-{key}.{suffix}"
        path.write_bytes(data)
        by_row[row][key] = str(path.resolve())
        by_row[row][f"{key}_sha256"] = hashlib.sha256(data).hexdigest()

    items = list(by_row.values())
    (work_dir / "catalog-data.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    items = extract(args.input.resolve(), args.work_dir.resolve())
    print(f"Extracted {len(items)} products")
