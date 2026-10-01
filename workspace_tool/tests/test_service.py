import asyncio
import tempfile
import unittest
from pathlib import Path
from workspace_tool.service import Workspace
from workspace_tool.runtime import RuntimeError


class FakeRuntime:
    def __init__(self):
        self.calls = 0
        self.answers = []
        self.capabilities = {"logged_in": True, "models": [{"model": "gpt-6.1-sol"}, {"model": "gpt-5.6-terra"}], "version": "fake"}
    async def start(self, config): return self.capabilities
    async def start_thread(self, *args, **kwargs): return "native-thread"
    async def resume_thread(self, *args, **kwargs): return {}
    async def start_turn(self, request): self.calls += 1; return "turn1"
    async def answer(self, ident, answer): self.answers.append((ident, answer))
    async def interrupt(self, *args): return {}
    async def close(self): pass
    async def events(self):
        await asyncio.Future()
        yield {}


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = FakeRuntime()
        self.service = Workspace(self.root, "127.0.0.1:5000", project=self.root, runtime=self.runtime)
        await self.service.start()
        self.tid = self.service.store.create()["task_id"]

    async def asyncTearDown(self):
        await self.service.close()
        self.tmp.cleanup()

    async def test_retried_message_and_streamed_reply_only_start_one_turn(self):
        payload = {"request_id": "message1", "expected_revision": 0, "text": "帮我整理资料", "input_ids": []}
        a = await self.service.message(self.tid, payload)
        b = await self.service.message(self.tid, payload)
        self.assertEqual(a, b)
        self.assertEqual(self.runtime.calls, 1)
        await self.service.handle_runtime_event({"kind": "item/agentMessage/delta", "thread_id": "native-thread", "turn_id": "turn1", "item_id": "m1", "payload": {"delta": "好的"}})
        await self.service.handle_runtime_event({"kind": "turn/completed", "thread_id": "native-thread", "turn_id": "turn1", "payload": {"turn": {"id": "turn1", "status": "completed"}}})
        state = self.service.store.snapshot(self.tid)
        self.assertEqual(state["blocks"][-1]["body"]["text"], "好的")
        self.assertEqual(state["state"], "ready")

    async def test_stop_waits_for_native_interruption_and_preserves_text(self):
        await self.service.message(self.tid, {"request_id": "m", "expected_revision": 0, "text": "继续做"})
        state = self.service.store.snapshot(self.tid)
        await self.service.action(self.tid, {"request_id": "stop", "expected_revision": state["revision"], "kind": "stop", "payload": {}})
        self.assertEqual(self.service.store.snapshot(self.tid)["state"], "running")
        await self.service.handle_runtime_event({"kind": "turn/completed", "thread_id": "native-thread", "turn_id": "turn1", "payload": {"turn": {"id": "turn1", "status": "interrupted"}}})
        self.assertEqual(self.service.store.snapshot(self.tid)["state"], "interrupted")

    async def test_answer_is_bound_to_pending_native_request(self):
        await self.service.message(self.tid, {"request_id": "m", "expected_revision": 0, "text": "准备礼品"})
        await self.service.handle_runtime_event({"kind": "item/tool/requestUserInput", "thread_id": "native-thread", "turn_id": "turn1", "request_id": 7,
            "payload": {"questions": [{"id": "budget", "question": "多少钱以内？"}]}})
        state = self.service.store.snapshot(self.tid)
        answer = {"request_id": "answer", "expected_revision": state["revision"], "kind": "answer", "payload": {"native_request_id": 8, "answer": {"answers": {}}}}
        with self.assertRaises(ValueError): await self.service.action(self.tid, answer)
        self.assertEqual(self.runtime.answers, [])

    async def test_model_cannot_present_unregistered_file_or_approve_via_business_tool(self):
        with self.assertRaises(ValueError):
            await self.service.agent_call(self.tid, {"name": "ui_present", "arguments": {"kind": "artifact", "refs": {"artifact_id": "guess"}}})
        with self.assertRaises(ValueError):
            await self.service.agent_call(self.tid, {"name": "approve_everything", "arguments": {}})

    async def test_restarted_native_request_id_is_not_deduplicated_across_turns(self):
        self.service._threads['native-thread'] = self.tid
        for turn in ('turn1', 'turn2'):
            await self.service.handle_runtime_event({'kind': 'item/tool/requestUserInput', 'thread_id': 'native-thread',
                'turn_id': turn, 'request_id': 0, 'payload': {'questions': [{'id': 'q', 'question': turn}]}})
            self.assertEqual(self.service.store.snapshot(self.tid)['pending_requests'][0]['turn_id'], turn)
            self.service.store.record(self.tid, 'turn_ended', {'status': 'interrupted'})

    async def test_repeated_export_one_job_and_stop_preserves_previous_file(self):
        self.service.store.add_ref(self.tid, 'session', 's1', {'session_id': 's1'})
        old = self.service.output_dir(self.tid) / '产品图册.pptx'
        old.write_bytes(b'previous-verified-result')
        started = asyncio.Event()
        async def slow_export(*args):
            started.set()
            await asyncio.Future()
        self.service.pool.export = slow_export
        request = {'request_id': 'export1', 'expected_revision': 0, 'kind': 'export', 'payload': {'session_id': 's1', 'revision': 0}}
        one = await self.service.action(self.tid, request)
        two = await self.service.action(self.tid, request)
        self.assertEqual(one, two)
        self.assertEqual(len(self.service._jobs), 1)
        await started.wait()
        snapshot = self.service.store.snapshot(self.tid)
        await self.service.action(self.tid, {'request_id': 'stop', 'expected_revision': snapshot['revision'], 'kind': 'stop', 'payload': {}})
        self.assertEqual(self.service.store.snapshot(self.tid)['progress']['state'], 'failed')
        self.assertEqual(old.read_bytes(), b'previous-verified-result')
        self.assertEqual(self.runtime.calls, 0)

    async def test_pre_release_job_metadata_cannot_break_reopening(self):
        self.service.store.add_ref(self.tid, 'job', 'old', {'job_id': 'old', 'state': 'running'})
        await self.service.close()
        self.service = Workspace(self.root, '127.0.0.1:5000', project=self.root, runtime=FakeRuntime())
        await self.service.start()
        self.assertTrue(self.service.status()['ready'])
        self.assertEqual(self.service.store.ref(self.tid, 'job', 'old')['state'], 'failed')

    async def test_start_timeout_keeps_confirmed_turn_stoppable(self):
        async def timeout(request):
            await self.service.handle_runtime_event({'kind': 'turn/started', 'thread_id': 'native-thread', 'turn_id': 'late-turn', 'payload': {}})
            raise RuntimeError('timeout', code='request_timeout')
        self.runtime.start_turn = timeout
        response = await self.service.message(self.tid, {'request_id': 'late', 'expected_revision': 0, 'text': '整理资料'})
        state = self.service.store.snapshot(self.tid)
        self.assertEqual(state['active_turn_id'], 'late-turn')
        self.assertEqual(state['state'], 'running')
        self.assertEqual(response['state'], 'completed')
        await self.service.action(self.tid, {'request_id': 'stop-late', 'expected_revision': state['revision'], 'kind': 'stop', 'payload': {}})

    async def test_file_approval_keeps_reviewable_changes_after_refresh(self):
        self.service._threads['native-thread'] = self.tid
        item = {'id': 'file1', 'type': 'fileChange', 'changes': [{'path': 'notice.txt', 'kind': {'type': 'add'}, 'diff': '+周五开会'}]}
        await self.service.handle_runtime_event({'kind': 'item/started', 'thread_id': 'native-thread', 'turn_id': 't1', 'payload': {'item': item}})
        await self.service.handle_runtime_event({'kind': 'item/fileChange/requestApproval', 'thread_id': 'native-thread', 'turn_id': 't1', 'item_id': 'file1', 'request_id': 8, 'payload': {}})
        question = self.service.store.snapshot(self.tid)['pending_requests'][0]
        self.assertEqual(question['changes'], item['changes'])
