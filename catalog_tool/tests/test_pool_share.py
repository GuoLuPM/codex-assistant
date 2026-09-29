import json
import contextlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pool_share_view import PublicView, public_server
from pool_share import ShareManager
from share_runtime import WindowsJob, prepare_binary


class PublicShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = {'title': '合成候选', 'selected_ids': ['private-id'], 'revision': 7,
                      'session_id': 'private-session', 'items': [
            {'id': 'private-id', 'name': '<script>bad()</script>', 'model': 'A', 'variant': None,
             'features': '资料原文', 'prices': [{'label': '零售价', 'value': 88, 'raw': 'internal evidence', 'cell': 'B7'}],
             'source_file': 'private.xlsx', 'locator': 'secret row', 'tags': [{'value': 'internal annotation'}], 'image': None}]}

    def tearDown(self): self.tmp.cleanup()

    def test_public_projection_omits_owner_identity_choices_and_evidence(self):
        view = PublicView(self.state, self.root)
        state = view.state()
        raw = json.dumps(state)
        for secret in ('private-id', 'private-session', 'private.xlsx', 'secret row', 'internal evidence', 'internal annotation'):
            self.assertNotIn(secret, raw)
        self.assertTrue(state['readonly'])
        self.assertEqual(state['selected_ids'], [])
        self.assertEqual(state['items'][0]['prices'], [{'label': '零售价', 'value': 88}])
        self.assertEqual(state['items'][0]['features'], '资料原文')

    def test_public_listener_has_no_control_or_file_endpoints_and_expires(self):
        view = PublicView(self.state, self.root)
        server = public_server(view)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}{view.prefix}'
        try:
            with urlopen(url) as response:
                self.assertNotIn('bad()', response.read().decode())
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            with urlopen(url + 'state') as response: self.assertTrue(json.load(response)['readonly'])
            for path in ('selection', 'share', 'share/start', 'share/stop', '../catalog.sqlite3', 'image/private-id', '../../source.xlsx'):
                with self.assertRaises(HTTPError) as failure: urlopen(url + path)
                self.assertEqual(failure.exception.code, 404)
            for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(url + 'selection', data=b'{}', method=method, headers={'Origin': url.rstrip('/')}))
                self.assertEqual(failure.exception.code, 405)
            view.expires_at = time.time() - 1
            with self.assertRaises(HTTPError) as failure: urlopen(url + 'state')
            self.assertEqual(failure.exception.code, 410)
        finally:
            server.shutdown();server.server_close();worker.join(3)

    def test_images_cannot_escape_pool_assets(self):
        (self.root / 'secret.txt').write_text('private')
        for name in ('../secret.txt', 'secret.txt', str(self.root / 'secret.txt')):
            self.state['items'][0]['image'] = name
            with self.assertRaisesRegex(ValueError, '图片'):
                PublicView(self.state, self.root)

    @unittest.skipUnless(os.name == 'nt', 'Windows process ownership')
    def test_windows_job_kills_its_owned_child(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        job = None
        try:
            job = WindowsJob(process)
            self.assertIsNone(process.poll())
            job.close()
            process.wait(timeout=5)
            self.assertIsNotNone(process.returncode)
        finally:
            if job: job.close()
            if process.poll() is None: process.kill();process.wait(timeout=5)

    @unittest.skipUnless(os.name == 'nt', 'Windows runtime')
    def test_modified_runtime_is_rejected_before_execution(self):
        binary = self.root / 'cloudflared.exe'
        binary.write_bytes(b'not the verified official binary')
        with patch.dict(os.environ, {'ASSISTANT_CLOUDFLARED': str(binary)}):
            with self.assertRaisesRegex(ValueError, '校验不符'):
                prepare_binary(Path(__file__).resolve().parents[2], threading.Event(), lambda *args: None)

    def test_manager_duplicate_start_stop_expiry_and_child_failure(self):
        class Child:
            dead = False
            def poll(self): return 1 if self.dead else None
        child = Child()
        starts, exits = [], []
        @contextlib.contextmanager
        def tunnel(*args):
            starts.append(args[0])
            try: yield 'https://synthetic.trycloudflare.com', child, None
            finally: exits.append(True)
        manager = ShareManager(self.root, self.root, tunnel_factory=tunnel, probe=lambda *args: True)
        def wait_for(status):
            end = time.monotonic() + 3
            while time.monotonic() < end:
                if manager.state()['status'] == status: return
                time.sleep(.02)
            self.fail(str(manager.state()))
        try:
            manager.start(PublicView(self.state, self.root), 15)
            wait_for('ready')
            first = manager.state()['url']
            manager.start(PublicView(self.state, self.root), 15)
            self.assertEqual(manager.state()['url'], first)
            self.assertEqual(len(starts), 1)
            manager.stop();wait_for('stopped')
            self.assertNotIn('url', manager.state())
            self.assertEqual(len(exits), 1)
            manager.start(PublicView(self.state, self.root), 90);wait_for('ready')
            self.assertEqual(manager.state()['minutes'], 90)
            manager.view.expires_at = time.time() - 1;wait_for('expired')
            manager.start(PublicView(self.state, self.root), 15);wait_for('ready')
            child.dead = True;wait_for('failed')
            self.assertNotIn('url', manager.state())
        finally: manager.close()
        self.assertEqual(len(starts), len(exits))

    def test_cancel_while_connecting_never_publishes_a_url(self):
        entered = threading.Event()
        @contextlib.contextmanager
        def delayed(target, project, directory, cancel, progress):
            entered.set();cancel.wait(3)
            raise InterruptedError('cancelled')
            yield  # contextmanager generator, deliberately never yields
        manager = ShareManager(self.root, self.root, tunnel_factory=delayed)
        try:
            manager.start(PublicView(self.state, self.root), 60)
            self.assertTrue(entered.wait(2))
            manager.stop();manager.close()
            self.assertEqual(manager.state()['status'], 'stopped')
            self.assertNotIn('url', manager.state())
            self.assertFalse(manager.view.live())
        finally: manager.close()

    def test_unlimited_share_has_no_deadline_but_can_be_stopped(self):
        class Child:
            def poll(self): return None
        @contextlib.contextmanager
        def tunnel(*args):
            yield 'https://synthetic.trycloudflare.com', Child(), None
        manager = ShareManager(self.root, self.root, tunnel_factory=tunnel, probe=lambda *args: True)
        view = PublicView(self.state, self.root)
        try:
            manager.start(view)
            deadline = time.monotonic() + 3
            while manager.state()['status'] != 'ready' and time.monotonic() < deadline: time.sleep(.02)
            self.assertEqual(manager.state()['status'], 'ready')
            self.assertIsNone(manager.state()['minutes'])
            self.assertIsNone(view.expires_at)
            with patch('pool_share_view.time.time', return_value=time.time() + 20 * 365 * 86400):
                self.assertTrue(view.live())
            manager.stop()
            self.assertFalse(view.live())
        finally: manager.close()

    def test_custom_duration_validation_does_not_turn_bad_values_into_unlimited(self):
        from pool_share import validate_minutes
        for value in (None, 1, 90, 600, 525600):
            validate_minutes(value)
        for value in (True, False, 0, -1, 1.5, '永久', '', 525601, float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError): validate_minutes(value)


if __name__ == '__main__': unittest.main()
