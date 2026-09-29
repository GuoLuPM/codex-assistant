"""Small Codex tool router. Discovery uses only the standard library."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def local_file(value):
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError("Registry paths must be relative to the project")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"Missing or out-of-project registry path: {value}")
    return path


def registry():
    data = json.loads((ROOT / "tools.json").read_text(encoding="utf-8"))
    if set(data) != {"version", "tools"} or data["version"] != 1 or not isinstance(data["tools"], list):
        raise ValueError("Unsupported tools.json schema")
    result = {}
    for tool in data["tools"]:
        if not isinstance(tool, dict) or set(tool) != {"id", "summary", "tags", "entrypoint", "guide"}:
            raise ValueError("Invalid tool descriptor fields")
        if not isinstance(tool["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", tool["id"]) or tool["id"] in result:
            raise ValueError("Invalid or duplicate tool id")
        if not isinstance(tool["summary"], str) or not 1 <= len(tool["summary"]) <= 160:
            raise ValueError("Tool summary must contain 1 to 160 characters")
        if (not isinstance(tool["tags"], list) or len(tool["tags"]) > 12
                or any(not isinstance(tag, str) or not 1 <= len(tag) <= 40 for tag in tool["tags"])):
            raise ValueError("Invalid tool tags")
        if local_file(tool["entrypoint"]).suffix != ".py":
            raise ValueError("Tool entrypoint must be a Python CLI adapter")
        local_file(tool["guide"])
        result[tool["id"]] = tool
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Find capabilities without reading their guides or loading data")
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=int, default=10)
    listing.add_argument("--offset", type=int, default=0)
    commands.add_parser("describe", help="Return one capability's guide and entrypoint").add_argument("tool")
    run = commands.add_parser("run", help="Forward arguments to one capability; paths are relative to the project")
    run.add_argument("tool")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    commands.add_parser("doctor", help="Check the router only; capability dependencies are checked when used")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 11):
            raise ValueError("Python 3.11+ required")
        tools = registry()
        if args.command == "list":
            if not 1 <= args.limit <= 50 or args.offset < 0 or len(args.query) > 160:
                raise ValueError("Invalid discovery query/limit/offset")
            terms = args.query.casefold().split()
            items = [tool for tool in tools.values() if all(
                term in " ".join([tool["id"], tool["summary"], *tool["tags"]]).casefold() for term in terms)]
            result = {"total": len(items), "offset": args.offset, "limit": args.limit,
                      "items": [{"id": item["id"], "summary": item["summary"]}
                                for item in items[args.offset:args.offset + args.limit]]}
        elif args.command == "doctor":
            result = {"ok": True, "scope": "router", "python": sys.executable,
                      "python_version": sys.version.split()[0], "project": str(ROOT), "tools": len(tools)}
        else:
            if args.tool not in tools:
                raise ValueError(f"Unknown tool: {args.tool}; use list --query KEYWORD")
            result = tools[args.tool]
            if args.command == "run":
                forwarded = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
                env = dict(os.environ, PYTHONIOENCODING="utf-8")
                return subprocess.run([sys.executable, str(local_file(result["entrypoint"])), *forwarded],
                                      cwd=ROOT, env=env, check=False).returncode
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
