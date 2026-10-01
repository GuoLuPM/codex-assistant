"""Stream uploads to local task storage, validate format and decompression budget."""
import hashlib
import mimetypes
import re
import secrets
import zipfile
from pathlib import Path

UPLOAD_LIMIT = 64 * 1024 * 1024
ALLOWED = {".xlsx", ".xls", ".pdf", ".pptx", ".docx", ".csv", ".txt", ".md", ".json", ".png", ".jpg", ".jpeg", ".webp"}


def validate_file(path, suffix):
    with path.open("rb") as stream:
        magic = stream.read(16)
    if suffix in (".xlsx", ".pptx", ".docx"):
        if not zipfile.is_zipfile(path):
            raise ValueError("这个文件的格式与名字不一致，请重新保存后添加。")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 256 * 1024 * 1024 or any(e.flag_bits & 1 for e in entries):
                raise ValueError("这份文件过大或已加密，请分成小一些的文件。")
            required = {".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml", ".docx": "word/document.xml"}[suffix]
            if required not in archive.namelist():
                raise ValueError("文件内容与扩展名不一致。")
    elif suffix == ".pdf" and not magic.startswith(b"%PDF-"):
        raise ValueError("这不是有效的 PDF 文件。")
    elif suffix == ".xls" and not magic.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ValueError("请用 Excel 另存为 XLSX 后添加。")
    elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
        from PIL import Image
        try:
            with Image.open(path) as image:
                if image.width * image.height > 40000000:
                    raise ValueError("图片太大，请缩小后再添加。")
                image.verify()
        except OSError:
            raise ValueError("这张图片无法读取。") from None


async def accept_upload(store, work_dir, tid, stream, name, *, limit=UPLOAD_LIMIT):
    store.snapshot(tid)
    if (not isinstance(name, str) or not 1 <= len(name) <= 180 or any(c in name for c in '/\\:\x00')
            or name in (".", "..") or name.endswith((".", " ")) or re.match(r"^(CON|PRN|AUX|NUL|COM\d|LPT\d)(\.|$)", name, re.I)):
        raise ValueError("这个文件名不能使用，请换个名字再添加。")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("暂时读不了这种文件。可以提供 Excel、PDF、Word、PPT、文字或图片。")
    directory = Path(work_dir).resolve() / "tasks" / tid / "inputs"
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / (".incoming-" + secrets.token_hex(12))
    size, hasher = 0, hashlib.sha256()
    try:
        with temp.open("xb") as output:
            async for chunk in stream:
                size += len(chunk)
                if size > limit:
                    raise ValueError(f"文件超过 {limit // (1024*1024)} MB，请分成小文件。")
                hasher.update(chunk); output.write(chunk)
        if not size:
            raise ValueError("这份文件是空的。")
        validate_file(temp, suffix)
        sha = hasher.hexdigest()
        ident = "input_" + sha
        old = next((x for x in store.refs(tid, "input") if x["id"] == ident), None)
        if old:
            return {k: old[k] for k in ("input_id", "display_name", "sha256", "media_type")}
        target = directory / sha / name
        target.parent.mkdir(exist_ok=True)
        temp.replace(target)
        item = {"input_id": ident, "display_name": name, "sha256": sha,
                "media_type": mimetypes.guess_type(name)[0] or "application/octet-stream", "path": str(target)}
        store.add_ref(tid, "input", ident, item)
        return {k: v for k, v in item.items() if k != "path"}
    finally:
        if temp.exists():
            temp.unlink()
