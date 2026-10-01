"""Task references and bounded arguments for the existing product capability."""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "catalog_tool") not in sys.path:
    sys.path.insert(0, str(ROOT / "catalog_tool"))
from pool import make_parser
from pool_commands import execute
from pool_owner import pool_lock, operation
from pool_selection import Selections
from pool_store import Pool
from present import invocation
from workspace_tool.processes import OwnedProcessGroup

ALLOWED = frozenset({"add", "files", "inspect", "render", "observe", "import", "annotate", "enrich", "vocabulary", "source-update", "link", "offer-terms", "derive", "quality", "review-queue", "retrieve", "history", "search", "show", "stats", "facets", "choose", "selection", "sessions", "rename"})
MUTATING = ALLOWED - {"files", "quality", "review-queue", "history", "search", "show", "stats", "facets", "selection", "sessions", "retrieve"}


class PoolAdapter:
    def __init__(self, store, root, work_dir, project=ROOT):
        self.store, self.root, self.work_dir, self.project = store, Path(root).resolve(), Path(work_dir).resolve(), Path(project).resolve()

    def execute(self, tid, command, payload, request_id):
        if command not in ALLOWED:
            raise ValueError("这个操作不能从页面直接执行。")
        self.store.snapshot(tid)
        values = payload.get("args", [])
        if not isinstance(values, list) or len(values) > 250 or any(not isinstance(x, str) or len(x) > 4000 for x in values):
            raise ValueError("Invalid bounded command arguments")
        argv = [command, *values]
        if command == "add":
            ref = self.store.ref(tid, "input", payload.get("input_id"))
            argv.insert(1, ref["path"])
        json_inputs = payload.get("json", {})
        if not isinstance(json_inputs, dict) or set(json_inputs) - {"records", "map", "plan"}:
            raise ValueError("Invalid structured input")
        directory = self.work_dir / "tasks" / tid / "tool-inputs"
        directory.mkdir(parents=True, exist_ok=True)
        trusted_paths = set()
        if command == "observe":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 1048576:
                raise ValueError("Visual observation needs bounded plain text in payload.text")
            target = directory / ("observation-" + hashlib.sha256(text.encode()).hexdigest() + ".local.txt")
            target.write_text(text, encoding="utf-8")
            trusted_paths.add(target.resolve())
            argv += ["--text-file", str(target)]
        for name, value in json_inputs.items():
            raw = json.dumps(value, ensure_ascii=False).encode()
            if len(raw) > 1048576:
                raise ValueError("Structured input too large")
            target = directory / (name + "-" + hashlib.sha256(raw).hexdigest() + ".local.json")
            target.write_bytes(raw)
            trusted_paths.add(target.resolve())
            argv += ["--" + name, str(target)]
        try:
            args = make_parser().parse_args(argv)
        except SystemExit:
            raise ValueError("命令参数不正确，请按工具说明检查。") from None
        args.index_dir, args.config = self.root, None
        for name, value in vars(args).items():
            if isinstance(value, Path) and name not in ("index_dir", "config"):
                if command == "add" and name == "input":
                    continue
                if value.resolve() not in trusted_paths:
                    raise ValueError("Files must use current-task input references or structured JSON")
        if getattr(args, "session", None):
            self.store.ref(tid, "session", args.session)
        result = execute(args, operation_id=(tid + ":" + request_id) if command in MUTATING else None)
        if command == "choose":
            sid = result["session_id"]
            self.store.add_ref(tid, "session", sid, {"session_id": sid})
            return {"session_id": sid, "candidates": result["candidates"], "next": "ui.present products with this session_id"}
        return result

    def state(self, tid, session_id, *, verify=False):
        self.store.ref(tid, "session", session_id)
        with pool_lock(self.root):
            pool = Pool(self.root)
            try:
                choices = Selections(pool)
                if verify:
                    choices.verify(session_id)
                return choices.state(session_id, include_items=True)
            finally:
                pool.close()

    def select(self, tid, session_id, ids, revision, request_id):
        self.store.ref(tid, "session", session_id)
        with pool_lock(self.root):
            pool = Pool(self.root)
            try:
                choices = Selections(pool)
                choices.verify(session_id)
                return choices.select(session_id, ids, revision, operation_id=tid + ":" + request_id)
            finally:
                pool.close()

    def image(self, tid, session_id, product_id):
        state = self.state(tid, session_id, verify=True)
        item = next((p for p in state["items"] if p["id"] == product_id), None)
        if not item or not item.get("image"):
            raise ValueError("这款商品没有图片。")
        path = (self.root / item["image"]).resolve()
        if not path.is_relative_to(self.root / "assets") or not path.is_file():
            raise ValueError("商品图片不可用，请重新核对资料。")
        return path

    def reopen(self, tid, session_id, request_id):
        self.store.ref(tid, "session", session_id)
        with pool_lock(self.root):
            pool = Pool(self.root)
            try:
                choices = Selections(pool)
                def clone():
                    choices.verify(session_id)
                    old = choices.state(session_id, include_items=True)
                    fresh = choices.create([p["id"] for p in old["items"]], old["price_fields"], old["title"])
                    if old["selected_ids"]:
                        choices.select(fresh["session_id"], old["selected_ids"], 0)
                    return {"session_id": fresh["session_id"]}
                result = operation(pool.db, tid + ":" + request_id, {"reopen": session_id}, clone)
            finally:
                pool.close()
        self.store.add_ref(tid, "session", result["session_id"], result)
        return result

    async def export(self, tid, session_id, revision, request_id):
        self.store.ref(tid, "session", session_id)
        def seal():
            with pool_lock(self.root):
                pool = Pool(self.root)
                try:
                    choices = Selections(pool)
                    state = choices.state(session_id)
                    if state["revision"] != revision:
                        raise ValueError("勾选已经变化，请核对后再生成。")
                    return choices.seal(session_id, operation_id=tid + ":" + request_id + ":seal")
                finally:
                    pool.close()
        state = await asyncio.to_thread(seal)
        if os.name != "nt":
            raise ValueError("当前图册生成需要 Windows。")
        import shutil
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise ValueError("没有找到 PowerShell，请让 Codex 检查安装。")
        output = self.project / "outputs" / "workspace" / tid / "产品图册.pptx"
        output.parent.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(index_dir=self.root, ids=state["selected_ids"], price_fields=state["price_fields"], input=None,
                                  map=None, config=None, output=output, style=None, runtime_root=None, skill_dir=None)
        process = await asyncio.create_subprocess_exec(shell, "-NoProfile", "-NonInteractive", "-EncodedCommand",
            invocation(args, ROOT / "catalog_tool/pool.py"), cwd=self.project,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            group = OwnedProcessGroup(process.pid)
        except OSError:
            process.terminate(); await process.wait()
            raise
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 240)
        except BaseException:
            group.close()
            if process.returncode is None:
                process.terminate()
                await process.wait()
            raise
        finally:
            group.close()
        if process.returncode != 0 or not output.is_file():
            raise ValueError("图册还没生成成功，已保留原来的文件。请让 Codex 检查资料或生成环境。")
        # The shared pipeline verifies source/price/image invariants before replacing output.
        return {"path": str(output), "display_name": output.name, "verification_ref": "pool:" + session_id + ":" + str(revision) + ":job:" + request_id}
