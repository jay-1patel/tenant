"""Inbound WABA payload -> tenant_id.

Meta's webhook puts the phone-number id (not the WABA id) on the top-level
``entry[]`` object, and the WABA id on ``value.metadata``. We try, in order:

    entry[0].id  ->  value.metadata.phone_number_id  ->  value.metadata.display_phone_number
                 ->  env FALLBACK

The first two are numeric; the display number is not, so it is only used when
the tenant table was seeded that way. Unknown phone-ids land on the default
tenant rather than being dropped — a misconfigured client still gets a bot.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from .defaults import DEFAULT_TENANT_ID

logger = logging.getLogger("tenancy.resolver")

_UNSET = object()


def _extract_phone_ids(payload: Dict[str, Any]) -> list[str]:
    """All plausible phone-number identifiers in a WABA webhook, best first."""
    out: list[str] = []
    try:
        entry = (payload.get("entry") or [{}])[0] or {}
        changes = (entry.get("changes") or [{}])[0] or {}
        value = changes.get("value") or {}

        raw = entry.get("id")
        if raw not in (None, ""):
            out.append(str(raw))

        meta = value.get("metadata") or {}
        for key in ("phone_number_id", "display_phone_number", "display_phone_number_id"):
            val = meta.get(key)
            if val not in (None, ""):
                out.append(str(val))
    except (AttributeError, IndexError, TypeError) as exc:
        logger.debug("Could not extract phone ids from payload: %s", exc)
    return out


def _req_tenant() -> Optional[str]:
    try:
        from database import get_request_tenant
        req_t = get_request_tenant()
        if req_t:
            return str(req_t).strip()
    except Exception:
        pass
    return None


def _active_test_override() -> Optional[str]:
    try:
        from database import get_active_test_tenant
        val = get_active_test_tenant()
        if val:
            from . import store
            rec = store.get_tenant(val)
            if rec:
                return str(rec.get("slug") or rec.get("id"))
            return val
    except Exception:
        pass
    return None


def resolve_tenant_from_payload(payload: Dict[str, Any]) -> str:
    """Tenant for an inbound webhook body. Respects request context, active test tenant, then phone binding."""
    req = _req_tenant()
    if req:
        return req

    # Active test override takes precedence for single-number testing
    override = _active_test_override()
    if override:
        return override

    fallback = os.getenv("DEFAULT_TENANT_ID", DEFAULT_TENANT_ID)

    for phone_id in _extract_phone_ids(payload or {}):
        tenant_id = store.find_tenant_by_phone_id(phone_id)
        if tenant_id:
            logger.debug("Resolved tenant %s from phone id %s", tenant_id, phone_id)
            return tenant_id

    # Second pass: a tenant whose slug or id matches the id field directly.
    for candidate in _extract_phone_ids(payload or {}):
        if store.get_tenant(candidate):
            return candidate

    if _extract_phone_ids(payload or {}):
        logger.warning(
            "Unbound WABA phone id(s) %s — falling back to tenant '%s'",
            _extract_phone_ids(payload or {}), fallback,
        )
    return fallback


def resolve_tenant_for_phone(phone_id: str, default: Optional[str] = None) -> str:
    """Tenant for a known phone-number id (test harness, admin simulator)."""
    req = _req_tenant()
    if req:
        return req

    override = _active_test_override()
    if override:
        return override

    from . import store

    tid = store.find_tenant_by_phone_id(phone_id) if phone_id else None
    if tid:
        return tid
    return default or resolve_default_tenant()


def bind_phone_id(tenant_id: str, phone_id: str) -> bool:
    """Register a WABA phone-id for a tenant. Idempotent."""
    from . import store

    return store.set_waba_phone_id(tenant_id, phone_id)


def resolve_default_tenant() -> str:
    """The tenant an unrecognised request belongs to.

    Resolution order:
      0. ``_req_tenant()`` if request-scoped tenant is active
      1. ``_active_test_override()`` if active test tenant is toggled
      2. ``DEFAULT_TENANT_ID`` from the environment, if that tenant is registered
      3. the single active tenant, when exactly one is registered
      4. the literal default id as a last resort
    """
    req = _req_tenant()
    if req:
        return req

    override = _active_test_override()
    if override:
        return override

    from . import store

    configured = os.getenv("DEFAULT_TENANT_ID", "").strip() or DEFAULT_TENANT_ID
    if store.get_tenant(configured):
        return configured

    active = [t for t in store.list_tenants(status="active") if t.get("id")]
    if len(active) == 1:
        return active[0]["id"]
    if active:
        logger.warning(
            "DEFAULT_TENANT_ID is not set and %d tenants are registered (%s); "
            "falling back to %r. Set DEFAULT_TENANT_ID to the owning tenant.",
            len(active), ", ".join(sorted(str(t["id"]) for t in active)), configured,
        )
    return str(configured)


def resolve_tenant_for_user(wa_id: str, default: Optional[str] = None) -> str:
    """Tenant that owns a WhatsApp user.

    In single-number testing mode, active test tenant override takes absolute
    precedence so testers don't get trapped in stale tenant states.
    """
    req = _req_tenant()
    if req:
        return req

    override = _active_test_override()
    if override:
        return override

    if not wa_id:
        return default or resolve_default_tenant()

    from . import store

    tid = store.tenant_id_for_user(wa_id)
    if tid:
        if store.get_tenant(tid):
            return tid
        logger.warning(
            "user %s is stamped with unregistered tenant %r; falling back to default",
            wa_id, tid,
        )

    return default or resolve_default_tenant()
