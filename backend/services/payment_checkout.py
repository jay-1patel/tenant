"""Create payment links for WhatsApp checkout (no admin JWT required).

Used by B2C/B2B bots after an order is placed. Reuses the same Stripe /
Razorpay / custom providers as the admin create-session route.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from database import get_db_context

logger = logging.getLogger("payment_checkout")


async def create_payment_link(
    tenant_id: str,
    order_id: str,
    amount: float,
    *,
    currency: str = "INR",
    description: str = "WhatsApp Order Payment",
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a payment URL for an order.

    Returns ``{ok, payment_url, provider, payment_id, ...}`` or
    ``{ok: False, error, skipped?}`` when no gateway is configured.
    """
    if not tenant_id or not order_id or not amount or amount <= 0:
        return {"ok": False, "error": "invalid payment request"}

    try:
        from shared.tenancy import get_profile
        profile = get_profile(tenant_id)
        if profile and not profile.features.is_on("payments"):
            return {
                "ok": False,
                "skipped": True,
                "error": "Payments feature is disabled for this tenant",
            }
    except Exception as feat_err:
        logger.debug("Could not check payments feature for tenant %s: %s", tenant_id, feat_err)

    try:
        from services.integrations import (
            CustomIntegrationService,
            RazorpayService,
            StripeService,
        )
    except Exception as exc:
        logger.error("payment integrations unavailable: %s", exc)
        return {"ok": False, "error": "payment integrations unavailable"}

    with get_db_context() as conn:
        prov = (provider or "").lower().strip()
        creds: Dict[str, Any] = {}
        if not prov:
            row = conn.execute(
                """SELECT provider, credentials_json FROM tenant_integrations
                   WHERE tenant_id = ? AND api_type = 'payment_api' AND is_active = 1
                   ORDER BY CASE WHEN status = 'verified' THEN 1 ELSE 2 END ASC LIMIT 1""",
                (tenant_id,),
            ).fetchone()
            if not row:
                return {
                    "ok": False,
                    "skipped": True,
                    "error": "No active payment gateway configured",
                }
            prov = row["provider"]
            creds = json.loads(row["credentials_json"] or "{}")
        else:
            row = conn.execute(
                """SELECT credentials_json FROM tenant_integrations
                   WHERE tenant_id = ? AND provider = ? AND is_active = 1 LIMIT 1""",
                (tenant_id, prov),
            ).fetchone()
            if not row:
                return {"ok": False, "error": f"Provider '{prov}' is not configured"}
            creds = json.loads(row["credentials_json"] or "{}")

        result: Dict[str, Any] = {"ok": False, "error": "Provider not supported"}
        if "stripe" in prov:
            api_key = creds.get("secret_key") or creds.get("api_key") or ""
            result = await StripeService.create_checkout_session(
                api_key=api_key,
                amount=amount,
                currency=currency,
                order_id=order_id,
                description=description,
                customer_email=customer_email,
            )
        elif "razorpay" in prov:
            key_id = creds.get("key_id") or creds.get("api_key") or ""
            key_secret = creds.get("key_secret") or creds.get("secret") or ""
            result = await RazorpayService.create_payment_link(
                key_id=key_id,
                key_secret=key_secret,
                amount=amount,
                currency=currency,
                order_id=order_id,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                description=description,
            )
        elif "custom" in prov:
            endpoint_url = creds.get("endpoint_url") or creds.get("api_url") or ""
            auth_header = creds.get("auth_header") or creds.get("api_key") or ""
            result = await CustomIntegrationService.process_custom_payment(
                endpoint_url=endpoint_url,
                auth_header=auth_header,
                amount=amount,
                currency=currency,
                order_id=order_id,
                customer_phone=customer_phone,
            )

        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "Payment link generation failed"),
                "provider": prov,
            }

        payment_id = (
            result.get("payment_link_id")
            or result.get("session_id")
            or result.get("payment_id")
            or ""
        )
        payment_url = result.get("payment_url") or ""

        try:
            conn.execute(
                """INSERT INTO tenant_payments
                   (tenant_id, order_id, provider, amount, currency, payment_id,
                    session_id, payment_url, status, raw_response)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created', ?)""",
                (
                    tenant_id,
                    order_id,
                    prov,
                    amount,
                    currency,
                    payment_id,
                    result.get("session_id"),
                    payment_url,
                    json.dumps(result),
                ),
            )
            # Mark order as awaiting online payment (not COD).
            conn.execute(
                """UPDATE orders SET payment_status = 'pending', payment_method = ?
                   WHERE order_number = ? AND tenant_id = ?""",
                (prov, order_id, tenant_id),
            )
        except Exception as exc:
            logger.warning("Could not persist payment row for %s: %s", order_id, exc)

        return {
            "ok": True,
            "provider": prov,
            "order_id": order_id,
            "payment_url": payment_url,
            "payment_id": payment_id,
            "amount": amount,
            "currency": currency,
        }


def mark_order_paid(tenant_id: str, order_id: str, payment_id: str = "") -> bool:
    """Flip order + tenant_payments to paid after a gateway webhook."""
    if not tenant_id or not order_id:
        return False
    try:
        with get_db_context() as conn:
            conn.execute(
                """UPDATE orders SET payment_status = 'paid', status = CASE
                       WHEN status = 'placed' THEN 'confirmed' ELSE status END
                   WHERE order_number = ? AND tenant_id = ?""",
                (order_id, tenant_id),
            )
            if payment_id:
                conn.execute(
                    """UPDATE tenant_payments SET status = 'paid'
                       WHERE tenant_id = ? AND (order_id = ? OR payment_id = ? OR session_id = ?)""",
                    (tenant_id, order_id, payment_id, payment_id),
                )
            else:
                conn.execute(
                    """UPDATE tenant_payments SET status = 'paid'
                       WHERE tenant_id = ? AND order_id = ?""",
                    (tenant_id, order_id),
                )
        return True
    except Exception as exc:
        logger.error("mark_order_paid failed tenant=%s order=%s: %s", tenant_id, order_id, exc)
        return False


def resolve_tenant_id_for_wa(wa_id: str) -> str:
    try:
        from shared.tenancy.resolver import resolve_tenant_for_user
        return resolve_tenant_for_user(wa_id) or ""
    except Exception:
        return ""
