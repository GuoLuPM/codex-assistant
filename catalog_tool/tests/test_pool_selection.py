import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pool_store import Pool
from pool_selection import Selections
from pool_server import server_for, open_session


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
                request = Request(url + "selection", data=data, headers={"Origin": origin, "Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
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


if __name__ == "__main__":
    unittest.main()
