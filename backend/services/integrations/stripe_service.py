"""Stripe Payment Integration Service using direct REST API calls."""

import hmac
import hashlib
import time
import logging
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger("stripe_integration")
STRIPE_API_BASE = "https://api.stripe.com/v1"


class StripeService:
    @staticmethod
    async def test_connection(api_key: str) -> Dict[str, Any]:
        """Test Stripe credentials by querying account balance / account details."""
        if not api_key:
            return {"ok": False, "error": "Stripe Secret Key is required"}
        
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{STRIPE_API_BASE}/balance", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    available = data.get("available", [])
                    currencies = [item.get("currency", "").upper() for item in available]
                    return {
                        "ok": True,
                        "message": "Stripe connection verified successfully",
                        "livemode": data.get("livemode", False),
                        "currencies": currencies or ["USD", "INR", "EUR"],
                    }
                else:
                    err = resp.json().get("error", {}).get("message", resp.text)
                    return {"ok": False, "error": f"Stripe error ({resp.status_code}): {err}"}
        except Exception as e:
            logger.error(f"Stripe test connection failed: {e}")
            return {"ok": False, "error": f"Network or connection error: {str(e)}"}

    @staticmethod
    async def create_checkout_session(
        api_key: str,
        amount: float,
        currency: str = "inr",
        order_id: str = "ORD-001",
        description: str = "Order Payment",
        customer_email: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Stripe Checkout Session."""
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        # Stripe expects smallest currency unit (e.g. cents/paise)
        unit_amount = int(round(amount * 100))
        cur = (currency or "inr").lower()

        data = {
            "payment_method_types[0]": "card",
            "mode": "payment",
            "line_items[0][price_data][currency]": cur,
            "line_items[0][price_data][unit_amount]": str(unit_amount),
            "line_items[0][price_data][product_data][name]": f"Order #{order_id} - {description}",
            "line_items[0][quantity]": "1",
            "client_reference_id": order_id,
            "success_url": success_url or f"https://example.com/payment/success?order_id={order_id}",
            "cancel_url": cancel_url or f"https://example.com/payment/cancel?order_id={order_id}",
            "metadata[order_id]": order_id,
        }
        if customer_email:
            data["customer_email"] = customer_email

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{STRIPE_API_BASE}/checkout/sessions", headers=headers, data=data)
                if resp.status_code in (200, 201):
                    session = resp.json()
                    return {
                        "ok": True,
                        "session_id": session.get("id"),
                        "payment_url": session.get("url"),
                        "status": session.get("payment_status"),
                        "raw": session,
                    }
                else:
                    err = resp.json().get("error", {}).get("message", resp.text)
                    return {"ok": False, "error": f"Stripe Checkout creation failed: {err}"}
        except Exception as e:
            logger.error(f"Failed to create Stripe checkout session: {e}")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def verify_webhook_signature(payload: bytes, sig_header: str, secret: str, tolerance: int = 300) -> bool:
        """Verify Stripe webhook signature header (t=timestamp,v1=signature)."""
        if not sig_header or not secret:
            return False
        try:
            pairs = dict(item.split("=", 1) for item in sig_header.split(","))
            timestamp = pairs.get("t")
            signature = pairs.get("v1")
            if not timestamp or not signature:
                return False
            
            # Check timestamp freshness
            if abs(time.time() - int(timestamp)) > tolerance:
                return False

            signed_payload = f"{timestamp}.".encode("utf-8") + payload
            expected_sig = hmac.new(
                secret.encode("utf-8"),
                signed_payload,
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(expected_sig, signature)
        except Exception as e:
            logger.error(f"Stripe webhook signature verification error: {e}")
            return False
