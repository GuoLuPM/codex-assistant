"""Real-model test utilities; never connect a rehearsal to a user's workspace.

Authentication stays with native Codex. Only synthetic inputs, transient threads,
and the task-scoped assistant MCP are allowed. No global settings are changed.
"""
import asyncio
import json
import re
import socket
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from workspace_tool.runtime import CodexRuntime, RuntimeError, find_codex

ROOT = Path(__file__).resolve().parents[1]
ISOLATION_CONFIG = {
    **{"features." + key: False for key in (
        "plugins", "remote_plugin", "apps", "computer_use", "browser_use", "browser_use_external",
        "hooks", "memories", "multi_agent", "shell_tool", "unified_exec", "view_image",
        "image_generation", "skill_search", "workspace_dependencies",
    )},
    "web_search": "disabled", "project_doc_max_bytes": 0,
}
WORKSPACE_TOOLS = {"capabilities_find", "capabilities_describe", "capabilities_call", "ui_present"}


def rehearsal_directory(parent):
    parent = Path(parent).resolve()
    if not parent.is_relative_to(ROOT / "data"):
        raise ValueError("验收目录必须在项目 data 内，不能连接日常工作台。")
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run-", dir=parent))


class RehearsalRuntime(CodexRuntime):
    def __init__(self):
        super().__init__()
        self._rehearsal_threads = {}

    async def start(self, config=None):
        config = dict(config or {})
        if config.get("command"):
            raise RuntimeError("验收不能覆盖原生启动命令。")
        command = [find_codex(config.get("codex_bin")), "app-server", "--listen", "stdio://"]
        for key, value in ISOLATION_CONFIG.items():
            if key.startswith("features."):
                # --disable rejects unknown flags. --strict-config would also reject
                # unrelated legacy keys in the user's config, which we must not edit.
                command += ["--disable", key.split(".", 1)[1]]
            else:
                command += ["-c", key + "=" + json.dumps(value)]
        # Disable native hooks/plugins before starting any thread, not afterwards.
        return await super().start({**config, "command": command})

    async def request(self, method, params=None, **kwargs):
        params = dict(params or {})
        if method in {"thread/resume", "thread/fork"}:
            raise RuntimeError("合成验收只用新建的临时会话，不能恢复日常聊天。")
        if method == "thread/start":
            cfg = (await super().request("config/read", {"cwd": params["cwd"], "includeLayers": False}))["config"]
            incoming = params.get("config") or {}
            isolated = {k: v for k, v in incoming.items() if k in {
                "mcp_servers.assistant_workspace", "sandbox_workspace_write.writable_roots",
            }}
            servers = cfg.get("mcp_servers") or {}
            for name in servers:
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
                    raise RuntimeError("无法安全关闭个人 MCP；验收已停止。")
                isolated["mcp_servers." + name + ".enabled"] = False
            # Only a bridge explicitly supplied by this test can be enabled.
            if "mcp_servers.assistant_workspace" in isolated:
                isolated["mcp_servers.assistant_workspace.enabled"] = True
            isolated.update(ISOLATION_CONFIG)
            params.update(ephemeral=True, config=isolated, sandbox="read-only")
            result = await super().request(method, params, **kwargs)
            thread = result["thread"]
            if thread.get("ephemeral") is not True or thread.get("path"):
                # Do not send even one model turn to an unsupported persistent thread.
                await super().request("thread/archive", {"threadId": thread["id"]})
                raise RuntimeError("原生 Codex 未确认临时会话；已归档空记录并停止验收。")
            self._rehearsal_threads[thread["id"]] = {
                "cwd": params["cwd"], "workspace": "mcp_servers.assistant_workspace" in isolated,
            }
            return result
        if method == "turn/start":
            thread = params.get("threadId")
            if thread not in self._rehearsal_threads:
                raise RuntimeError("验收不能使用其他会话。")
            await self.verify_tools(thread)
        return await super().request(method, params, **kwargs)

    async def verify_tools(self, thread):
        cursor, found = None, False
        for _ in range(20):
            page = await super().request("mcpServerStatus/list", {
                "threadId": thread, "limit": 100, **({"cursor": cursor} if cursor else {}),
            })
            for server in page["data"]:
                if server["name"] == "assistant_workspace" and self._rehearsal_threads[thread]["workspace"]:
                    # Native inventory may qualify dictionary keys; each Tool has its raw name.
                    names = {tool.get("name", name) for name, tool in server["tools"].items()}
                    if (names != WORKSPACE_TOOLS or server.get("runtimeStatus") != "connected"
                            or server.get("toolsError") or server.get("pluginId")):
                        raise RuntimeError("验收工具不完整或超出范围；已停止。")
                    found = True
                elif (server.get("runtimeStatus") != "disabled" or server.get("tools")
                      or server.get("resources") or server.get("resourceTemplates")):
                    raise RuntimeError("检测到验收以外的工具；尚未启动模型回合。")
            cursor = page.get("nextCursor")
            if not cursor:
                if self._rehearsal_threads[thread]["workspace"] and not found:
                    raise RuntimeError("验收工具未就绪；已停止。")
                return
        raise RuntimeError("无法完整核对验收工具；已停止。")

    async def verify_history(self):
        for thread, state in self._rehearsal_threads.items():
            for archived in (False, True):
                cursor = None
                for _ in range(20):
                    page = await super().request("thread/list", {"cwd": state["cwd"], "archived": archived,
                        "limit": 100, **({"cursor": cursor} if cursor else {})})
                    if any(t["id"] == thread for t in page["data"]):
                        raise RuntimeError("验收会话意外进入原生历史，验收不通过。")
                    cursor = page.get("nextCursor")
                    if not cursor: break
                else: raise RuntimeError("无法完整核对原生历史；验收不通过。")


@asynccontextmanager
async def rehearsal_workspace(parent, *, codex_bin=None):
    """Own an isolated service and its socket; never attach to a live user service."""
    import uvicorn
    from workspace_tool.app import create_app
    from workspace_tool.auth import LocalAuth
    from workspace_tool.service import Workspace
    root = rehearsal_directory(parent)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0)); sock.listen(128)
    host = "127.0.0.1:" + str(sock.getsockname()[1])
    service = Workspace(root / "workspace", host, project=root, runtime=RehearsalRuntime(), codex_bin=codex_bin)
    app = create_app(service, LocalAuth(host), ROOT / "workspace_tool/web/dist")
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    running = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(60):
            while not service.status()["ready"]:
                if running.done():
                    await running
                    raise RuntimeError("验收服务未启动。")
                if service.connection_error: raise RuntimeError(service.connection_error)
                await asyncio.sleep(.1)
        yield service
        await service.runtime.verify_history()
    finally:
        server.should_exit = True
        try: await asyncio.wait_for(running, 30)
        finally:
            await service.close()
            sock.close()
