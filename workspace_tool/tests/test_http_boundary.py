import unittest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from workspace_tool.auth import LocalAuth
from workspace_tool.app import create_app
from workspace_tool.tasks import TaskStore


class BoundaryTests(unittest.TestCase):
    def test_one_time_bootstrap_and_session_expiry(self):
        now = [100.0]
        auth = LocalAuth("127.0.0.1:5000", clock=lambda: now[0])
        token = auth.issue()
        session = auth.exchange(token)
        self.assertTrue(auth.session_valid(session))
        with self.assertRaises(ValueError):
            auth.exchange(token)
        now[0] += 86401
        self.assertFalse(auth.session_valid(session))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = LocalAuth("127.0.0.1:5000")
        class Service:
            store = TaskStore(Path(self.tmp.name) / "tasks.db")
            async def start(self): pass
            async def close(self): pass
            def status(self): return {"ready": True}
        self.app = create_app(Service(), self.auth, Path(self.tmp.name))
        self.client = TestClient(self.app, base_url="http://127.0.0.1:5000")

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def login(self):
        response = self.client.post("/api/bootstrap", json={"token": self.auth.issue()}, headers={"origin": "http://127.0.0.1:5000"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])

    def test_private_api_requires_cookie_host_and_origin(self):
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/tasks").status_code, 200)
        self.assertEqual(self.client.get("/api/tasks", headers={"host": "evil.test"}).status_code, 403)
        self.assertEqual(self.client.post("/api/tasks", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/tasks", json={}, headers={"origin": "https://evil.test"}).status_code, 403)

    def test_refuses_non_json_and_oversized_body_without_mutation(self):
        self.login()
        headers = {"origin": "http://127.0.0.1:5000"}
        self.assertEqual(self.client.post("/api/tasks", content="a", headers=headers).status_code, 415)
        headers["content-type"] = "application/json"
        self.assertEqual(self.client.post("/api/tasks", content='"' + 'x'*1048577 + '"', headers=headers).status_code, 413)
        self.assertEqual(self.client.get("/api/tasks").json(), [])

    def test_wrong_origin_host_and_expired_start_link_are_rejected(self):
        now = [100.0]
        auth = LocalAuth("127.0.0.1:5000", clock=lambda: now[0])
        self.assertTrue(auth.origin_valid("127.0.0.1:5000", "http://127.0.0.1:5000"))
        self.assertFalse(auth.origin_valid("evil.test", "http://127.0.0.1:5000"))
        self.assertFalse(auth.origin_valid("127.0.0.1:5000", "https://evil.test"))
        self.assertFalse(auth.origin_valid("127.0.0.1:5000", "null"))
        token = auth.issue(); now[0] += 121
        with self.assertRaises(ValueError):
            auth.exchange(token)
