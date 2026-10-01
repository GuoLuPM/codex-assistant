"""Synthetic NDJSON peer; no model, network, or credentials."""
import json
import sys

ready = False
last_answer = None


def send(obj):
    print(json.dumps(obj), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method is None:
        last_answer = message
        continue
    if method == "initialized":
        ready = True
        continue
    ident = message["id"]
    if method == "initialize":
        send({"id": ident, "result": {"userAgent": "test-runtime"}})
        print("stderr is not protocol", file=sys.stderr, flush=True)
        continue
    if not ready:
        send({"id": ident, "error": {"message": "not initialized"}})
        continue
    if method == "model/list":
        result = {"data": [{"model": "gpt-6.1-sol"}, {"model": "gpt-5.6-terra"}], "nextCursor": None}
    elif method == "account/read":
        result = {"account": {"type": "chatgpt", "email": "private@example.invalid"}, "requiresOpenaiAuth": True}
    elif method == "unknownApproval":
        send({"id": 89, "method": "future/approve", "params": {"threadId": "thread"}})
        result = {}
    elif method == "question":
        send({"id": 90, "method": "item/tool/requestUserInput", "params": {"threadId": "thread", "questions": []}})
        result = {}
    elif method == "lastAnswer":
        result = last_answer
    elif method == "quota":
        send({"id": ident, "error": {"code": -32000, "message": "quota exhausted"}})
        continue
    elif method == "failedTurn":
        send({"method": "turn/completed", "params": {"threadId": "thread", "turn": {"id": "turn", "status": "failed"}}})
        result = {}
    elif method == "hang":
        continue
    else:
        result = message.get("params", {})
    send({"id": ident, "result": result})
