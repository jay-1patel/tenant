"""Context helpers for request metadata and mutation actors in audit events."""

from __future__ import annotations

import contextvars

_audit_actor: contextvars.ContextVar = contextvars.ContextVar("audit_actor", default=None)


def set_audit_actor(actor: dict | None) -> None:
    _audit_actor.set(dict(actor) if actor else None)


def clear_audit_actor() -> None:
    _audit_actor.set(None)


def get_audit_actor() -> dict | None:
    actor = _audit_actor.get()
    return dict(actor) if actor else None


def actor_from_context(explicit_actor: dict | None = None) -> dict | None:
    return explicit_actor or get_audit_actor()
