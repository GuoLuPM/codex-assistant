"""Evaluation commands must distinguish a model pass from a failed experiment."""
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class EvaluationExitTests(unittest.TestCase):
    def test_both_evaluators_return_failure_for_errors_or_incomplete_checks(self):
        for name in ("evaluate_pool_models", "evaluate_pool_retrieval"):
            spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cases = [
                ({"error": "CLI option unsupported"}, 1),
                ({"passed": 1, "total": 2, "checks": {"one": True, "two": "bad evidence"}}, 1),
                ({"passed": 2, "total": 2, "checks": {"one": True}}, 1),
                ({"passed": 1, "total": 1, "checks": {"one": True}}, 0),
            ]
            for outcome, expected in cases:
                with self.subTest(evaluator=name, outcome=outcome), patch.object(module, "evaluate", return_value=outcome), contextlib.redirect_stdout(io.StringIO()) as output:
                    code = module.main(["--codex", sys.executable, "--models", "synthetic-model", "--work-dir", "unused"])
                    self.assertEqual(code, expected)
                    self.assertEqual(json.loads(output.getvalue()), outcome)
            with patch.object(module, "evaluate", side_effect=RuntimeError("synthetic failure")), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(module.main(["--codex", sys.executable, "--models", "synthetic-model", "--work-dir", "unused"]), 1)
                self.assertIn("synthetic failure", json.loads(output.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
