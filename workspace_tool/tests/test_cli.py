import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workspace_tool import cli


class LauncherTests(unittest.TestCase):
    def test_windows_python_redirector_can_report_a_different_server_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            def spawned(command, **kwargs):
                nonce = command[command.index('--launch-id') + 1]
                Path(directory, 'server.local.json').write_text(json.dumps({
                    'pid': 4321, 'launch_id': nonce, 'origin': 'http://127.0.0.1:1234', 'control_token': 'test'}))
                class Process:
                    pid = 1234
                    def poll(self): return None
                return Process()
            with patch.object(cli.subprocess, 'Popen', side_effect=spawned), patch.object(cli, 'control', return_value={'url': 'test'}) as control:
                self.assertEqual(cli.launch(directory), {'url': 'test'})
                control.assert_called_once()

    def test_process_alive_finds_current_process(self):
        import os
        self.assertTrue(cli.process_alive(os.getpid()))
        self.assertFalse(cli.process_alive(-1))
