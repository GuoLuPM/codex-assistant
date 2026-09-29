"""Check tracked files and reachable Git history before making this code public.

Print locations/rule names only, never matched secret values. This is a focused
release check, not a replacement for credential revocation or human review.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".csv", ".tsv", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".zip", ".db", ".sqlite", ".sqlite3", ".pem", ".key"}
RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "api-key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "aws-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential-url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
    "literal-user-path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+[\\/]", re.I),
    "secret-assignment": re.compile(r'''(?i)\b(?:password|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*["'][A-Za-z0-9_+/.=-]{12,}["']'''),
}
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def allowed_email(address):
    return address.endswith(("@users.noreply.github.com", "@example.com", "@example.invalid")) or address == "noreply@github.com"


def findings(data, location):
    text = data.decode("utf-8", errors="replace")
    result = [{"location": location, "rule": name} for name, pattern in RULES.items() if pattern.search(text)]
    if any(not allowed_email(match.group()) for match in EMAIL.finditer(text)):
        result.append({"location": location, "rule": "personal-email"})
    return result


def private_path(name):
    path = Path(name)
    return (path.suffix.lower() in PRIVATE_SUFFIXES or name.endswith(".local.json")
            or path.name.startswith(".env") or any(part.startswith(".catalog") or part in {"outputs", "data"} for part in path.parts))


def audit():
    issues, checked = [], set()
    for raw in git("ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        if private_path(name):
            issues.append({"location": name, "rule": "private-data-file"})
        path = ROOT / name
        if path.is_file():
            issues.extend(findings(path.read_bytes(), name))
    # Check unique blobs from every reachable revision, including deleted files.
    for line in git("rev-list", "--objects", "--all").decode("utf-8").splitlines():
        object_id, _, name = line.partition(" ")
        if not name or object_id in checked:
            continue
        checked.add(object_id)
        if git("cat-file", "-t", object_id).strip() != b"blob":
            continue
        location = f"{object_id[:8]}:{name}"
        if private_path(name):
            issues.append({"location": location, "rule": "historical-private-data-file"})
        issues.extend(findings(git("cat-file", "blob", object_id), location))
    for line in git("log", "--all", "--format=%H%x09%ae%x09%ce").decode("utf-8").splitlines():
        commit, *emails = line.split("\t")
        if any(not allowed_email(address) for address in emails):
            issues.append({"location": commit[:8], "rule": "commit-personal-email"})
        issues.extend(findings(git("show", "-s", "--format=%B", commit), commit[:8] + ":message"))
    return {"ok": not issues, "checked_history_objects": len(checked), "findings": issues}


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    sys.exit(0 if result["ok"] else 1)
