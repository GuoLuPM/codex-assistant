"""Fixed presentation types resolved from verified task-scoped references."""
from workspace_tool.tasks import fingerprint


def build_view(tid, request, store, pool):
    if not isinstance(request, dict) or set(request) - {"kind", "refs", "caption"}:
        raise ValueError("Unsupported display fields")
    kind, refs, caption = request.get("kind"), request.get("refs", {}), request.get("caption", "")
    if not isinstance(refs, dict) or not isinstance(caption, str) or len(caption) > 3000:
        raise ValueError("Invalid display reference")
    store.snapshot(tid)
    actions = []
    if kind in ("products", "comparison"):
        if set(refs) - {"session_id", "ids"}:
            raise ValueError("Unknown product reference")
        state = pool.state(tid, refs.get("session_id"), verify=True)
        items = state.pop("items")
        if kind == "comparison":
            ids = refs.get("ids", [])
            if not isinstance(ids, list) or not 1 <= len(ids) <= 4 or len(ids) != len(set(ids)) or set(ids) - {x["id"] for x in items}:
                raise ValueError("Compare 1..4 members of the same price session")
            items = [next(x for x in items if x["id"] == ident) for ident in ids]
        shown = []
        for item in items:
            value = {k: item.get(k) for k in ("id", "name", "model", "variant", "prices", "features", "category", "tags", "source_file", "locator")}
            value["image_url"] = f"/api/tasks/{tid}/images/{state['session_id']}/{item['id']}" if item.get("image") else None
            shown.append(value)
        body = {**state, "items": shown, "caption": caption}
        actions = ["select", "export", "share"] if kind == "products" else []
    elif kind == "artifact":
        if set(refs) != {"artifact_id"}:
            raise ValueError("Artifact needs one registered reference")
        value = store.ref(tid, "artifact", refs["artifact_id"])
        if not value.get("verification_ref"):
            raise ValueError("Artifact has not been verified")
        body = {k: value[k] for k in ("artifact_id", "display_name", "sha256")}
        body["url"] = f"/api/artifacts/{refs['artifact_id']}?task={tid}"
        actions = ["download"]
    elif kind == "text":
        if refs or not caption.strip():
            raise ValueError("Text needs a short plain-text caption")
        body = {"text": caption, "role": "assistant", "complete": True}
    elif kind == "question":
        current = store.snapshot(tid)
        body = next((p for p in current["pending_requests"] if p["request_id"] == refs.get("request_id")), None)
        if not body:
            raise ValueError("Question is no longer pending")
        actions = ["answer"]
    elif kind == "progress":
        value = store.ref(tid, "job", refs.get("job_id"))
        body = {"job_id": refs["job_id"], "state": value["state"]}
    else:
        raise ValueError("Unknown display type")
    identity = {"kind": kind, "refs": refs}
    if kind == "text": identity["caption"] = caption
    return {"block_id": "view_" + fingerprint(identity)[:20], "kind": kind, "revision": body.get("revision", 0), "body": body, "actions": actions}
