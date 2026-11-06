"""Trusted experiment owner for the current task. Never taken from a request body."""

from __future__ import annotations

from contextvars import ContextVar, Token

_owner_id: ContextVar[str | None] = ContextVar("experiment_owner_id", default=None)


def bind_owner(owner_id: str | None) -> Token[str | None]:
    return _owner_id.set(owner_id)


def reset_owner(token: Token[str | None]) -> None:
    _owner_id.reset(token)


def current_owner_id() -> str | None:
    return _owner_id.get()


def owner_fields() -> dict[str, str]:
    owner_id = current_owner_id()
    if not owner_id:
        return {}
    return {"owner_id": owner_id}
