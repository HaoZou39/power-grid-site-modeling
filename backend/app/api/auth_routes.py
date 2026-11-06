"""Login, logout, and the small admin account list."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.actor import Actor
from backend.app.infrastructure.account_store import SESSION_HOURS, AccountStore

router = APIRouter(prefix="/api/v1", tags=["auth"])
COOKIE = "site_session"
_USERNAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str = Field(min_length=8)
    role: str


class UserPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=8)


def _store(request: Request) -> AccountStore:
    return request.app.state.account_store


def _actor(request: Request) -> Actor:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "请先登录"})
    return actor


def _public_user(user) -> dict[str, str | None]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "disabled_at": user.disabled_at,
        "created_at": user.created_at,
    }


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _check_username(username: str) -> None:
    if not _USERNAME.fullmatch(username):
        raise HTTPException(status_code=422, detail={"code": "invalid_username", "message": "用户名只能包含字母、数字、下划线和短横线"})


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    store = _store(request)
    try:
        user = store.authenticate(payload.username, payload.password)
    except PermissionError:
        raise HTTPException(status_code=429, detail={"code": "login_limited", "message": "登录尝试过多，请稍后再试"}) from None
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "login_failed", "message": "用户名或密码不正确"})
    token, csrf, _expires = store.create_session(user.id)
    set_session_cookie(response, request, token)
    return {"user": _public_user(user), "csrf_token": csrf}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE, "")
    if token:
        _store(request).delete_session(token)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request) -> dict:
    actor = _actor(request)
    user = _store(request).get_user(actor.id)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "请先登录"})
    _session = _store(request).session_user(request.cookies.get(COOKIE, ""))
    csrf = _session[1] if _session else ""
    return {"user": _public_user(user), "csrf_token": csrf}


def _require_admin(request: Request) -> Actor:
    actor = _actor(request)
    if not actor.is_admin:
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "需要管理员"})
    return actor


@router.get("/admin/users")
def list_users(request: Request) -> dict:
    _require_admin(request)
    return {"users": [_public_user(user) for user in _store(request).list_users()]}


@router.post("/admin/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateRequest, request: Request) -> dict:
    _require_admin(request)
    _check_username(payload.username)
    if payload.role not in {"admin", "user"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_role", "message": "角色只能是 admin 或 user"})
    try:
        user = _store(request).create_user(payload.username, payload.password, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_user", "message": str(exc)}) from exc
    return _public_user(user)


@router.patch("/admin/users/{user_id}")
def patch_user(user_id: str, payload: UserPatchRequest, request: Request) -> dict:
    actor = _require_admin(request)
    store = _store(request)
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "user_not_found", "message": "用户不存在"})
    if payload.disabled is True:
        if user.id == actor.id:
            raise HTTPException(status_code=422, detail={"code": "cannot_disable_self", "message": "不能停用当前登录的管理员"})
        if user.role == "admin" and user.disabled_at is None and store.active_admin_count() <= 1:
            raise HTTPException(status_code=422, detail={"code": "last_admin", "message": "不能停用最后一个管理员"})
        updated = store.set_disabled(user_id, True)
    elif payload.disabled is False:
        updated = store.set_disabled(user_id, False)
    else:
        updated = user
    if payload.password:
        store.set_password(user_id, payload.password)
        updated = store.get_user(user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail={"code": "user_not_found", "message": "用户不存在"})
    return _public_user(updated)
