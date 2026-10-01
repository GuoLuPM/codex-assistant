"""Loopback, same-origin, one-use launch links. No model credentials here."""
import hashlib
import secrets
import time


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class LocalAuth:
    def __init__(self, host, *, clock=time.time):
        self.host, self.clock = host, clock
        self._starts, self._sessions = {}, {}
        self.control_token = secrets.token_urlsafe(32)

    def origin_valid(self, host, origin):
        return host == self.host and origin == "http://" + self.host

    def issue(self):
        now = self.clock()
        self._starts = {k: v for k, v in self._starts.items() if v > now}
        token = secrets.token_urlsafe(32)
        self._starts[digest(token)] = now + 120
        return token

    def exchange(self, token):
        if not isinstance(token, str) or len(token) > 200:
            raise ValueError("请从 Codex 重新打开工作台。")
        expires = self._starts.pop(digest(token), 0)
        if expires <= self.clock():
            raise ValueError("这个打开链接已失效，请从 Codex 重新打开。")
        session = secrets.token_urlsafe(32)
        self._sessions[digest(session)] = self.clock() + 86400
        return session

    def session_valid(self, token):
        return isinstance(token, str) and self._sessions.get(digest(token), 0) > self.clock()

    def control_valid(self, token):
        return isinstance(token, str) and secrets.compare_digest(token, self.control_token)
