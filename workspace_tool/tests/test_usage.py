import tempfile
import unittest
from pathlib import Path
from workspace_tool.tasks import TaskStore


class UsageTests(unittest.TestCase):
    def test_native_totals_replayed_and_reasoning_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.db")
            self.assertIsNone(store.usage("thread"))
            data = {"total": {"inputTokens": 100, "cachedInputTokens": 60, "outputTokens": 20, "reasoningOutputTokens": 5, "totalTokens": 120}}
            store.record_usage("thread", "turn1", data)
            store.record_usage("thread", "turn1", data)
            self.assertEqual(store.usage("thread")["totalTokens"], 120)
            store.record_usage("thread", "turn2", {"total": {**data["total"], "inputTokens": 150, "outputTokens": 30, "totalTokens": 180}})
            self.assertEqual(store.usage("thread")["totalTokens"], 180)
            store.record_usage("thread", "turn1", data)
            self.assertEqual(store.usage("thread")["totalTokens"], 180)
            store.record_usage("thread", "turn3", None)
            self.assertEqual(store.usage("thread")["totalTokens"], 180)
