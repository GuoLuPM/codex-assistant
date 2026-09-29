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
    "agent_price": ["代理价"],
    "supply_price": ["供货价", "供货价格", "供价", "出货价"],
    "purchase_price": ["采购价", "进货价"],
    "cost_price": ["成本价"],
    "reference_price_b": ["参考价B"],
    "reference_price": ["参考价", "市场参考价"],
    "retail_price": ["建议零售价", "零售价", "零售价格"],
    "sale_price": ["销售价", "售价"],
    "features": ["功能特点", "产品特点", "产品功能", "卖点", "规格参数", "产品规格", "规格", "参数", "描述", "说明"],
    "category": ["品类", "类目", "类别", "分类", "产品类别"],
    "brand": ["品牌"],
    "supplier": ["供应商", "厂家"],
    "product_image": ["产品图片", "产品图", "商品图片", "图片"],
    "package_image": ["包装图", "包装图片"],
}
PRICE_ROLES = tuple(key for key in ALIASES if key.endswith('_price') or key == 'reference_price_b')
LEGACY_LABELS = {"serial": "序号", "name": "产品名称", "agent_price": "代理价",
                 "reference_price_b": "参考价B", "features": "功能特点",
                 "product_image": "产品图片", "package_image": "包装图"}


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalized_header(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


PRICE_LABEL_ROLES = {normalized_header(label): role for role in PRICE_ROLES for label in ALIASES[role]}


def price_basis(label):
    """Only recognize explicit commercial labels; unknown labels remain unknown."""
    return PRICE_LABEL_ROLES.get(normalized_header(label))


def json_value(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _automatic_plans(sheet, schema):
    from openpyxl.utils import get_column_letter
    populated = [cell for cell in sheet._cells.values() if cell.value is not None]
    if not populated:
        return []
    last_row, last_col = max(c.row for c in populated), max(c.column for c in populated)
    aliases = {**ALIASES, **schema.get("aliases", {})}
    aliases = {key: {normalized_header(x) for x in values} for key, values in aliases.items()}
    claimed = {}
    for role, values in schema.get('aliases', {}).items():
        if role not in PRICE_ROLES: continue
        for value in values:
            label = normalized_header(value)
            if label in claimed and claimed[label] != role:
                raise ValueError('Conflicting explicit price aliases; use a coordinate mapping')
            claimed[label] = role
    for label, role in claimed.items():
        for other in PRICE_ROLES:
            if other != role: aliases[other].discard(label)
    candidates = []
    for row in range(1, min(last_row, schema.get("header_search_rows", 20)) + 1):
        headers = {col: str(sheet.cell(row, col).value).strip() for col in range(1, last_col + 1)
                   if sheet.cell(row, col).value is not None}
        columns = {key: [col for col, label in headers.items() if normalized_header(label) in names]
                   for key, names in aliases.items()}
        if columns["name"]:
            candidates.append((row, headers, columns))
    if not candidates:
        return []
    if len(candidates) != 1:
        raise ValueError(f"Ambiguous table headers in {sheet.title}; inspect and provide an explicit mapping")
    header, headers, columns = candidates[0]
    if len({normalized_header(label) for label in headers.values()}) != len(headers):
        raise ValueError(f"Duplicate column labels in {sheet.title}; provide a coordinate mapping")
    for key, cols in columns.items():
        if len(cols) > 1 and key != "features":
            raise ValueError(f"Multiple columns for {key} in {sheet.title}; provide a coordinate mapping")
    fields = {key: get_column_letter(columns[key][0]) for key in
              ("name", "model", "serial", "category", "brand", "supplier") if columns.get(key)}
    prices = {key: get_column_letter(columns[key][0]) for key in PRICE_ROLES if columns[key]}
    used = {col for key in PRICE_ROLES for col in columns[key]}
    prices.update({label: get_column_letter(col) for col, label in headers.items()
                   if col not in used and (label.endswith("价") or label.endswith("价格"))})
    details = sorted(set(columns["features"] + [col for col, label in headers.items() if label in schema.get("detail_fields", [])]))
    details = [{"column": get_column_letter(col), "plain": len(details) == 1 and col in columns["features"]} for col in details]
    return [{"sheet": sheet.title, "range": f"A{header + 1}:{get_column_letter(last_col)}{last_row}",
             "header_row": header, "fields": fields, "prices": prices, "details": details,
             "images": {role: [get_column_letter(col) for col in columns[role]] for role in ("product_image", "package_image")},
             "automatic": True}]


def _project(record, source, source_hash, identities, image_reader):
    from layouts import empty
    from openpyxl.utils import get_column_letter
    from workbook_images import CELL_IMAGE

    plan, sheet = record.plan, record.values.sheet
    field_cells, issues, cell_errors = {}, [], set()

    def collect(ref):
        cells = record.cells(ref)
        values, seen = [], set()
        for cell in cells:
            value = json_value(cell.value)
            if cell.data_type == "e":
                cell_errors.add(cell.coordinate)
                issues.append(f"单元格错误:{cell.coordinate}")
            if cell.coordinate in image_reader.formulas and cell.value is None:
                if not CELL_IMAGE.fullmatch(image_reader.formulas[cell.coordinate]):
                    issues.append(f"公式无缓存值:{cell.coordinate}")
            if not empty(value):
                key = json.dumps(value, ensure_ascii=False)
                if key not in seen:
                    values.append(value)
                    seen.add(key)
        return values, [cell.coordinate for cell in cells]

    def scalar(ref, key):
        values, cells = collect(ref)
        field_cells[key] = cells
        if len(values) > 1:
            raise ValueError(f"Conflicting {key} values at {sheet.title}!{','.join(cells)}; choose row-level records")
        return values[0] if values else None

    values = {key: scalar(ref, key) for key, ref in plan["fields"].items()}
    prices = {key: {"label": record.label(ref), "value": scalar(ref, key)} for key, ref in plan.get("prices", {}).items()}
    for key, price in prices.items():
        if cell_errors.intersection(field_cells[key]):
            price["error"] = "spreadsheet_error"
    details, source_cells, raw_fields = [], {}, {}
    refs = list(plan["fields"].values()) + list(plan.get("prices", {}).values()) + plan.get("details", [])
    raw_refs = refs if record.block else [get_column_letter(col) for col in range(record.left, record.right + 1)]
    for ref in raw_refs:
        raw, cells = collect(ref)
        label = record.label(ref)
        if label in source_cells and source_cells[label] != (cells[0] if len(cells) == 1 else cells):
            label += f" [{cells[0]}]"
        raw_fields[label] = raw[0] if len(raw) == 1 else raw or None
        source_cells[label] = cells[0] if len(cells) == 1 else cells
    if all(empty(value) for value in values.values()) and all(p["value"] is None for p in prices.values()) and all(value is None for value in raw_fields.values()):
        return None
    if empty(values.get("name")):
        raise ValueError(f"Missing product name: {source.name}/{sheet.title} row {record.top}")
    name = str(values["name"])
    if CELL_IMAGE.fullmatch(name.strip()):
        raise ValueError("Mapped product name points to an image formula")
    for ref in plan.get("details", []):
        texts, cells = collect(ref)
        field_cells.setdefault("features", []).extend(cell for cell in cells if cell not in field_cells.get("features", []))
        if texts:
            text = "\n".join(str(value) for value in texts)
            details.append(text if isinstance(ref, dict) and ref.get("plain") else f"{record.label(ref)}：\n{text}")
    identity = str(values.get("model") or name)
    if not empty(values.get("variant")):
        identity = json.dumps([identity, values["variant"]], ensure_ascii=False)
    occurrence = identities[identity]
    identities[identity] += 1
    product_id = "p_" + hashlib.sha256(json.dumps(
        [str(source).casefold(), sheet.title, identity, occurrence], ensure_ascii=False).encode()).hexdigest()[:16]
    for key, label in LEGACY_LABELS.items():
        if key in field_cells and label not in source_cells:
            cells = field_cells[key]
            source_cells[label] = cells[0] if len(cells) == 1 else cells
    item = {"id": product_id, "source_path": str(source), "source_file": source.name, "source_hash": source_hash,
            "sheet": sheet.title, "row": record.top, "end_row": record.bottom, "name": name,
            **{key: values.get(key) for key in ("serial", "model", "variant", "category", "brand", "supplier")},
            "features": "\n".join(details), "prices": prices,
            "agent_price": prices.get("agent_price", {}).get("value"),
            "reference_price_b": prices.get("reference_price_b", {}).get("value"),
            "raw_fields": raw_fields, "source_cells": source_cells, "field_cells": field_cells, "images": [],
            "product_image": None, "package_image": None,
            "product_image_sha256": None, "package_image_sha256": None}
    if plan.get("category_from_sheet"):
        item["category"], item["category_origin"] = sheet.title, "sheet"
    mapped_refs = refs + [ref for refs in plan.get("images", {}).values() for ref in refs]
    mapped_cells = {cell.coordinate for ref in mapped_refs for cell in record.cells(ref)}
    item["unmapped_fields"] = [label for label, cells in source_cells.items()
                               if raw_fields.get(label) is not None and not set(cells if isinstance(cells, list) else [cells]) <= mapped_cells]
    for role, refs in plan.get("images", {}).items():
        if role not in {"product_image", "package_image"}:
            raise ValueError(f"Unknown image role: {role}")
        seen = set()
        for ref in refs:
            for cell in record.image_cells(ref):
                pictures, image_issues = image_reader.read(cell)
                issues.extend(image_issues)
                for picture in pictures:
                    if picture["sha256"] in seen:
                        continue
                    seen.add(picture["sha256"])
                    item["images"].append({**picture, "role": role})
                    if item[role] is None:
                        item[role], item[f"{role}_sha256"] = picture["path"], picture["sha256"]
        if len(seen) > 1:
            issues.append(f"同记录多图:{role}:{len(seen)};首张用于主图,其余保留")
    item["issues"] = sorted(set(issues))
    return item


def read_products(source, image_dir, schema=None):
    import openpyxl
    from collections import defaultdict
    from layouts import records_for_plan, plan_bounds
    from workbook_images import WorkbookPackage, ImageReader

    source, image_dir = Path(source).resolve(), Path(image_dir).resolve()
    if not source.is_file() or source.suffix.lower() != ".xlsx":
        raise ValueError(f"XLSX file not found: {source}")
    schema = schema or {}
    before = file_hash(source)
    book = openpyxl.load_workbook(source, data_only=True)
    package = WorkbookPackage(source)
    records, skipped, identities, seen_records = [], [], defaultdict(Counter), set()
    try:
        mapping = schema.get("mapping")
        if mapping:
            if mapping.get("version") != 1:
                raise ValueError("Unsupported source mapping version")
            if set(mapping) - {"version", "tables", "blocks", "ignore_sheets"}:
                raise ValueError("Unknown mapping options; use the documented coordinate contract")
            plans = [(dict(plan, automatic=False), False) for plan in mapping.get("tables", [])]
            plans += [(dict(plan, automatic=False), True) for plan in mapping.get("blocks", [])]
            selected = {plan["sheet"] for plan, _ in plans}
            skipped = mapping.get("ignore_sheets", [])
            missing = set(book.sheetnames) - selected - set(skipped)
            if missing:
                raise ValueError(f"Unmapped sheets: {sorted(missing)}; inspect or explicitly list ignore_sheets")
            if selected - set(book.sheetnames):
                raise ValueError("Mapped sheet missing; inspect and remap")
        else:
            plans = []
            for sheet in book:
                sheet_plans = _automatic_plans(sheet, schema) if not schema.get("sheets") or sheet.title in schema["sheets"] else []
                if not sheet_plans:
                    skipped.append(sheet.title)
                plans.extend((plan, False) for plan in sheet_plans)
        readers, rectangles = {}, defaultdict(list)
        for plan, block in plans:
            sheet = book[plan["sheet"]]
            bounds = plan_bounds(sheet, plan, block)
            left, top, right, bottom = bounds
            if any(left <= r and right >= l and top <= b and bottom >= t for l, t, r, b in rectangles[sheet.title]):
                raise ValueError(f"Overlapping mapped ranges in {sheet.title}; use disjoint data regions")
            rectangles[sheet.title].append(bounds)
            if sheet.title not in readers:
                formulas, _ = package.sheet_info(sheet.title)
                readers[sheet.title] = ImageReader(sheet, package, image_dir, formulas)
            for record in records_for_plan(sheet, plan, block):
                key = (sheet.title, record.top, record.left)
                if key in seen_records:
                    raise ValueError(f"Overlapping mapped record: {key}")
                seen_records.add(key)
                item = _project(record, source, before, identities[sheet.title], readers[sheet.title])
                if item:
                    records.append(item)
    finally:
        book.close()
        package.close()
    if not records:
        raise ValueError(f"No recognized product table in {source.name}; inspect and provide a mapping")
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
