"""Check public repository revision using a small, read-only request."""
import json
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = "https://api.github.com/repos/GuoLuPM/codex-assistant/git/ref/heads/main"


def revision(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise ValueError("Invalid revision")
    return value


def check(root=ROOT, *, proxy=None):
    root = Path(root).resolve()
    try:
        if (root / ".git").exists():
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                      text=True, encoding="utf-8", check=True, timeout=3).stdout.strip()
            local = revision(git("rev-parse", "HEAD"))
            changed = bool(git("status", "--porcelain", "--untracked-files=normal"))
            kind = "git"
        else:
            marker = root / "deployment.local.json"
            if not marker.is_file():
                return {"status": "unknown", "reason": "没有可核对的本地版本标记。"}
            state = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("version") != 1: raise ValueError("Unsupported marker")
            local, changed, kind = revision(state["commit"]), None, "release"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {"status": "unknown", "reason": "本地版本暂时无法核对。"}
    result = {"installation": kind, "local": local[:12], "local_changes": changed}
    try:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler()
        request = urllib.request.Request(LATEST, headers={
            "User-Agent": "codex-assistant-update-check", "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache",
        })
        # No credentials, product data, downloads, Git fetch, or stale-cache fallback.
        with urllib.request.build_opener(handler).open(request, timeout=3) as response:
            raw = response.read(16385)
        if len(raw) > 16384: raise ValueError("Metadata exceeded limit")
        remote = revision(json.loads(raw)["object"]["sha"])
    except (OSError, ValueError, KeyError, TypeError):
        return {**result, "status": "unknown", "reason": "远端版本暂时无法确认；可检查网络或指定本机代理。"}
    return {**result, "latest": remote[:12], "status": "current" if local == remote else "different"}
