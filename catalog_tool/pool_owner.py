"""One OS-backed writer lease shared by CLI, selection page, and workspace.

The lease releases on process exit; no stale PID lock files to guess about.
Each connection is created and used by the same worker thread.
"""
import contextlib
import functools
import inspect
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

_threads = threading.local()
_locks, _registry_guard = {}, threading.Lock()


@contextlib.contextmanager
def pool_lock(root, timeout=20):
    path = str((Path(root).resolve() / "writer.lock"))
    with _registry_guard:
        lock = _locks.setdefault(path, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise ValueError("产品库正在处理另一项操作，请稍后再试。")
    held = getattr(_threads, "held", None)
    if held is None:
        held = _threads.held = {}
    handle = None
    try:
        if path not in held:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "a+b")
            if handle.seek(0, 2) == 0:
                handle.write(b"0"); handle.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError("产品库正在处理另一项操作，请稍后再试。") from None
                    time.sleep(.025)
            held[path] = handle
        yield
    finally:
        if handle is not None:
            if path in held:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
                held.pop(path, None)
            handle.close()
        lock.release()


class AtomicConnection(sqlite3.Connection):
    """Let existing `with db` scopes join one explicit business transaction."""
    external_transaction = False

    def __exit__(self, exc_type, exc, tb):
        if self.external_transaction:
            return False
        return super().__exit__(exc_type, exc, tb)

    def executescript(self, script):
        if self.external_transaction:
            raise ValueError("Schema writes cannot run inside a business operation")
        return super().executescript(script)

    @contextlib.contextmanager
    def atomic(self):
        if self.external_transaction:
            yield self
            return
        if self.in_transaction:
            raise ValueError("Unfinished transaction before business operation")
        self.execute("BEGIN IMMEDIATE")
        self.external_transaction = True
        try:
            yield self
            super().commit()
        except BaseException:
            super().rollback()
            raise
        finally:
            self.external_transaction = False


def ensure_receipts(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pool_operations (
        operation_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state='completed'), result_ref TEXT NOT NULL)""")


def operation(db, ident, payload, work):
    from pool_store import digest, encoded
    if not isinstance(ident, str) or not 1 <= len(ident) <= 200:
        raise ValueError("Invalid operation ID")
    signature = digest(payload)
    with db.atomic():
        old = db.execute("SELECT payload_hash,result_ref FROM pool_operations WHERE operation_id=?", (ident,)).fetchone()
        if old:
            if old[0] != signature:
                raise ValueError("operation ID reused for different content")
            return json.loads(old[1])
        result = work()
        db.execute("INSERT INTO pool_operations VALUES (?,?,'completed',?)", (ident, signature, encoded(result)))
        return result


def selection_write(fn):
    signature = inspect.signature(fn)
    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        with pool_lock(self.pool.root):
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            ident = bound.arguments.get("operation_id")
            if ident is None:
                return fn(self, *args, **kwargs)
            payload = {k: v for k, v in bound.arguments.items() if k not in ("self", "operation_id")}
            return operation(self.db, ident, {"method": fn.__name__, "args": payload}, lambda: fn(self, *args, **kwargs))
    return wrapped
