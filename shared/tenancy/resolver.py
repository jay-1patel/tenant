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


def resolve_tenant_from_payload(payload: Dict[str, Any]) -> str:
    """Tenant for an inbound webhook body. Falls back to the default tenant."""
    from . import store  # local import: store needs the backend on sys.path

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
        try:
            from services.alerts import send_alert
            send_alert(
                "Unbound WABA phone id(s) %s — messages are being "
                "attributed to the default tenant '%s'. Bind the number to a "
                "tenant to fix attribution." % (
                    _extract_phone_ids(payload or {}), fallback,
                ),
                severity="warning",
            )
        except Exception:
            pass
    return fallback


def resolve_tenant_for_phone(phone_id: str, default: Optional[str] = None) -> str:
    """Tenant for a known phone-number id (test harness, admin simulator)."""
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
      1. ``DEFAULT_TENANT_ID`` from the environment, if that tenant is registered
      2. the single active tenant, when exactly one is registered
      3. the literal default id as a last resort

    Step 1 checks registration on purpose. The single-shop deployment that
    predates tenants has exactly one registered tenant and no
    ``DEFAULT_TENANT_ID``; falling back to a literal id would build a synthetic
    ``generic`` profile, whose feature flags have commerce off, and silently
    lock every existing shopper out of their cart.
    """
    from . import store

    configured = os.getenv("DEFAULT_TENANT_ID", "").strip() or DEFAULT_TENANT_ID
    if store.get_tenant(configured):
        return configured

    active = [t for t in store.list_tenants(status="active") if t.get("id")]
    if len(active) == 1:
        return active[0]["id"]
    if active:
        # Ambiguous. Guessing would route users to a tenant they do not belong
        # to, so say so and let the deployment pin DEFAULT_TENANT_ID.
        logger.warning(
            "DEFAULT_TENANT_ID is not set and %d tenants are registered (%s); "
            "falling back to %r. Set DEFAULT_TENANT_ID to the owning tenant.",
            len(active), ", ".join(sorted(t["id"] for t in active)), configured,
        )
    return configured


def resolve_tenant_for_user(wa_id: str, default: Optional[str] = None) -> str:
    """Tenant that owns a WhatsApp user.

    Lets the service layer enforce feature flags without threading ``tenant_id``
    through every ``cart_service``/``order_service`` signature. ``user_states``
    is keyed by ``wa_id`` and already carries ``tenant_id`` (D3), so the owner of
    a conversation is a single indexed read.

    Falls back to :func:`resolve_default_tenant` when the user has no state row
    yet - the pre-tenant single-tenant stack, where every user belongs to one
    shop.
    """
    if not wa_id:
        return default or resolve_default_tenant()

    from . import store

    tid = store.tenant_id_for_user(wa_id)
    if tid:
        return tid
    return default or resolve_default_tenant()
