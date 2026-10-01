"""Launch/reuse/inspect the local workspace from Codex. No browser credentials printed to logs."""
import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "catalog_tool"))
from pool_owner import pool_lock


def control(state, action, *, method="GET"):
    from urllib.parse import urlsplit
    url = state["origin"]
    if urlsplit(url).hostname != "127.0.0.1" or urlsplit(url).scheme != "http":
        raise ValueError("Invalid local service address")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url + "/control/" + action, data=b"{}" if method == "POST" else None,
                                    headers={"X-Workspace-Control": state["control_token"], "Content-Type": "application/json"}, method=method)
    with opener.open(request, timeout=2) as response:
        return json.load(response)


def launch(directory, pool_dir=None, codex_bin=None):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    state_file = directory / "server.local.json"
    with pool_lock(directory):
        if state_file.is_file():
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            try:
                return control(saved, "open", method="POST")
            except OSError:
                # Confirm absence before replacing a registry for a live process.
                if process_alive(saved.get("pid")):
                    raise ValueError("工作台还在启动或连接异常，请稍后检查 status。") from None
        command = [sys.executable, str(Path(__file__)), "--work-dir", str(directory)]
        if pool_dir: command += ["--pool-dir", str(Path(pool_dir).resolve())]
        if codex_bin: command += ["--codex-bin", str(Path(codex_bin).resolve())]
        launch_id = secrets.token_hex(16)
        command += ["--launch-id", launch_id, "serve"]
        with (directory / "server.log").open("ab") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError("工作台没能启动，请让 Codex 检查安装。")
            if state_file.is_file():
                saved = json.loads(state_file.read_text(encoding="utf-8"))
                # Windows virtualenv redirectors may spawn a different Python PID.
                if saved.get("launch_id") == launch_id:
                    try: return control(saved, "open", method="POST")
                    except OSError: pass
            time.sleep(.15)
        raise ValueError("工作台启动时间较长，请稍后检查 status。")


def process_alive(pid):
    if type(pid) is not int or pid <= 0: return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False


async def serve(args):
    import uvicorn
    from workspace_tool.auth import LocalAuth
    from workspace_tool.app import create_app
    from workspace_tool.service import Workspace
    directory = args.work_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # A retained bound socket makes port choice race-free.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0)); sock.listen(128)
    host = f"127.0.0.1:{sock.getsockname()[1]}"
    auth = LocalAuth(host)
    service = Workspace(directory, host, pool_root=args.pool_dir, codex_bin=args.codex_bin)
    app = create_app(service, auth, ROOT / "workspace_tool/web/dist")
    config = uvicorn.Config(app, host="127.0.0.1", port=sock.getsockname()[1], log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    service.shutdown = lambda: setattr(server, "should_exit", True)
    state_file = directory / "server.local.json"
    state = {"pid": os.getpid(), "launch_id": args.launch_id, "origin": "http://" + host, "control_token": auth.control_token, "protocol": 1}
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8"); temporary.replace(state_file)
    try:
        await server.serve(sockets=[sock])
    finally:
        sock.close()
        if state_file.is_file() and json.loads(state_file.read_text())["pid"] == os.getpid(): state_file.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-dir", type=Path, default=ROOT / "data/workspace")
    p.add_argument("--pool-dir", type=Path)
    p.add_argument("--codex-bin", type=Path)
    p.add_argument("--launch-id", default=None, help=argparse.SUPPRESS)
    p.add_argument("command", choices=["open", "status", "stop", "serve"])
    args = p.parse_args(argv)
    if args.command == "serve":
        asyncio.run(serve(args)); return 0
    try:
        if args.command == "open":
            result = launch(args.work_dir, args.pool_dir, args.codex_bin)
        else:
            state_file = args.work_dir / "server.local.json"
            if not state_file.is_file():
                result = {"running": False}
            else:
                saved = json.loads(state_file.read_text(encoding="utf-8"))
                result = control(saved, args.command, method="POST" if args.command == "stop" else "GET")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
