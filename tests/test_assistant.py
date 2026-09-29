import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AssistantTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "assistant.py"), *args],
                              cwd=ROOT.parent, text=True, encoding="utf-8", capture_output=True)

    def test_discovery_is_bounded_and_does_not_load_business_data(self):
        result = self.run_cli("list", "--query", "xlsx", "--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertGreaterEqual(data["total"], 1)
        self.assertIn(data["items"][0]["id"], {"catalog", "pool"})
        self.assertLess(len(result.stdout), 1000)
        self.assertNotIn(".catalog-index", result.stdout)
        total = json.loads(self.run_cli("list").stdout)["total"]
        self.assertEqual(json.loads(self.run_cli("list", "--offset", str(total)).stdout)["items"], [])
        self.assertNotEqual(self.run_cli("list", "--limit", "0").returncode, 0)

    def test_describe_only_selected_tool_and_unknown_tool_fails(self):
        result = self.run_cli("describe", "catalog")
        self.assertEqual(result.returncode, 0, result.stderr)
        tool = json.loads(result.stdout)
        self.assertTrue((ROOT / tool["guide"]).is_file())
        self.assertLess(len(result.stdout), 1500)
        self.assertNotEqual(self.run_cli("describe", "missing").returncode, 0)

    def test_dispatch_preserves_flags_and_failure_status_from_any_cwd(self):
        result = self.run_cli("run", "catalog", "inspect", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--max-cells", result.stdout)
        result = self.run_cli("run", "catalog", "--unknown-argument")
        self.assertEqual(result.returncode, 2)

    def test_ppt_is_available_through_catalog_entry(self):
        result = self.run_cli("run", "catalog", "ppt", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--ids", result.stdout)
        self.assertIn("--price-fields", result.stdout)

    def test_new_tool_registers_without_router_changes_and_arguments_remain_data(self):
        with tempfile.TemporaryDirectory(prefix="assistant test ") as folder:
            root = Path(folder)
            shutil.copyfile(ROOT / "assistant.py", root / "assistant.py")
            (root / "echo.py").write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n", encoding="utf-8")
            (root / "guide.md").write_text("A bounded fixture.", encoding="utf-8")
            descriptor = {"id": "echo", "summary": "Echo fixture", "tags": ["sample"],
                          "entrypoint": "echo.py", "guide": "guide.md"}
            (root / "tools.json").write_text(json.dumps({"version": 1, "tools": [descriptor]}), encoding="utf-8")
            args = ["two words", "中文", "$(literal)", "a'b", "--flag"]
            result = subprocess.run([sys.executable, str(root / "assistant.py"), "run", "echo", *args],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 7)
            self.assertEqual(json.loads(result.stdout), args)
            descriptor["entrypoint"] = "../outside.py"
            (root / "tools.json").write_text(json.dumps({"version": 1, "tools": [descriptor]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(root / "assistant.py"), "list"],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("out-of-project", result.stderr)


if __name__ == "__main__":
    unittest.main()
