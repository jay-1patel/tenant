"""Context helpers for request metadata and mutation actors in audit events."""

from __future__ import annotations

import contextvars

_audit_actor: contextvars.ContextVar = contextvars.ContextVar("audit_actor", default=None)
_original_writer = None


def set_audit_actor(actor: dict | None) -> None:
    _audit_actor.set(dict(actor) if actor else None)


def clear_audit_actor() -> None:
    _audit_actor.set(None)


def get_audit_actor() -> dict | None:
    actor = _audit_actor.get()
    return dict(actor) if actor else None


def actor_from_context(explicit_actor: dict | None = None) -> dict | None:
    actor = explicit_actor or get_audit_actor()
    if not actor:
        return None
    if actor.get("type") == "tenant":
        return {
            **actor,
            "type": "tenant_token",
            "username": actor.get("label") or "tenant",
            "role": "tenant_token",
        }
    return actor


def install_writer_context(database_module) -> None:
    """Wrap the shared writer so helpers without actor params still attribute the request."""
    global _original_writer
    if _original_writer is not None:
        return
    _original_writer = database_module.record_admin_audit_event

    def record_with_context(conn, **kwargs):
        if not kwargs.get("actor"):
            kwargs["actor"] = get_audit_actor()
        return _original_writer(conn, **kwargs)

    database_module.record_admin_audit_event = record_with_context
