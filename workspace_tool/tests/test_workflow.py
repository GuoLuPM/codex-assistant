import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from workspace_tool.tasks import TaskStore
from workspace_tool.uploads import accept_upload
from workspace_tool.artifacts import publish_artifact, artifact_file


async def chunks(data):
    for i in range(0, len(data), 10):
        yield data[i:i+10]


class FilesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TaskStore(self.root / "tasks.db")
        self.tid = self.store.create()["task_id"]

    def tearDown(self): self.tmp.cleanup()

    async def test_duplicate_uploads_reuse_ref_without_replacing_content(self):
        a = await accept_upload(self.store, self.root, self.tid, chunks(b"original"), "first.txt")
        b = await accept_upload(self.store, self.root, self.tid, chunks(b"original"), "renamed.txt")
        self.assertEqual(a["input_id"], b["input_id"])
        self.assertEqual(len(self.store.refs(self.tid, "input")), 1)

    async def test_oversize_path_and_mislabelled_file_leave_no_registered_input(self):
        for data, name, limit in [(b"data", "../outside.txt", 10), (b"x"*15, "large.txt", 10), (b"not zip", "bad.xlsx", 100)]:
            with self.assertRaises(ValueError):
                await accept_upload(self.store, self.root, self.tid, chunks(data), name, limit=limit)
        self.assertEqual(self.store.refs(self.tid, "input"), [])

    def test_artifact_is_scoped_and_tamper_prevents_download(self):
        path = self.root / "outputs" / self.tid / "工作安排.txt"
        path.parent.mkdir(parents=True); path.write_text("周五", encoding="utf-8")
        artifact = publish_artifact(self.store, self.tid, path, self.root / "outputs" / self.tid, "file-checked")
        self.assertEqual(artifact_file(self.store, self.tid, artifact["artifact_id"])["path"], str(path.resolve()))
        other = self.store.create()["task_id"]
        with self.assertRaises(ValueError): artifact_file(self.store, other, artifact["artifact_id"])
        path.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError): artifact_file(self.store, self.tid, artifact["artifact_id"])

    def test_no_artifact_from_arbitrary_path_or_unverified_file(self):
        path = self.root / "private.txt"; path.write_text("keep")
        with self.assertRaises(ValueError): publish_artifact(self.store, self.tid, path, self.root / "outputs", "checked")
        with self.assertRaises(ValueError): publish_artifact(self.store, self.tid, path, self.root, "")
