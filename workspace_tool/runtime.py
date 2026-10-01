"""Small asynchronous adapter for Codex App Server's public stdio protocol.

One owned child, one reader, correlated requests, independently answered server
requests. Never reads auth files and never connects to the desktop's private socket.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from workspace_tool.processes import OwnedProcessGroup


class RuntimeError(Exception):
    def __init__(self, message, *, code=None, data=None):
        super().__init__(message)
        self.code, self.data = code, data


REQUEST_METHODS = frozenset({
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
    "item/permissions/requestApproval", "item/tool/requestUserInput",
})


def find_codex(explicit: str | None = None) -> str:
    desktop = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    installs = sorted(desktop.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True) if os.name == "nt" and desktop.is_dir() else []
    candidates = [explicit] if explicit else [
        os.environ.get("CODEX_CLI_PATH"),
        *map(str, installs),
        str(desktop / "codex.exe") if os.name == "nt" else None,
        shutil.which("codex"),
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return str(Path(value).resolve())
    raise RuntimeError("还没找到 Codex。请先安装并登录 Codex，再打开工作台。", code="codex_missing")


def choose_model(models: list[dict], profile: str) -> str:
    if profile not in ("normal", "low"):
        raise RuntimeError("不认识这个档位。", code="invalid_profile")
    family = "sol" if profile == "normal" else "terra"
    candidates = [m.get("model", m.get("id", "")) for m in models if not m.get("hidden")]
    candidates = [m for m in candidates if re.fullmatch(r"gpt-\d+(?:\.\d+)*-" + family, m)]
    if not candidates:
        raise RuntimeError(f"当前账号没有可用的 {family.capitalize()} 模型，请在 Codex 中检查。", code="model_unavailable")
    return max(candidates, key=lambda m: tuple(int(n) for n in re.findall(r"\d+", m)))


class CodexRuntime:
    def __init__(self):
        self.process = None
        self._group = None
        self._ready = False
        self._closed = False
        self._next_id = 0
        self._pending = {}
        self._server_requests = {}
        self._events = asyncio.Queue()
        self._write_lock = asyncio.Lock()
        self._reader = self._stderr = None
        self.capabilities = {}
        self.config = {}

    async def start(self, config=None) -> dict:
        if self.process:
            raise RuntimeError("Codex connection already started")
        self.config = config or {}
        command = self.config.get("command") or [find_codex(self.config.get("codex_bin")), "app-server", "--listen", "stdio://"]
        # Use per-thread/turn tier fields; never modify the user's global config.
        if "command" not in self.config:
            for key, value in self.config.get("overrides", {}).items():
                command += ["-c", f"{key}={value}"]
        self.process = await asyncio.create_subprocess_exec(
            *command, cwd=self.config.get("cwd"),
            env={k: v for k, v in os.environ.items() if k not in {
                "CODEX_APP_TOOLS_PIPE_PATH", "CODEX_THREAD_ID", "CODEX_SESSION_ID",
                "CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
            }},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=8 * 1024 * 1024,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            self._group = OwnedProcessGroup(self.process.pid)
        except OSError:
            self.process.terminate(); await self.process.wait()
            raise
        self._reader = asyncio.create_task(self._read_loop())
        self._stderr = asyncio.create_task(self._drain_stderr())
        try:
            initialized = await self.request("initialize", {
                "clientInfo": {"name": "codex_assistant_workspace", "title": "Assistant", "version": "0.4.0"},
                "capabilities": {"experimentalApi": False},
            }, _initial=True)
            await self._send({"method": "initialized"})
            self._ready = True
            models, cursor = [], None
            for _ in range(20):
                page = await self.request("model/list", {"limit": 100, **({"cursor": cursor} if cursor else {})})
                models.extend(page.get("data", []))
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            else:
                raise RuntimeError("Codex model list exceeded pagination limit")
            account = await self.request("account/read", {"refreshToken": False})
            # Never forward account email, account IDs, or credentials to the UI.
            self.capabilities = {
                "version": initialized.get("userAgent", "unknown"), "models": models,
                "logged_in": bool(account.get("account")),
                "account_type": (account.get("account") or {}).get("type"),
                "transport": "stdio", "service_tier": "default",
                "request_methods": sorted(REQUEST_METHODS), "access_verified": False,
            }
            return self.capabilities
        except BaseException:
            await self.close()
            raise

    async def _send(self, message):
        if self._closed or not self.process or self.process.returncode is not None:
            raise RuntimeError("Codex 连接已关闭。", code="connection_closed")
        async with self._write_lock:
            try:
                self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionError) as exc:
                raise RuntimeError("Codex 连接已断开。", code="connection_closed") from exc

    async def request(self, method, params=None, *, timeout=45, _initial=False):
        if not self._ready and not _initial:
            raise RuntimeError("Codex 尚未连接。", code="not_initialized")
        self._next_id += 1
        ident = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        try:
            await self._send({"id": ident, "method": method, "params": params or {}})
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            # No retry: the peer may already have accepted a turn or effect.
            raise RuntimeError("Codex 暂时没有回应，请检查连接。", code="request_timeout") from exc
        finally:
            self._pending.pop(ident, None)

    async def _read_loop(self):
        failure = "Codex 连接已断开。"
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("invalid protocol object")
                if "method" in message:
                    method, params = message["method"], message.get("params") or {}
                    event = {"kind": method, "thread_id": params.get("threadId") or (params.get("thread") or {}).get("id"),
                             "turn_id": params.get("turnId") or (params.get("turn") or {}).get("id"),
                             "item_id": params.get("itemId") or (params.get("item") or {}).get("id"), "payload": params}
                    if "id" in message:
                        event["request_id"] = message["id"]
                        if method not in REQUEST_METHODS:
                            await self._send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported server request; no approval granted"}})
                            event["kind"] = "unsupported_request"
                        else:
                            self._server_requests[message["id"]] = message
                    await self._events.put(event)
                elif (future := self._pending.get(message.get("id"))) is not None and not future.done():
                    if "error" in message:
                        error = message["error"]
                        future.set_exception(RuntimeError(error.get("message", "Codex error"), code=error.get("code"), data=error.get("data")))
                    else:
                        future.set_result(message.get("result"))
        except (ValueError, OSError, asyncio.LimitOverrunError) as exc:
            failure = f"Codex 协议连接异常：{type(exc).__name__}"
        finally:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(RuntimeError(failure, code="connection_closed"))
            await self._events.put({"kind": "connection_closed", "payload": {"message": failure}})

    async def _drain_stderr(self):
        # Stderr can contain local paths or tool output. Keep it out of protocol,
        # browser, logs, and exceptions; diagnostics come from structured events.
        while await self.process.stderr.read(8192):
            pass

    async def start_thread(self, cwd, profile="normal", *, instructions=None, config=None):
        model = choose_model(self.capabilities.get("models", []), profile)
        if not self.capabilities.get("logged_in"):
            raise RuntimeError("请先在 Codex 中登录，然后重新连接。", code="login_required")
        params = {"cwd": str(cwd), "model": model, "serviceTier": "default",
                  "approvalPolicy": "on-request", "sandbox": "workspace-write"}
        if instructions:
            params["developerInstructions"] = instructions
        if config:
            params["config"] = config
        result = await self.request("thread/start", params)
        return result["thread"]["id"]

    async def resume_thread(self, thread_id, **options):
        return await self.request("thread/resume", {"threadId": thread_id, "serviceTier": "default", **options})

    async def start_turn(self, request):
        text = request.get("text", "")
        inputs = [{"type": "text", "text": text}] if text else []
        inputs += request.get("inputs", [])
        params = {"threadId": request["thread_id"], "input": inputs, "serviceTier": "default"}
        if request.get("model_profile"):
            params["model"] = choose_model(self.capabilities["models"], request["model_profile"])
        result = await self.request("turn/start", params)
        return result["turn"]["id"]

    async def answer(self, request_id, answer):
        if request_id not in self._server_requests:
            raise RuntimeError("这个问题已经结束，请刷新当前任务。", code="request_expired")
        method = self._server_requests[request_id]["method"]
        if method.endswith("requestUserInput"):
            valid = isinstance(answer, dict) and isinstance(answer.get("answers"), dict)
        elif method == "item/permissions/requestApproval":
            valid = isinstance(answer, dict) and isinstance(answer.get("permissions"), dict)
        else:
            valid = isinstance(answer, dict) and answer.get("decision") in ("accept", "decline", "cancel", "acceptForSession")
        if not valid:
            raise RuntimeError("回答格式不正确。", code="invalid_answer")
        await self._send({"id": request_id, "result": answer})
        del self._server_requests[request_id]

    async def interrupt(self, thread_id, turn_id):
        return await self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})

    async def events(self):
        while True:
            event = await self._events.get()
            yield event
            if event["kind"] == "connection_closed":
                return

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                if self._group: self._group.close()
                if self.process.returncode is None: self.process.terminate()
                await self.process.wait()
            finally:
                if self._group: self._group.close()
        for task in (self._reader, self._stderr):
            if task:
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(RuntimeError("Codex connection closed", code="connection_closed"))
