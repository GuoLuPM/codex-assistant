"""Version checks must not mistake stale or unverifiable code for current code."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_update import check


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.local = "a" * 40

    def installed(self):
        (self.root / "deployment.local.json").write_text(json.dumps({"version": 1, "commit": self.local, "tag": "v1"}))

    def remote(self, sha):
        from io import BytesIO
        return BytesIO(json.dumps({"object": {"sha": sha}}).encode())

    def test_installed_bundle_can_check_without_git(self):
        self.installed()
        with patch("urllib.request.OpenerDirector.open", return_value=self.remote(self.local)), \
                patch("subprocess.run", side_effect=AssertionError("Must not need Git")):
            result = check(self.root)
        self.assertEqual(result["status"], "current")
        self.assertEqual(result["installation"], "release")

    def test_different_commit_is_not_reported_current(self):
        self.installed()
        with patch("urllib.request.OpenerDirector.open", return_value=self.remote("b" * 40)):
            self.assertEqual(check(self.root)["status"], "different")

    def test_network_failure_does_not_claim_a_cached_or_current_version(self):
        self.installed()
        with patch("urllib.request.OpenerDirector.open", side_effect=TimeoutError()):
            self.assertEqual(check(self.root)["status"], "unknown")

    def test_unmarked_source_archive_cannot_guess_its_version(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No local revision")):
            self.assertEqual(check(self.root)["status"], "unknown")

    def test_git_worktree_checks_live_head_and_reports_local_edits(self):
        (self.root / ".git").write_text("gitdir: synthetic-worktree")
        def git(args, **kwargs):
            operation = args[3:]
            self.assertIn(operation[0], ("rev-parse", "status"))
            output = self.local if operation[0] == "rev-parse" else " M assistant.py"
            return subprocess.CompletedProcess(args, 0, output, "")
        with patch("subprocess.run", side_effect=git), \
                patch("urllib.request.OpenerDirector.open", return_value=self.remote(self.local)):
            result = check(self.root)
        self.assertEqual(result["status"], "current")
        self.assertTrue(result["local_changes"])

    def test_invalid_remote_payload_is_unknown(self):
        self.installed()
        with patch("urllib.request.OpenerDirector.open", return_value=self.remote("not-a-commit")):
            self.assertEqual(check(self.root)["status"], "unknown")

    def test_malformed_installation_marker_returns_unknown_without_network(self):
        for value in (None, [], {"version": 1, "commit": "a" * 50}):
            (self.root / "deployment.local.json").write_text(json.dumps(value))
            with self.subTest(value=value), patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Invalid local revision")):
                self.assertEqual(check(self.root)["status"], "unknown")
