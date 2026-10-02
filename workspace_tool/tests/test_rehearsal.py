"""A live-model rehearsal must fail before using personal history or tools."""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.workspace_rehearsal import RehearsalRuntime
from workspace_tool.runtime import CodexRuntime, RuntimeError


class Peer:
    """Protocol boundary only; no subprocess, model, credentials, or personal data."""
    def __init__(self):
        self.calls, self.persisted, self.turns = [], [], 0
        self.ephemeral_supported = True
        self.inventory = [{"name": "personal", "runtimeStatus": "disabled", "pluginId": None,
                           "tools": {}, "resources": [], "resourceTemplates": [], "toolsError": None}]

    async def request(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        if method == "config/read":
            return {"config": {"mcp_servers": {"personal": {"command": "private-program"}}}}
        if method == "thread/start":
            ephemeral = params.get("ephemeral") is True and self.ephemeral_supported
            if not ephemeral: self.persisted.append("synthetic-thread")
            return {"thread": {"id": "synthetic-thread", "ephemeral": ephemeral,
                               "path": None if ephemeral else "private-rollout.jsonl"}}
        if method == "mcpServerStatus/list":
            return {"data": self.inventory, "nextCursor": None}
        if method == "turn/start":
            self.turns += 1
            return {"turn": {"id": "synthetic-turn"}}
        if method == "thread/list":
            return {"data": [{"id": t} for t in self.persisted], "nextCursor": None}
        if method == "thread/archive":
            return {}
        raise AssertionError("Unexpected protocol method: " + method)


class RehearsalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.peer = Peer()
        self.runtime = RehearsalRuntime()
        self.runtime.capabilities = {"logged_in": True, "models": [{"model": "gpt-6.1-sol"}]}
        self.boundary = patch.object(CodexRuntime, "request", new=self.peer.request)
        self.boundary.start()
        self.addCleanup(self.boundary.stop)

    async def create(self, **kwargs):
        return await self.runtime.start_thread(Path.cwd(), **kwargs)

    async def test_rehearsal_never_creates_persistent_history(self):
        thread = await self.create()
        await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.assertEqual(self.peer.persisted, [])
        self.assertEqual(self.peer.turns, 1)

    async def test_unsupported_ephemeral_fails_before_a_model_turn(self):
        self.peer.ephemeral_supported = False
        with self.assertRaises(RuntimeError):
            thread = await self.create()
            await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.assertEqual(self.peer.turns, 0)

    async def test_unrelated_tools_cannot_be_used_even_if_added_between_turns(self):
        thread = await self.create()
        await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.peer.inventory.append({"name": "desktop", "runtimeStatus": "connected", "pluginId": "computer",
                                    "tools": {"get_state": {}}, "resources": [], "resourceTemplates": []})
        with self.assertRaises(RuntimeError):
            await self.runtime.start_turn({"thread_id": thread, "text": "again"})
        self.assertEqual(self.peer.turns, 1)

    async def test_only_disabled_unrelated_servers_are_allowed(self):
        self.peer.inventory[0]["runtimeStatus"] = "starting"
        with self.assertRaises(RuntimeError):
            thread = await self.create()
            await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.assertEqual(self.peer.turns, 0)

    async def test_test_config_cannot_reenable_desktop_plugins_or_personal_mcp(self):
        await self.create(config={"features.plugins": True, "features.computer_use": True,
                                  "mcp_servers.personal.enabled": True})
        params = next(p for m, p in self.peer.calls if m == "thread/start")
        self.assertIs(params["config"]["features.plugins"], False)
        self.assertIs(params["config"]["features.computer_use"], False)
        self.assertIs(params["config"]["features.shell_tool"], False)
        self.assertIs(params["config"]["mcp_servers.personal.enabled"], False)

    async def test_rehearsal_cannot_resume_or_turn_an_existing_personal_thread(self):
        with self.assertRaises(RuntimeError):
            await self.runtime.resume_thread("personal-thread")
        with self.assertRaises(RuntimeError):
            await self.runtime.request("thread/fork", {"threadId": "personal-thread"})
        with self.assertRaises(RuntimeError):
            await self.runtime.start_turn({"thread_id": "personal-thread", "text": "no"})
        self.assertEqual(self.peer.turns, 0)
        self.assertFalse(any(m == "thread/resume" for m, _ in self.peer.calls))

    async def test_inventory_failure_is_not_treated_as_empty(self):
        thread = await self.create()
        original = self.peer.request
        async def unavailable(_runtime, method, params=None, **kwargs):
            if method == "mcpServerStatus/list": raise RuntimeError("inventory unavailable")
            return await original(method, params, **kwargs)
        with patch.object(CodexRuntime, "request", new=unavailable), self.assertRaises(RuntimeError):
            await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.assertEqual(self.peer.turns, 0)

    async def test_native_process_disables_personal_capabilities_before_thread_creation(self):
        with patch.object(CodexRuntime, "start", new_callable=AsyncMock) as launch, \
                patch("scripts.workspace_rehearsal.find_codex", return_value="codex.exe"):
            await self.runtime.start({"cwd": str(Path.cwd())})
        command = launch.await_args.args[0]["command"]
        disabled = {command[i + 1] for i, value in enumerate(command) if value == "--disable"}
        self.assertTrue({"plugins", "apps", "computer_use", "browser_use", "hooks", "memories", "shell_tool"} <= disabled)

    async def test_only_the_explicit_task_bridge_is_allowed(self):
        self.peer.inventory.append({"name": "assistant_workspace", "runtimeStatus": "connected", "pluginId": None,
            "tools": {name: {"name": name} for name in
                      ("capabilities_find", "capabilities_describe", "capabilities_call", "ui_present")},
            "resources": [], "resourceTemplates": [], "toolsError": None})
        thread = await self.create(config={"mcp_servers.assistant_workspace": {"command": "synthetic-bridge"}})
        await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.peer.inventory[-1]["tools"]["read_desktop"] = {"name": "read_desktop"}
        with self.assertRaises(RuntimeError):
            await self.runtime.start_turn({"thread_id": thread, "text": "again"})
        self.assertEqual(self.peer.turns, 1)

    async def test_missing_bridge_is_an_error_not_a_fallback_to_other_tools(self):
        thread = await self.create(config={"mcp_servers.assistant_workspace": {"command": "synthetic-bridge"}})
        with self.assertRaises(RuntimeError):
            await self.runtime.start_turn({"thread_id": thread, "text": "synthetic"})
        self.assertEqual(self.peer.turns, 0)

    async def test_persistence_found_after_a_turn_fails_verification(self):
        await self.create()
        await self.runtime.verify_history()
        self.peer.persisted.append("synthetic-thread")
        with self.assertRaises(RuntimeError):
            await self.runtime.verify_history()


if __name__ == "__main__":
    unittest.main()
