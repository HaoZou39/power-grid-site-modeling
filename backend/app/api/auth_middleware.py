"""Default-deny session check. Health and login stay public."""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.api.auth_routes import COOKIE
from backend.app.domain.actor import Actor, current_actor

_PUBLIC = {("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health")}
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_SCENE_ID = r"[^/]+"


def install_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_session(request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or (request.method, path) in _PUBLIC:
            return await call_next(request)
        store = request.app.state.account_store
        found = store.session_user(request.cookies.get(COOKIE, ""))
        if found is None:
            return JSONResponse(status_code=401, content={"detail": {"code": "unauthenticated", "message": "请先登录"}})
        user, csrf = found
        if request.method in _UNSAFE and request.headers.get("x-csrf-token") != csrf:
            return JSONResponse(status_code=403, content={"detail": {"code": "csrf_failed", "message": "缺少或错误的 CSRF 令牌"}})
        actor = Actor(id=user.id, username=user.username, role=user.role)
        if actor.role != "admin" and _scene_mutation(request.method, path):
            return JSONResponse(status_code=403, content={"detail": {"code": "admin_required", "message": "不能修改公共场景"}})
        request.state.actor = actor
        token = current_actor.set(actor)
        try:
            return await call_next(request)
        finally:
            current_actor.reset(token)


def _scene_mutation(method: str, path: str) -> bool:
    match = re.fullmatch(rf"/api/v1/scenes/({_SCENE_ID})(?:/(.*))?", path)
    if match is None:
        return False
    rest = match.group(2) or ""
    if rest.startswith("favorites"):
        return False
    if rest == "" :
        return method in {"DELETE", "PATCH"}
    head = rest.split("/", 1)[0]
    if head not in {"cad-files", "data-import", "protected-farmland", "landuse-patch", "landuse-edits"}:
        return False
    if method == "GET" and head == "landuse-edits" and "/" not in rest:
        return False
    if method == "GET" and head == "cad-files" and "/" not in rest:
        return False
    if method == "GET" and head == "protected-farmland" and rest.endswith("overlay"):
        return False
    if "preview" in rest.split("/"):
        return True
    return method != "GET"
