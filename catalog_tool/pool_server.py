"""Local selection-only HTTP adapter; no uploads, commands or public binding."""

import json
import mimetypes
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import urlopen

from pool_selection import Selections
from pool_store import Pool, encoded


def server_for(pool, session_id, port=0):
    selections = Selections(pool)
    session = selections.session(session_id)
    prefix = "/" + session["token"] + "/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload, content_type="application/json; charset=utf-8"):
            data = payload if isinstance(payload, bytes) else encoded(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            host = f"127.0.0.1:{self.server.server_port}"
            return self.headers.get("Host") == host and self.path.startswith(prefix)

        def do_GET(self):
            if not self.allowed():
                return self.reply(404, {"error": "Unknown selection page"})
            relative = self.path[len(prefix):]
            if relative == "":
                page = pool.root / "sessions" / session_id / "index.html"
                return self.reply(200, page.read_bytes(), "text/html; charset=utf-8")
            if relative == "state":
                return self.reply(200, selections.state(session_id, include_items=True))
            if relative.startswith("image/"):
                product_id = relative[6:]
                row = pool.db.execute("SELECT snapshot FROM pool_choices WHERE session_id=? AND product_id=?", (session_id, product_id)).fetchone()
                snapshot = json.loads(row[0]) if row else {}
                if snapshot.get("image"):
                    path = (pool.root / snapshot["image"]).resolve()
                    if path.is_relative_to(pool.root / "assets") and path.is_file():
                        return self.reply(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            return self.reply(404, {"error": "Unknown selection resource"})

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self.allowed() or self.headers.get("Origin") != origin or self.path != prefix + "selection":
                return self.reply(403, {"error": "Selection origin/path denied"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, {"error": "JSON required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 20000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {"ids", "revision"} or type(data["revision"]) is not int:
                    raise ValueError("Expected ids and integer revision")
                state = selections.select(session_id, data["ids"], data["revision"])
                self.reply(200, state)
            except (ValueError, TypeError) as error:
                self.reply(409, {"error": str(error)})

    return HTTPServer(("127.0.0.1", port), Handler), prefix


def serve(root, session_id, port=0):
    pool = Pool(root)
    server, prefix = server_for(pool, session_id, port)
    url = f"http://127.0.0.1:{server.server_port}{prefix}"
    state_path = pool.root / "sessions" / session_id / "server.local.json"
    state_path.write_text(encoded({"url": url, "pid": os.getpid()}), encoding="utf-8")
    print(encoded({"url": url}), flush=True)
    try:
        server.timeout = 1
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline and Selections(pool).session(session_id)["state"] == "open":
            server.handle_request()
    finally:
        server.server_close()
        pool.close()


def open_session(root, session_id):
    root = Path(root).resolve()
    pool = Pool(root)
    try:
        session = Selections(pool).session(session_id)
        if session["state"] != "open":
            raise ValueError("Selection session is sealed or closed; create a new selection")
    finally:
        pool.close()
    directory = root / "sessions" / session_id
    # Refresh the view on reopen; frozen candidates/prices and saved choices stay in SQLite.
    template = Path(__file__).with_name("pool_select.html").read_text(encoding="utf-8")
    (directory / "index.html").write_text(template, encoding="utf-8")
    path = directory / "server.local.json"
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        try:
            with urlopen(state["url"] + "state", timeout=1) as response:
                if json.load(response).get("session_id") == session_id:
                    return state
        except OSError:
            pass  # Restart an explicitly unavailable local helper, retaining SQLite choices.
    with (directory / "server.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("pool.py")), "--index-dir", str(root), "serve", "--session", session_id],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    for _ in range(50):
        if process.poll() is not None:
            raise ValueError("Selection helper failed; inspect its private server.log")
        if path.is_file():
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("pid") == process.pid:
                return state
        time.sleep(0.1)
    process.terminate()
    raise ValueError("Selection helper startup timed out")
