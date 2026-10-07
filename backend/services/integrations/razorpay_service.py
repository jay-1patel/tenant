"""Razorpay Payment Integration Service using direct REST API calls."""

import hmac
import hashlib
import logging
import base64
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger("razorpay_integration")
RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class RazorpayService:
    @staticmethod
    def _get_auth_header(key_id: str, key_secret: str) -> Dict[str, str]:
        token = base64.b64encode(f"{key_id.strip()}:{key_secret.strip()}".encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    @classmethod
    async def test_connection(cls, key_id: str, key_secret: str) -> Dict[str, Any]:
        """Test Razorpay Key ID and Secret against the Razorpay REST API."""
        if not key_id or not key_secret:
            return {"ok": False, "error": "Razorpay Key ID and Key Secret are required"}

        headers = cls._get_auth_header(key_id, key_secret)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{RAZORPAY_API_BASE}/payments?count=1", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "ok": True,
                        "message": "Razorpay credentials verified successfully",
                        "count": data.get("count", 0),
                    }
                else:
                    err = resp.json().get("error", {}).get("description", resp.text)
                    return {"ok": False, "error": f"Razorpay authentication failed ({resp.status_code}): {err}"}
        except Exception as e:
            logger.error(f"Razorpay test connection failed: {e}")
            return {"ok": False, "error": f"Network or connection error: {str(e)}"}

    @classmethod
    async def create_order(
        cls,
        key_id: str,
        key_secret: str,
        amount: float,
        currency: str = "INR",
        receipt: str = "receipt_001",
        notes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a Razorpay Order for checkout."""
        headers = cls._get_auth_header(key_id, key_secret)
        unit_amount = int(round(amount * 100))  # Amount in paise

        payload = {
            "amount": unit_amount,
            "currency": currency.upper(),
            "receipt": receipt,
            "notes": notes or {"receipt": receipt},
            "payment_capture": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{RAZORPAY_API_BASE}/orders", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    order = resp.json()
                    return {
                        "ok": True,
                        "order_id": order.get("id"),
                        "amount": amount,
                        "currency": order.get("currency"),
                        "status": order.get("status"),
                        "raw": order,
                    }
                else:
                    err = resp.json().get("error", {}).get("description", resp.text)
                    return {"ok": False, "error": f"Order creation failed: {err}"}
        except Exception as e:
            logger.error(f"Failed to create Razorpay order: {e}")
            return {"ok": False, "error": str(e)}

    @classmethod
    async def create_payment_link(
        cls,
        key_id: str,
        key_secret: str,
        amount: float,
        currency: str = "INR",
        order_id: str = "ORD-001",
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        customer_email: Optional[str] = None,
        description: str = "WhatsApp Order Payment",
    ) -> Dict[str, Any]:
        """Create an instant Razorpay Standard Payment Link (shareable directly on WhatsApp)."""
        headers = cls._get_auth_header(key_id, key_secret)
        unit_amount = int(round(amount * 100))

        customer: Dict[str, str] = {}
        if customer_name:
            customer["name"] = customer_name
        if customer_phone:
            customer["contact"] = customer_phone.replace("+", "").strip()
        if customer_email:
            customer["email"] = customer_email

        payload: Dict[str, Any] = {
            "amount": unit_amount,
            "currency": currency.upper(),
            "accept_partial": False,
            "description": f"Order #{order_id} - {description}",
            "reference_id": order_id,
            "notes": {"order_id": order_id},
        }
        if customer:
            payload["customer"] = customer

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{RAZORPAY_API_BASE}/payment_links", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    link = resp.json()
                    return {
                        "ok": True,
                        "payment_link_id": link.get("id"),
                        "payment_url": link.get("short_url"),
                        "status": link.get("status"),
                        "raw": link,
                    }
                else:
                    err = resp.json().get("error", {}).get("description", resp.text)
                    return {"ok": False, "error": f"Payment Link creation failed: {err}"}
        except Exception as e:
            logger.error(f"Failed to create Razorpay payment link: {e}")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def verify_payment_signature(order_id: str, payment_id: str, signature: str, key_secret: str) -> bool:
        """Verify checkout payment signature (order_id|payment_id)."""
        if not signature or not key_secret:
            return False
        try:
            msg = f"{order_id}|{payment_id}".encode("utf-8")
            expected = hmac.new(key_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.error(f"Razorpay payment signature verification error: {e}")
            return False

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
        """Verify Razorpay webhook signature header (`X-Razorpay-Signature`)."""
        if not signature or not webhook_secret:
            return False
        try:
            expected = hmac.new(webhook_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.error(f"Razorpay webhook signature verification error: {e}")
            return False
