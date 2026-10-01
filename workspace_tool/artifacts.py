"""Only validated, task-owned files become downloadable artifacts."""
import hashlib
from pathlib import Path
from workspace_tool.uploads import validate_file


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish_artifact(store, tid, path, allowed_dir, verification_ref):
    path, allowed_dir = Path(path), Path(allowed_dir).resolve()
    if not verification_ref or not path.is_file() or not path.resolve().is_relative_to(allowed_dir):
        raise ValueError("成品还没通过检查。")
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
        raise ValueError("成品路径不能使用链接。")
    if path.suffix.lower() not in {".pptx", ".xlsx", ".docx", ".pdf", ".txt", ".md", ".csv"} or not 0 < path.stat().st_size <= 128*1024*1024:
        raise ValueError("成品类型或大小不适合下载。")
    validate_file(path, path.suffix.lower())
    if path.suffix.lower() in {".txt", ".md", ".csv"}:
        path.read_text(encoding="utf-8-sig")
    signature = sha(path)
    ident = "artifact_" + hashlib.sha256((signature + verification_ref + path.name).encode()).hexdigest()
    value = {"artifact_id": ident, "path": str(path.resolve()), "display_name": path.name,
             "sha256": signature, "verification_ref": verification_ref}
    store.add_ref(tid, "artifact", ident, value)
    store.record(tid, "artifact", {k: v for k, v in value.items() if k != "path"}, key="artifact:" + ident)
    return {k: v for k, v in value.items() if k != "path"}


def artifact_file(store, tid, ident):
    value = store.ref(tid, "artifact", ident)
    if not Path(value["path"]).is_file() or sha(value["path"]) != value["sha256"]:
        raise ValueError("这份成品已经变化，请打开最新生成的文件。")
    return value
