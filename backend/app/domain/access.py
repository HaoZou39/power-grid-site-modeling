"""Ownership checks. A missing owner is invalid and is not treated as the admin."""

from __future__ import annotations

import logging

from backend.app.domain.actor import Actor

logger = logging.getLogger(__name__)


def owner_of(summary: dict) -> str | None:
    value = summary.get("owner_id")
    if isinstance(value, str) and value:
        return value
    return None


def can_read_owned(owner_id: str | None, actor: Actor, *, kind: str, resource_id: str) -> bool:
    if not owner_id:
        logger.error("invalid unowned %s %s", kind, resource_id)
        return False
    if actor.is_admin:
        return True
    return owner_id == actor.id
