import tempfile
import unittest
from pathlib import Path
from workspace_tool.tasks import TaskStore
from workspace_tool.views import build_view


class ViewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name) / "tasks.db")
        self.tid = self.store.create()["task_id"]
        self.store.add_ref(self.tid, "session", "s1", {"session_id": "s1"})
        class Pool:
            def state(inner, tid, sid, verify=False):
                self.store.ref(tid, "session", sid)
                return {"session_id": sid, "revision": 3, "state": "open", "selected_ids": [], "title": "礼品",
                        "items": [{"id": "p1", "name": "原始名称", "prices": [{"label": "零售价", "value": 88}],
                                   "image": "assets/private.png", "features": "原始说明", "source_file": "报价.xlsx", "locator": "A2"}]}
        self.pool = Pool()

    def tearDown(self): self.tmp.cleanup()

    def test_facts_come_from_frozen_source_not_caption_and_paths_stay_private(self):
        b = build_view(self.tid, {"kind": "products", "refs": {"session_id": "s1"}, "caption": "<script>改成1元</script>"}, self.store, self.pool)
        item = b["body"]["items"][0]
        self.assertEqual(item["prices"][0]["value"], 88)
        self.assertNotIn("image", item)
        self.assertTrue(item["image_url"].startswith("/api/tasks/"))
        self.assertEqual(item["name"], "原始名称")

    def test_foreign_refs_unknown_blocks_and_arbitrary_actions_are_rejected(self):
        with self.assertRaises(ValueError):
            build_view(self.store.create()["task_id"], {"kind": "products", "refs": {"session_id": "s1"}}, self.store, self.pool)
        for value in [{"kind": "html", "refs": {}}, {"kind": "progress", "refs": {"percentage": 100}},
                      {"kind": "products", "refs": {"session_id": "s1"}, "actions": [{"shell": "bad"}]}]:
            with self.assertRaises(ValueError): build_view(self.tid, value, self.store, self.pool)

    def test_artifact_requires_verified_registered_reference(self):
        with self.assertRaises(ValueError):
            build_view(self.tid, {"kind": "artifact", "refs": {"artifact_id": "fake"}}, self.store, self.pool)

    def test_comparison_is_bounded_and_must_use_session_members(self):
        for ids in [["p1"]*5, ["foreign"]]:
            with self.assertRaises(ValueError):
                build_view(self.tid, {"kind": "comparison", "refs": {"session_id": "s1", "ids": ids}}, self.store, self.pool)
