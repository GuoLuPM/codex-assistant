"""Bounded opt-in real Codex rehearsal. All inputs and outputs are synthetic.

Usage: python scripts/check_workspace_runtime.py --work-dir data/runtime-check
No private account details or raw tool outputs are written to the report.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_tool.runtime import RuntimeError, choose_model
from scripts.workspace_rehearsal import RehearsalRuntime, rehearsal_directory


async def collect(runtime, thread, text, *, inputs=None, interrupt=False):
    turn = await runtime.start_turn({"thread_id": thread, "text": text, "inputs": inputs or []})
    result = {"turn_id": turn, "text": "", "tools": [], "requests": [], "usage": None}
    async def read():
        stop_sent = False
        async for event in runtime.events():
            if event.get("thread_id") not in (None, thread):
                continue
            kind, data = event["kind"], event["payload"]
            if "request_id" in event:
                result["requests"].append(kind)
                # The probe cannot silently approve a request on the user's behalf.
                raise RuntimeError("Real probe requires user input: " + kind)
            if kind == "item/agentMessage/delta":
                result["text"] += data.get("delta", "")
                if interrupt and not stop_sent:
                    await runtime.interrupt(thread, turn)
                    stop_sent = True
            if kind == "item/completed":
                item = data.get("item", {})
                if item.get("type") not in ("agentMessage", "userMessage", "reasoning"):
                    result["tools"].append({"type": item.get("type"), "tool": item.get("tool"), "status": item.get("status")})
            if kind == "thread/tokenUsage/updated":
                result["usage"] = data.get("tokenUsage")
            if kind == "turn/completed" and data.get("turn", {}).get("id") == turn:
                result["status"] = data["turn"]["status"]
                result["error"] = data["turn"].get("error")
                return result
            if kind == "connection_closed":
                raise RuntimeError("Connection closed during probe")
    return await asyncio.wait_for(read(), timeout=180)


async def check(args):
    root = rehearsal_directory(args.work_dir)
    runtime = RehearsalRuntime()
    report = {"schema": 1, "directory": str(root), "checks": {}, "rehearsals": [],
              "isolation": "ephemeral_project_tools_only", "durable_resume_tested": False}
    try:
        caps = await runtime.start({"cwd": str(root), **({"codex_bin": args.codex_bin} if args.codex_bin else {})})
        report.update({k: v for k, v in caps.items() if k not in ("models", "request_methods")})
        report["model"] = choose_model(caps["models"], args.profile)
        if args.discovery_only:
            report["checks"]["discovery"] = True
            return report
        thread = await runtime.start_thread(root, args.profile, instructions=(
            "这是隔离的合成验收。用中文简短回答，只处理当前目录的测试材料。"
            "不要访问其他聊天或真实产品库。普通速度，不派子代理，不读取凭据。"
        ))
        result = await collect(runtime, thread, "请先问我这次准备送谁，一句话即可。")
        report["rehearsals"].append(result)
        report["checks"]["chinese"] = result["status"] == "completed" and bool(result["text"])
        result = await collect(runtime, thread, "送同事。请记住这个信息，只答‘好的’。")
        report["rehearsals"].append(result)
        report["checks"]["multiturn"] = result["status"] == "completed"
        result = await collect(runtime, thread, "刚才说要送谁？只回答对象。")
        report["rehearsals"].append(result)
        report["checks"]["in_memory_context"] = result["status"] == "completed" and "同事" in result["text"]
        result = await collect(runtime, thread, "请写一篇长文章，主题是如何整理产品资料。", interrupt=True)
        report["rehearsals"].append(result)
        report["checks"]["interrupt"] = result["status"] == "interrupted"
        await runtime.verify_history()
        report["checks"]["not_in_native_history"] = True
        report["access_verified"] = all(report["checks"].values())
        return report
    finally:
        await runtime.close()
        (root / "runtime-check.local.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-dir", required=True)
    p.add_argument("--codex-bin")
    p.add_argument("--profile", choices=["normal", "low"], default="normal")
    p.add_argument("--discovery-only", action="store_true")
    args = p.parse_args()
    try:
        report = asyncio.run(check(args))
        print(json.dumps({k: v for k, v in report.items() if k != "rehearsals"}, ensure_ascii=False))
        return 0 if all(report["checks"].values()) else 1
    except (RuntimeError, TimeoutError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
