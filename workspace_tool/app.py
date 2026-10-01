"""Authenticated local HTTP/SSE surface; public sharing never serves this app."""
import asyncio
import json
import hashlib
import base64
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from workspace_tool.tasks import Conflict
from workspace_tool.runtime import RuntimeError


class HttpError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


async def json_body(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HttpError(415, "需要 JSON 请求")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1048576:
            raise HttpError(413, "这条消息太长了，请分开说或作为文件添加。")
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise HttpError(400, "请求格式不正确") from None


def create_app(service, auth, static_dir):
    static_dir = Path(static_dir).resolve()

    @asynccontextmanager
    async def lifespan(app):
        async def connect():
            try:
                await service.start()
            except Exception:
                service.connection_error = "上次的记录暂时无法恢复，请让 Codex 检查工作台。资料仍保留。"
                import logging
                logging.getLogger(__name__).exception("Workspace startup failed")
        connecting = asyncio.create_task(connect())
        try:
            yield
        finally:
            connecting.cancel()
            await asyncio.gather(connecting, return_exceptions=True)
            await service.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundary(request, call_next):
        host, origin = request.headers.get("host"), request.headers.get("origin")
        path = request.url.path
        if host != auth.host or (origin is not None and not auth.origin_valid(host, origin)):
            return JSONResponse({"error": "仅支持本机打开"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "请从 Codex 打开工作台"}, status_code=403)
        control = path.startswith("/control/")
        agent = path.startswith("/agent/")
        if control and not auth.control_valid(request.headers.get("x-workspace-control")):
            return JSONResponse({"error": "无效连接"}, status_code=403)
        if not control and not agent:
            if request.method not in ("GET", "HEAD") and not auth.origin_valid(host, origin):
                return JSONResponse({"error": "请在工作台页面内操作"}, status_code=403)
            if path.startswith("/api/") and path != "/api/bootstrap" and not auth.session_valid(request.cookies.get("workspace_session")):
                return JSONResponse({"error": "请从 Codex 重新打开工作台。", "code": "session_expired"}, status_code=401)
        response = await call_next(request)
        styles = "'self'"
        if path == "/help":
            guide = (Path(__file__).resolve().parents[1] / "docs/USER_GUIDE.html").read_text(encoding="utf-8")
            styles += " " + " ".join("'sha256-" + base64.b64encode(hashlib.sha256(css.encode()).digest()).decode() + "'" for css in re.findall(r"<style>(.*?)</style>", guide, re.S))
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src " + styles + "; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'",
            "Permissions-Policy": "microphone=(), camera=(), geolocation=()",
        })
        return response

    @app.exception_handler(HttpError)
    async def http_error(request, exc):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=409)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"error": str(exc), "code": "revision_conflict"}, status_code=409)

    @app.exception_handler(RuntimeError)
    async def runtime_error(request, exc):
        return JSONResponse({"error": str(exc), "code": exc.code}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing_field(request, exc):
        return JSONResponse({"error": "这次操作的信息不完整，请刷新后再试。"}, status_code=400)

    @app.post("/api/bootstrap")
    async def bootstrap(request: Request):
        session = auth.exchange((await json_body(request)).get("token"))
        response = JSONResponse({"ok": True})
        response.set_cookie("workspace_session", session, httponly=True, samesite="strict", max_age=86400)
        return response

    @app.post("/control/open")
    async def control_open():
        return {"url": "http://" + auth.host + "/#start=" + auth.issue(), "readiness": service.status()}

    @app.get("/control/status")
    async def control_status():
        return service.status()

    @app.post("/control/stop")
    async def control_stop():
        await service.request_shutdown()
        return {"stopping": True}

    @app.get("/api/status")
    async def status():
        return service.status()

    @app.get("/api/tasks")
    async def recent():
        return service.store.recent()

    @app.post("/api/tasks")
    async def create_task(request: Request):
        data = await json_body(request)
        return service.store.create(profile=data.get("model_profile", "normal"))

    @app.get("/api/tasks/{tid}")
    async def snapshot(tid: str):
        return service.store.snapshot(tid)

    @app.get("/api/tasks/{tid}/events")
    async def events(tid: str, request: Request, after: int = 0):
        service.store.snapshot(tid)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", 0)))
        except ValueError:
            raise HttpError(400, "Invalid event cursor") from None
        async def stream():
            nonlocal cursor
            heartbeats = 0
            while not await request.is_disconnected():
                batch = service.store.events_after(tid, cursor)
                for event in batch:
                    cursor = event["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                heartbeats += 1
                if heartbeats >= 60:
                    yield ": keepalive\n\n"
                    heartbeats = 0
                await asyncio.sleep(.25)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/tasks/{tid}/messages")
    async def message(tid: str, request: Request):
        result = await service.message(tid, await json_body(request))
        return {**result, "task_revision": service.store.snapshot(tid)["revision"]}

    @app.post("/api/tasks/{tid}/actions")
    async def action(tid: str, request: Request):
        result = await service.action(tid, await json_body(request))
        return {**result, "task_revision": service.store.snapshot(tid)["revision"]}

    @app.post("/api/tasks/{tid}/inputs")
    async def upload(tid: str, request: Request):
        return await service.upload(tid, request.stream(), unquote(request.headers.get("x-file-name", "")))

    @app.get("/api/tasks/{tid}/images/{session_id}/{product_id}")
    async def image(tid: str, session_id: str, product_id: str):
        return FileResponse(await service.image(tid, session_id, product_id))

    @app.get("/api/artifacts/{artifact_id}")
    async def artifact(artifact_id: str, task: str):
        item = service.artifact(task, artifact_id)
        return FileResponse(item["path"], filename=item["display_name"], media_type="application/octet-stream")

    @app.get("/api/tasks/{tid}/shares/{session_id}")
    async def share(tid: str, session_id: str):
        return await service.sharing(tid, {"session_id": session_id}, "share_state")

    @app.get("/help")
    async def help_page():
        return FileResponse(Path(__file__).resolve().parents[1] / "docs/USER_GUIDE.html")

    @app.post("/agent/{tid}")
    async def agent(tid: str, request: Request):
        if not service.agent_valid(tid, request.headers.get("x-workspace-agent")):
            raise HttpError(403, "Invalid task connection")
        return await service.agent_call(tid, await json_body(request))

    @app.get("/{path:path}")
    async def static(path: str):
        if path == "favicon.ico":
            return Response(status_code=204)
        target = (static_dir / (path or "index.html")).resolve()
        if not target.is_relative_to(static_dir) or not target.is_file():
            raise HttpError(404, "页面尚未安装完成，请让 Codex 检查工作台。")
        return FileResponse(target)

    return app
