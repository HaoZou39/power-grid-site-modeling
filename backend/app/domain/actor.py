"""The user resolved from the server session. Request bodies never supply this."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    id: str
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)
