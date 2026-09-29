import json
import sys
import tempfile
import threading
import time
import unittest
import contextlib
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pool_store import Pool
from pool_selection import Selections
from pool_server import server_for, open_session, serve
from pool_share import ShareManager


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = self.root / "source.xlsx"
        book = Workbook()
        book.active.append(["名称", "零售价"])
        book.active.append(["甲商品 </script><script>bad()</script>", 50])
        book.active.append(["乙商品", 80])
        book.save(source)
        self.pool = Pool(self.root / "pool")
        self.pool.add(source)
        self.ids = [i["id"] for i in self.pool.search()["items"]]
        self.selections = Selections(self.pool)
        self.session = self.selections.create(self.ids, ["零售价"])["session_id"]

    def tearDown(self):
        self.pool.close()
        self.tmp.cleanup()

    def test_rename_preserves_candidates_choices_and_revision(self):
        self.selections.select(self.session, self.ids[:1], 0)
        before = self.selections.state(self.session, include_items=True)
        other = self.selections.create(self.ids, ["零售价"], title="另一次选品")["session_id"]
        result = self.selections.rename(self.session, "新标题")
        self.assertEqual(result, {"session_id": self.session, "title": "新标题"})
        self.assertEqual(self.selections.state(self.session, include_items=True), {**before, "title": "新标题"})
        self.assertEqual(self.selections.state(other)["title"], "另一次选品")
        for title in (None, "", "   ", "长" * 161):
            with self.assertRaisesRegex(ValueError, "title"):
                self.selections.rename(self.session, title)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.selections.rename("missing", "新标题")
        self.assertEqual(self.selections.state(self.session, include_items=True), {**before, "title": "新标题"})
        self.selections.select(self.session, self.ids, before["revision"])
        self.assertEqual(self.selections.state(self.session)["selected_ids"], self.ids)

    def test_persistence_cross_session_revision_and_empty_export(self):
        with self.assertRaisesRegex(ValueError, "No products"):
            self.selections.seal(self.session)
        self.selections.select(self.session, [self.ids[0]], 0)
        self.assertEqual(Selections(self.pool).state(self.session)["selected_ids"], self.ids[:1])
        other = self.selections.create([self.ids[1]], ["零售价"])["session_id"]
        with self.assertRaisesRegex(ValueError, "outside"):
            self.selections.select(other, [self.ids[0]], 0)
        with self.assertRaisesRegex(ValueError, "revision"):
            self.selections.select(self.session, [], 0)
        frozen = self.selections.seal(self.session)
        self.assertEqual(frozen["selected_ids"], self.ids[:1])
        with self.assertRaisesRegex(ValueError, "sealed"):
            self.selections.select(self.session, [self.ids[1]], 1)
        self.pool.stage(frozen["selected_ids"], self.root / "stage", frozen["price_fields"])
        staged = json.loads((self.root / "stage/catalog-data.json").read_text(encoding="utf-8"))
        self.assertEqual([x["id"] for x in staged], self.ids[:1])
        self.assertEqual(staged[0]["display_prices"], [{"label": "零售价", "value": 50}])

    def test_http_origin_membership_and_safe_html(self):
        ready = threading.Event()
        shared = {}
        def host():
            pool = Pool(self.root / "pool")
            server, prefix = server_for(pool, self.session)
            shared.update(server=server, url=f"http://127.0.0.1:{server.server_port}", prefix=prefix)
            ready.set()
            server.serve_forever(poll_interval=0.05)
            server.server_close()
            pool.close()
        worker = threading.Thread(target=host)
        worker.start()
        ready.wait(5)
        try:
            url = shared["url"] + shared["prefix"]
            with urlopen(url) as response:
                page = response.read().decode()
            self.assertNotIn("bad()", page)
            data = json.dumps({"ids": self.ids[:1], "revision": 0}).encode()
            for origin in ("http://malicious.invalid", "null"):
                for route in ('selection', 'share/start', 'share/stop'):
                    request = Request(url + route, data=data, headers={"Origin": origin, "Content-Type": "application/json"})
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request)
                    self.assertEqual(error.exception.code, 403)
            with urlopen(url + 'share') as response:
                self.assertEqual(json.load(response)['status'], 'idle')
            bad_duration = Request(url + 'share/start', data=b'{"minutes":true}', headers={'Origin': shared['url'], 'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as error: urlopen(bad_duration)
            self.assertEqual(error.exception.code, 409)
            request = Request(url + "selection", data=data, headers={"Origin": shared["url"], "Content-Type": "application/json"})
            with urlopen(request) as response:
                self.assertEqual(json.load(response)["selected_ids"], self.ids[:1])
            self.assertEqual(self.selections.state(self.session)["selected_ids"], self.ids[:1])
            directory = self.pool.root / "sessions" / self.session
            (directory / "index.html").write_text("old page", encoding="utf-8")
            (directory / "server.local.json").write_text(json.dumps({"url": url}), encoding="utf-8")
            self.assertEqual(open_session(self.pool.root, self.session)["url"], url)
            with urlopen(url) as response:
                self.assertIn('id="products"', response.read().decode())
            self.assertEqual(self.selections.state(self.session)["selected_ids"], self.ids[:1])
        finally:
            shared["server"].shutdown()
            worker.join(5)

    def test_closed_session_cannot_reopen_or_export(self):
        self.selections.select(self.session, self.ids[:1], 0)
        with self.pool.db:
            self.pool.db.execute("UPDATE pool_sessions SET state='closed' WHERE id=?", (self.session,))
        with self.assertRaisesRegex(ValueError, "closed"):
            self.selections.seal(self.session)
        with self.assertRaisesRegex(ValueError, "closed"):
            open_session(self.pool.root, self.session)

    def test_sealing_keeps_live_share_until_stopped(self):
        class Child:
            def poll(self): return None
        @contextlib.contextmanager
        def tunnel(*args):
            yield 'https://synthetic.trycloudflare.com', Child(), None
        manager = ShareManager(self.root, self.root, tunnel_factory=tunnel, probe=lambda *args: True)
        state_path = self.pool.root / 'sessions' / self.session / 'server.local.json'
        with patch('pool_server.ShareManager', return_value=manager):
            worker = threading.Thread(target=serve, args=(self.pool.root, self.session))
            worker.start()
            try:
                deadline = time.monotonic() + 5
                while not state_path.exists() and time.monotonic() < deadline: time.sleep(.02)
                url = json.loads(state_path.read_text(encoding='utf-8'))['url']
                origin = url.split('/', 3)[:3]
                headers = {'Origin': '/'.join(origin), 'Content-Type': 'application/json'}
                with urlopen(Request(url + 'share/start', data=b'{"minutes":null}', headers=headers), timeout=2): pass
                while manager.state()['status'] != 'ready' and time.monotonic() < deadline: time.sleep(.02)
                self.assertEqual(manager.state()['status'], 'ready')
                self.selections.select(self.session, self.ids[:1], 0)
                self.selections.seal(self.session)
                # One request could already be pending when sealing; subsequent requests must still work.
                for _ in range(3):
                    with urlopen(url + 'share', timeout=2) as response:
                        self.assertEqual(json.load(response)['status'], 'ready')
                self.assertTrue(manager.view.live())
                with urlopen(Request(url + 'share/stop', data=b'{}', headers=headers), timeout=2): pass
                worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertFalse(manager.view.live())
            finally:
                manager.stop()
                with self.pool.db:
                    self.pool.db.execute("UPDATE pool_sessions SET state='closed' WHERE id=?", (self.session,))
                worker.join(5)


if __name__ == "__main__":
    unittest.main()
