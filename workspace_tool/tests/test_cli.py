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

    def test_reopening_failed_native_connection_restarts_owned_service(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory, 'server.local.json')
            state.write_text(json.dumps({'pid': 1, 'origin': 'http://127.0.0.1:1234', 'control_token': 'test',
                'configuration': {'pool_dir': str(Path(directory, 'pool')), 'codex_bin': str(Path(directory, 'native.exe'))}}))
            calls = []
            def control(saved, action, **kwargs):
                calls.append(action)
                if action == 'stop': state.unlink(); return {'stopping': True}
                if len(calls) == 1: return {'url': 'old', 'readiness': {'error': 'disconnected'}}
                return {'url': 'new'}
            def spawned(command, **kwargs):
                self.assertEqual(command[command.index('--pool-dir')+1], str(Path(directory, 'pool').resolve()))
                self.assertEqual(command[command.index('--codex-bin')+1], str(Path(directory, 'native.exe').resolve()))
                state.write_text(json.dumps({'pid': 2, 'launch_id': command[command.index('--launch-id')+1]}))
                class Process:
                    def poll(self): return None
                return Process()
            with patch.object(cli, 'control', side_effect=control), patch.object(cli.subprocess, 'Popen', side_effect=spawned):
                self.assertEqual(cli.launch(directory), {'url': 'new'})
            self.assertEqual(calls, ['open', 'stop', 'open'])
