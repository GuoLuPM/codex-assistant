"""Protocol boundaries, exercised against an actual child process."""
import asyncio
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

from workspace_tool.runtime import CodexRuntime, RuntimeError, choose_model, find_codex


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = CodexRuntime()
        self.config = {"command": [sys.executable, str(Path(__file__).with_name("fake_runtime.py"))]}

    async def asyncTearDown(self):
        await self.runtime.close()

    async def test_requires_handshake_and_correlates_concurrent_responses(self):
        with self.assertRaises(RuntimeError):
            await self.runtime.request("echo", {})
        caps = await self.runtime.start(self.config)
        self.assertEqual(caps["version"], "test-runtime")
        a, b = await asyncio.gather(self.runtime.request("echo", {"x": 1}), self.runtime.request("echo", {"x": 2}))
        self.assertEqual([a["x"], b["x"]], [1, 2])

    async def test_unknown_approval_is_rejected_and_not_auto_accepted(self):
        await self.runtime.start(self.config)
        await self.runtime.request("unknownApproval", {})
        event = await asyncio.wait_for(anext(self.runtime.events()), 2)
        self.assertEqual(event["kind"], "unsupported_request")
        answer = await self.runtime.request("lastAnswer", {})
        self.assertIn("error", answer)

    async def test_pending_question_does_not_block_interrupt_and_needs_explicit_answer(self):
        await self.runtime.start(self.config)
        await self.runtime.request("question", {})
        event = await asyncio.wait_for(anext(self.runtime.events()), 2)
        self.assertEqual(event["request_id"], 90)
        await self.runtime.interrupt("thread", "turn")
        await self.runtime.answer(90, {"answers": {"budget": {"answers": ["100"]}}})
        answer = await self.runtime.request("lastAnswer", {})
        self.assertEqual(answer["result"]["answers"]["budget"]["answers"], ["100"])

    async def test_errors_and_failed_turn_are_not_success(self):
        await self.runtime.start(self.config)
        with self.assertRaisesRegex(RuntimeError, "quota"):
            await self.runtime.request("quota", {})
        await self.runtime.request("failedTurn", {})
        event = await asyncio.wait_for(anext(self.runtime.events()), 2)
        self.assertEqual(event["payload"]["turn"]["status"], "failed")

    async def test_close_ends_owned_process_and_pending_calls(self):
        await self.runtime.start(self.config)
        process = self.runtime.process
        pending = asyncio.create_task(self.runtime.request("hang", {}))
        await asyncio.sleep(.03)
        await self.runtime.close()
        with self.assertRaises(RuntimeError):
            await pending
        self.assertIsNotNone(process.returncode)

    def test_model_profiles_never_silently_upgrade_or_use_astra(self):
        models = [{"model": s} for s in ["gpt-6-sol", "gpt-6.1-sol", "gpt-6-astra", "gpt-5.6-terra"]]
        self.assertEqual(choose_model(models, "normal"), "gpt-6.1-sol")
        self.assertEqual(choose_model(models, "low"), "gpt-5.6-terra")
        with self.assertRaises(RuntimeError):
            choose_model(models[:3], "low")

    def test_desktop_install_wins_over_stale_path_cli(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            desktop = Path(directory) / 'OpenAI/Codex/bin/current/codex.exe'
            desktop.parent.mkdir(parents=True)
            desktop.write_text('synthetic desktop executable')
            stale = Path(directory) / 'stale-codex.cmd'
            stale.write_text('synthetic old executable')
            # Replace this module's OS view, not the global os.name used by
            # pathlib itself (which cannot construct WindowsPath on Linux).
            environment = SimpleNamespace(name='nt', environ={'LOCALAPPDATA': directory})
            with patch('workspace_tool.runtime.os', environment), patch('workspace_tool.runtime.shutil.which', return_value=str(stale)):
                self.assertEqual(find_codex(), str(desktop.resolve()))
                self.assertEqual(find_codex(str(stale)), str(stale.resolve()))


if __name__ == "__main__":
    unittest.main()
