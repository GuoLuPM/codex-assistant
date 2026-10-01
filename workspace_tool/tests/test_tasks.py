import tempfile
import unittest
from pathlib import Path
from workspace_tool.tasks import TaskStore, Conflict


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tasks.sqlite3"
        self.store = TaskStore(self.path)
        self.task = self.store.create()

    def tearDown(self):
        self.tmp.cleanup()

    def test_action_retry_is_idempotent_and_reuse_cannot_change_payload(self):
        action = {"task_id": self.task["task_id"], "request_id": "one", "expected_revision": 0, "kind": "message", "payload": {"text": "你好"}}
        receipt = self.store.accept_action(action)
        self.assertEqual(receipt, self.store.accept_action(action))
        with self.assertRaises(Conflict):
            self.store.accept_action({**action, "payload": {"text": "changed"}})
        with self.assertRaises(Conflict):
            self.store.accept_action({**action, "request_id": "two"})

    def test_question_and_cursor_survive_reopen_without_duplicate_event(self):
        tid = self.task["task_id"]
        self.store.record(tid, "question", {"request_id": 8, "questions": [{"question": "预算多少？"}]}, key="question:8")
        snapshot = self.store.snapshot(tid)
        other = TaskStore(self.path)
        self.assertEqual(snapshot, other.snapshot(tid))
        self.assertEqual(snapshot["state"], "awaiting_user")
        other.record(tid, "question", {"request_id": 8}, key="question:8")
        self.assertEqual(len(other.events_after(tid, 0)), 1)
        self.assertEqual(other.events_after(tid, snapshot["last_event_seq"]), [])

    def test_turn_completion_is_not_business_completion_and_failed_stays_failed(self):
        tid = self.task["task_id"]
        self.store.record(tid, "turn_started", {"turn_id": "t1"})
        self.store.record(tid, "turn_ended", {"status": "completed"})
        self.assertEqual(self.store.snapshot(tid)["state"], "ready")
        self.store.record(tid, "turn_ended", {"status": "failed", "message": "额度不足"})
        self.assertEqual(self.store.snapshot(tid)["state"], "failed")

    def test_recovery_interrupts_inflight_without_replaying_action(self):
        tid = self.task["task_id"]
        self.store.record(tid, "turn_started", {"turn_id": "t1"})
        self.store.recover()
        self.assertEqual(self.store.snapshot(tid)["state"], "interrupted")
        self.assertIsNone(self.store.snapshot(tid)["active_turn_id"])

    def test_stream_updates_same_block_and_final_text_deduplicates(self):
        tid = self.task["task_id"]
        self.store.record(tid, "text_delta", {"block_id": "m1", "delta": "您"})
        self.store.record(tid, "text_delta", {"block_id": "m1", "delta": "好"})
        self.store.record(tid, "text_done", {"block_id": "m1", "text": "您好"})
        blocks = self.store.snapshot(tid)["blocks"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["body"]["text"], "您好")

    def test_task_references_are_scoped(self):
        tid = self.task["task_id"]
        self.store.add_ref(tid, "input", "file1", {"display_name": "报价.xlsx"})
        self.assertEqual(self.store.ref(tid, "input", "file1")["display_name"], "报价.xlsx")
        with self.assertRaises(ValueError):
            self.store.ref(self.store.create()["task_id"], "input", "file1")
