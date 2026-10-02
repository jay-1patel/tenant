"""Delivery and payment integrations, approved per tenant by a super admin.

Two halves:
  * a registry of known providers (so the chatbot can offer them as choices
    and the admin panel can render human-readable labels), and
  * ``apply_to_profile`` — the bridge that copies an approved
    integration_requests row into the tenant's published profile, where
    checkout/orders read it via ``profile.integrations``.

Provider configs are stored as opaque JSON: the shape is provider-specific
(API keys, pickup pincode, webhook secrets...). Nothing here ever calls the
provider; that stays in the commerce services so a bad key fails a shipment,
not a schema load.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("tenancy.integrations")

# ── provider registry ─────────────────────────────────────────────────────
# ``kind`` is "delivery" or "payment". ``config_fields`` is what the chatbot
# onboarding flow asks for, in order; ``secret`` marks values that must be
# masked in admin surfaces.

DELIVERY_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "shiprocket": {
        "label": "Shiprocket",
        "config_fields": [
            {"key": "email", "label": "Shiprocket account email", "secret": False},
            {"key": "password", "label": "Shiprocket password or API token", "secret": True},
            {"key": "pickup_pincode", "label": "Warehouse pickup pincode", "secret": False},
        ],
    },
    "delhivery": {
        "label": "Delhivery",
        "config_fields": [
            {"key": "api_token", "label": "Delhivery API token", "secret": True},
            {"key": "client_id", "label": "Delhivery client id (optional)", "secret": False},
            {"key": "pickup_pincode", "label": "Warehouse pickup pincode", "secret": False},
        ],
    },
    "bluedart": {
        "label": "Blue Dart",
        "config_fields": [
            {"key": "api_key", "label": "Blue Dart API key", "secret": True},
            {"key": "license_number", "label": "Blue Dart licence number", "secret": True},
        ],
    },
    "self_delivery": {
        "label": "Self / own delivery fleet",
        "config_fields": [
            {"key": "contact_number", "label": "Delivery coordination contact number", "secret": False},
            {"key": "notes", "label": "How your delivery team works (optional)", "secret": False},
        ],
    },
}

PAYMENT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "razorpay": {
        "label": "Razorpay",
        "config_fields": [
            {"key": "key_id", "label": "Razorpay Key ID", "secret": False},
            {"key": "key_secret", "label": "Razorpay Key Secret", "secret": True},
            {"key": "webhook_secret", "label": "Razorpay webhook secret (optional)", "secret": True},
        ],
    },
    "phonepe": {
        "label": "PhonePe",
        "config_fields": [
            {"key": "merchant_id", "label": "PhonePe merchant id", "secret": False},
            {"key": "api_key", "label": "PhonePe API key / salt", "secret": True},
        ],
    },
    "paytm": {
        "label": "Paytm",
        "config_fields": [
            {"key": "mid", "label": "Paytm MID", "secret": False},
            {"key": "merchant_key", "label": "Paytm merchant key", "secret": True},
        ],
    },
    "stripe": {
        "label": "Stripe",
        "config_fields": [
            {"key": "secret_key", "label": "Stripe secret key", "secret": True},
            {"key": "webhook_secret", "label": "Stripe webhook secret (optional)", "secret": True},
        ],
    },
    "upi_collect": {
        "label": "UPI (collect / QR)",
        "config_fields": [
            {"key": "upi_id", "label": "Your UPI collect id (name@bank)", "secret": False},
            {"key": "payee_name", "label": "Name shown on the UPI request", "secret": False},
        ],
    },
    "cod": {
        "label": "Cash on delivery",
        "config_fields": [
            {"key": "notes", "label": "Any COD rules (limit, areas...)", "secret": False},
        ],
    },
}

REGISTRY = {"delivery": DELIVERY_PROVIDERS, "payment": PAYMENT_PROVIDERS}


def provider_label(kind: str, provider: str) -> str:
    return REGISTRY.get(kind, {}).get(provider, {}).get("label", provider or "—")


def known_providers(kind: str) -> list:
    return sorted(REGISTRY.get(kind, {}).keys())


def config_fields(kind: str, provider: str) -> list:
    return REGISTRY.get(kind, {}).get(provider, {}).get("config_fields", [])


def mask_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of a config with secret-looking values masked for display."""
    masked = {}
    for k, v in (config or {}).items():
        s = str(v or "")
        if any(t in k.lower() for t in ("secret", "password", "token", "key")) and s:
            masked[k] = s[:3] + "•" * max(len(s) - 3, 3)
        else:
            masked[k] = s
    return masked


# ── applying an approved request to the tenant profile ────────────────────

def apply_to_profile(tenant_id: str, request: Dict[str, Any],
                     reviewed_by: str = "") -> bool:
    """Copy an approved integration request into the tenant's live profile.

    Reads the published config, merges the ``integrations`` block, and
    republishes so the in-memory profile cache picks it up. Returns True when
    the profile was updated.
    """
    try:
        from . import loader
    except Exception as exc:
        logger.error("apply_to_profile: loader unavailable: %s", exc)
        return False

    try:
        profile = loader.get_tenant_profile(tenant_id)
    except Exception as exc:
        logger.error("apply_to_profile: cannot load profile for %s: %s", tenant_id, exc)
        return False

    from . import store
    from .merge import merge_layers

    current = store.get_current_payload(tenant_id) or {}
    integrations = {
        "delivery": {
            "provider": request.get("delivery_provider") or "",
            "config": request.get("delivery_config") or {},
            "approved_by": reviewed_by,
        },
        "payment": {
            "provider": request.get("payment_provider") or "",
            "config": request.get("payment_config") or {},
            "approved_by": reviewed_by,
        },
    }
    payload = merge_layers(current, {"integrations": integrations})

    # Validate the merged draft before it reaches the bot (same gate the
    # admin publish route uses), then publish as a new version so the
    # profile cache and the rollback history both see it.
    try:
        loader.validate_merged_profile(tenant_id, payload)
    except Exception as exc:
        logger.error("apply_to_profile: merged profile invalid for %s: %s", tenant_id, exc)
        return False

    try:
        store.publish_version(tenant_id, payload, published_by=reviewed_by or "integrations")
        loader.reload_profile(tenant_id)
        logger.info("INTEGRATION_APPLIED | tenant=%s | delivery=%s | payment=%s | by=%s",
                    tenant_id, integrations["delivery"]["provider"],
                    integrations["payment"]["provider"], reviewed_by)
        return True
    except Exception as exc:
        logger.error("apply_to_profile: publish failed for %s: %s", tenant_id, exc)
        return False


def get_active(tenant_id: str, kind: str) -> Optional[Dict[str, Any]]:
    """The active approved provider config for a tenant, or None."""
    try:
        from . import loader
        profile = loader.get_tenant_profile(tenant_id)
        block = getattr(profile, "integrations", None)
        if not block:
            return None
        entry = getattr(block, kind, None)
        if entry and getattr(entry, "provider", ""):
            return {"provider": entry.provider,
                    "config": dict(getattr(entry, "config", {}) or {})}
    except Exception as exc:
        logger.error("get_active: %s", exc)
    return None
