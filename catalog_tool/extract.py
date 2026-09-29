"""Read product tables without changing source values or inventing missing fields."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path


ALIASES = {
    "serial": ["序号", "编号"],
    "name": ["产品名称", "商品名称", "品名", "名称"],
    "model": ["型号", "产品型号", "SKU", "货号", "物料编码"],
    "agent_price": ["代理价", "供货价", "出货价", "采购价", "进货价", "成本价"],
    "reference_price_b": ["参考价B", "参考价", "市场参考价", "建议零售价", "零售价", "销售价", "售价"],
    "features": ["功能特点", "产品特点", "产品功能", "卖点", "规格参数", "产品规格", "规格", "参数", "描述", "说明"],
    "category": ["品类", "类目", "类别", "分类", "产品类别"],
    "brand": ["品牌"],
    "supplier": ["供应商", "厂家"],
    "product_image": ["产品图片", "产品图", "商品图片", "图片"],
    "package_image": ["包装图", "包装图片"],
}
LEGACY_LABELS = {"serial": "序号", "name": "产品名称", "agent_price": "代理价",
                 "reference_price_b": "参考价B", "features": "功能特点",
                 "product_image": "产品图片", "package_image": "包装图"}


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalized_header(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def json_value(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def read_products(source, image_dir, schema=None):
    import openpyxl
    from openpyxl.utils import get_column_letter

    source, image_dir = Path(source).resolve(), Path(image_dir).resolve()
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        raise ValueError(f"XLSX file not found: {source}")
    schema = schema or {}
    aliases = {**ALIASES, **schema.get("aliases", {})}
    aliases = {key: {normalized_header(x) for x in values} for key, values in aliases.items()}
    before = file_hash(source)
    book = openpyxl.load_workbook(source, data_only=True)
    formulas = openpyxl.load_workbook(source, data_only=False, read_only=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    records, skipped = [], []
    try:
        for sheet in book:
            if schema.get("sheets") and sheet.title not in schema["sheets"]:
                continue
            candidates = []
            for row in range(1, min(sheet.max_row, schema.get("header_search_rows", 20)) + 1):
                headers = {col: str(sheet.cell(row, col).value).strip() for col in range(1, sheet.max_column + 1)
                           if sheet.cell(row, col).value is not None}
                columns = {key: [col for col, label in headers.items() if normalized_header(label) in names]
                           for key, names in aliases.items()}
                if columns["name"]:
                    candidates.append((row, headers, columns))
            if not candidates:
                skipped.append(sheet.title)
                continue
            if len(candidates) != 1:
                raise ValueError(f"Ambiguous table headers in {source.name}/{sheet.title}; configure sheets/header_search_rows")
            header_row, headers, columns = candidates[0]
            if len({normalized_header(label) for label in headers.values()}) != len(headers):
                raise ValueError(f"Duplicate column labels in {sheet.title}; use unique source headers")
            for key, cols in columns.items():
                if len(cols) > 1 and key != "features":
                    raise ValueError(f"Multiple columns for {key} in {sheet.title}; configure aliases explicitly")
            by_row, identities = {}, Counter()
            # Read formula markers once; random access to read-only sheets would be quadratic.
            formula_cells = {cell.coordinate for line in formulas[sheet.title].iter_rows(min_row=header_row + 1)
                             for cell in line if cell.data_type == "f"}
            for row in range(header_row + 1, sheet.max_row + 1):
                raw = {label: json_value(sheet.cell(row, col).value) for col, label in headers.items()}
                if all(value is None or str(value).strip() == "" for value in raw.values()):
                    continue
                def value(key):
                    return json_value(sheet.cell(row, columns[key][0]).value) if columns.get(key) else None
                name = value("name")
                if name is None or not str(name).strip():
                    raise ValueError(f"Missing product name: {source.name}/{sheet.title} row {row}")
                name = str(name)
                identity = str(value("model") or name)
                occurrence = identities[identity]
                identities[identity] += 1
                product_id = "p_" + hashlib.sha256(
                    json.dumps([str(source).casefold(), sheet.title, identity, occurrence], ensure_ascii=False).encode()
                ).hexdigest()[:16]
                description_cols = sorted(set(columns["features"] + [
                    col for col, label in headers.items() if label in schema.get("detail_fields", [])]))
                descriptions = [(headers[col], json_value(sheet.cell(row, col).value)) for col in description_cols]
                descriptions = [(label, text) for label, text in descriptions if text is not None and str(text).strip()]
                plain_description = len(descriptions) == 1 and any(
                    headers[col] == descriptions[0][0] for col in columns["features"])
                features = (str(descriptions[0][1]) if plain_description else
                            "\n".join(f"{label}：\n{text}" for label, text in descriptions))
                source_cells = {label: f"{get_column_letter(col)}{row}" for col, label in headers.items()}
                for key, label in LEGACY_LABELS.items():
                    if columns.get(key):
                        source_cells[label] = f"{get_column_letter(columns[key][0])}{row}"
                prices = {}
                for key in ["agent_price", "reference_price_b"]:
                    if columns[key]:
                        prices[key] = {"label": headers[columns[key][0]], "value": value(key)}
                canonical_price_cols = {col for key in ["agent_price", "reference_price_b"] for col in columns[key]}
                for col, label in headers.items():
                    if col not in canonical_price_cols and (label.endswith("价") or label.endswith("价格")):
                        prices[label] = {"label": label, "value": json_value(sheet.cell(row, col).value)}
                issues = [f"公式无缓存值:{coord}" for coord in source_cells.values()
                          if coord in formula_cells and sheet[coord].value is None]
                item = {"id": product_id, "source_path": str(source), "source_file": source.name,
                        "source_hash": before, "sheet": sheet.title, "row": row, "name": name,
                        "serial": value("serial"), "model": value("model"), "features": features,
                        "agent_price": value("agent_price"), "reference_price_b": value("reference_price_b"),
                        "prices": prices, "source_cells": source_cells, "raw_fields": raw,
                        "category": value("category"), "brand": value("brand"), "supplier": value("supplier"),
                        "issues": sorted(set(issues)), "product_image": None, "package_image": None,
                        "product_image_sha256": None, "package_image_sha256": None}
                by_row[row] = item
            for image in sheet._images:
                if not hasattr(image.anchor, "_from"):
                    raise ValueError(f"Unsupported image anchor in {sheet.title}")
                row, col = image.anchor._from.row + 1, image.anchor._from.col + 1
                key = next((key for key in ["product_image", "package_image"] if col in columns[key]), None)
                if row not in by_row or key is None:
                    continue
                if by_row[row][key] is not None:
                    raise ValueError(f"Multiple {key} images at {sheet.title} row {row}")
                data = image._data()
                suffix = "jpg" if image.format.lower() == "jpeg" else image.format.lower()
                if suffix not in {"jpg", "png"}:
                    raise ValueError(f"Unsupported image format: {suffix} at {sheet.title}/{row}")
                digest = hashlib.sha256(data).hexdigest()
                target = image_dir / f"{digest}.{suffix}"
                if not target.exists() or file_hash(target) != digest:
                    target.write_bytes(data)
                by_row[row][key], by_row[row][f"{key}_sha256"] = str(target), digest
            records.extend(by_row.values())
    finally:
        book.close()
        formulas.close()
    if not records:
        raise ValueError(f"No recognized product table in {source.name}; configure header aliases")
    if file_hash(source) != before:
        raise ValueError(f"Source changed while reading: {source.name}")
    return records, skipped


def extract(source: Path, work_dir: Path) -> list[dict]:
    work_dir.mkdir(parents=True, exist_ok=True)
    items, _ = read_products(source, work_dir / "images")
    (work_dir / "catalog-data.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    print(f"Extracted {len(extract(args.input.resolve(), args.work_dir.resolve()))} products")
