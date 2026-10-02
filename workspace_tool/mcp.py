"""Minimal MCP stdio bridge to one authorized workspace task.

The gateway owns validation and execution. This process never interprets commands.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def tools_list():
    definitions = [
        ("capabilities_find", "按关键词找本地能力，只返回短目录。", {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, [], True),
        ("capabilities_describe", "读取一种能力的用法与参数，先读再调用。", {"id": {"type": "string"}}, ["id"], True),
        ("capabilities_call", "执行已发现的能力；资料入库、检索、选品和发布均经过校验。", {"id": {"type": "string"}, "command": {"type": "string"}, "payload": {"type": "object"}, "request_id": {"type": "string"}}, ["id", "command", "payload", "request_id"], False),
        ("ui_present", "在当前网页展示真实商品、对比或已核验成品；只传引用，不能改商品事实。", {"kind": {"type": "string", "enum": ["products", "comparison", "artifact", "text", "question", "progress"]}, "refs": {"type": "object"}, "caption": {"type": "string"}}, ["kind", "refs"], False),
    ]
    return [{"name": name, "description": description, "inputSchema": schema(props, required),
             "annotations": {"readOnlyHint": readonly, "destructiveHint": False, "openWorldHint": False}}
            for name, description, props, required, readonly in definitions]


def dispatch(method, params, call):
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}}, "serverInfo": {"name": "assistant-workspace", "version": "0.4.1"}}
    if method == "ping": return {}
    if method == "tools/list": return {"tools": tools_list()}
    if method != "tools/call" or params.get("name") not in {t["name"] for t in tools_list()}:
        raise ValueError("Unknown method or tool")
    result = call(params["name"], params.get("arguments", {}))
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}], "isError": isinstance(result, dict) and "error" in result}


def main():
    url, token = os.environ["ASSISTANT_AGENT_URL"], os.environ["ASSISTANT_AGENT_TOKEN"]
    address = urlsplit(url)
    if address.scheme != "http" or address.hostname != "127.0.0.1" or not address.path.startswith("/agent/"):
        raise ValueError("Task gateway must be loopback")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(name, arguments):
        raw = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False).encode()
        if len(raw) > 1048576: raise ValueError("Tool input too large")
        request = urllib.request.Request(url, raw, {"Content-Type": "application/json", "X-Workspace-Agent": token})
        try:
            with opener.open(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            return json.loads(error.read())
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin.buffer:
        if len(line) > 2*1048576:
            raise ValueError("MCP message too large")
        message = json.loads(line)
        if "id" not in message: continue
        try:
            result = dispatch(message["method"], message.get("params", {}), call)
            response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": str(error)[:500]}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
