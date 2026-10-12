"""Service to coordinate payment link creation and payment verification across bots."""

import json
import logging
from typing import Optional, Dict, Any
from database import get_db_context
from services.integrations import RazorpayService, StripeService

logger = logging.getLogger("payment_flow_service")


async def generate_payment_link_for_order(
    tenant_id: str,
    order_id: str,
    amount: float,
    currency: str = "INR",
    customer_phone: Optional[str] = None,
    customer_name: Optional[str] = None,
    description: str = "Order Payment",
) -> Optional[Dict[str, Any]]:
    """
    Check if tenant has an active payment integration (Razorpay or Stripe).
    If so, create a payment link/session and record it in tenant_payments.
    Returns dict with payment_url and provider, or None if no payment gateway is active.
    """
    if not tenant_id or amount <= 0:
        return None

    try:
        with get_db_context() as conn:
            # Check for active payment integration for this tenant
            row = conn.execute(
                """SELECT provider, credentials_json, webhook_secret, environment
                   FROM tenant_integrations
                   WHERE tenant_id = ? AND api_type = 'payment_api' AND is_active = 1
                   ORDER BY CASE WHEN status = 'verified' THEN 1 ELSE 2 END ASC LIMIT 1""",
                (tenant_id,),
            ).fetchone()

            if not row:
                return None

            provider = row["provider"].lower().strip()
            credentials = json.loads(row["credentials_json"] or "{}")

            result = {"ok": False}
            if "razorpay" in provider:
                key_id = credentials.get("key_id") or credentials.get("api_key") or ""
                key_secret = credentials.get("key_secret") or credentials.get("secret") or ""
                result = await RazorpayService.create_payment_link(
                    key_id=key_id,
                    key_secret=key_secret,
                    amount=amount,
                    currency=currency,
                    description=f"Order {order_id}",
                    order_id=order_id,
                    customer_phone=customer_phone,
                    customer_name=customer_name or "Customer",
                )
            elif "stripe" in provider:
                api_key = credentials.get("secret_key") or credentials.get("api_key") or ""
                result = await StripeService.create_payment_session(
                    api_key=api_key,
                    amount=amount,
                    currency=currency,
                    description=f"Order {order_id}",
                    order_id=order_id,
                    customer_phone=customer_phone,
                )

            if not result.get("ok"):
                logger.warning(f"Failed to generate payment link for {order_id} ({provider}): {result.get('error')}")
                return None

            payment_id = result.get("payment_link_id") or result.get("session_id") or result.get("payment_id") or ""
            payment_url = result.get("payment_url") or ""

            # Store in tenant_payments
            conn.execute(
                """INSERT INTO tenant_payments
                   (tenant_id, order_id, provider, amount, currency, payment_id, session_id, payment_url, status, raw_response)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created', ?)""",
                (
                    tenant_id,
                    order_id,
                    provider,
                    amount,
                    currency,
                    payment_id,
                    result.get("session_id"),
                    payment_url,
                    json.dumps(result),
                ),
            )

            return {
                "ok": True,
                "provider": provider,
                "payment_url": payment_url,
                "payment_id": payment_id,
            }

    except Exception as e:
        logger.error(f"Error in generate_payment_link_for_order: {e}", exc_info=True)
        return None

