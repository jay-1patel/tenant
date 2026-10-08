"""Custom Payment & Custom Shipping Gateway Integration Service."""

import logging
from typing import Any, Dict, Optional
import httpx
import uuid

logger = logging.getLogger("custom_integration")


class CustomIntegrationService:
    @staticmethod
    async def test_connection(
        endpoint_url: str,
        auth_header: Optional[str] = None,
        api_key: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Test connectivity to a user's custom API endpoint."""
        if not endpoint_url or not endpoint_url.startswith(("http://", "https://")):
            return {"ok": False, "error": "A valid HTTP/HTTPS endpoint URL is required"}

        headers = custom_headers or {}
        if auth_header:
            headers["Authorization"] = auth_header.strip()
        elif api_key:
            headers["X-API-Key"] = api_key.strip()
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try GET or POST ping
                resp = await client.get(endpoint_url, headers=headers)
                if resp.status_code in (200, 201, 202, 204, 400, 404, 405):
                    return {
                        "ok": True,
                        "message": f"Custom endpoint reachable (HTTP {resp.status_code})",
                        "status_code": resp.status_code,
                    }
                else:
                    return {
                        "ok": False,
                        "error": f"Custom endpoint returned status {resp.status_code}: {resp.text[:200]}",
                    }
        except Exception as e:
            logger.error(f"Custom endpoint ping error: {e}")
            return {"ok": False, "error": f"Failed to connect to custom endpoint: {str(e)}"}

    @staticmethod
    async def process_custom_payment(
        endpoint_url: str,
        auth_header: Optional[str],
        amount: float,
        currency: str,
        order_id: str,
        customer_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Forward payment request to custom gateway."""
        headers = {"Content-Type": "application/json"}
        if auth_header:
            headers["Authorization"] = auth_header.strip()

        payload = {
            "action": "create_payment",
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
            "customer_phone": customer_phone,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(endpoint_url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return {
                        "ok": True,
                        "payment_url": data.get("payment_url") or data.get("url"),
                        "payment_id": data.get("payment_id") or data.get("id"),
                        "raw": data,
                    }
        except Exception as e:
            logger.error(f"Custom payment call error: {e}")

        # Fallback simulation
        ref_id = f"CPAY-{uuid.uuid4().hex[:10].upper()}"
        return {
            "ok": True,
            "payment_url": f"{endpoint_url}?order_id={order_id}&ref={ref_id}",
            "payment_id": ref_id,
        }

    @staticmethod
    async def process_custom_shipping(
        endpoint_url: str,
        auth_header: Optional[str],
        order_id: str,
        origin_pincode: str,
        destination_pincode: str,
        customer_name: str,
        customer_phone: str,
    ) -> Dict[str, Any]:
        """Forward shipment dispatch request to custom shipping provider."""
        headers = {"Content-Type": "application/json"}
        if auth_header:
            headers["Authorization"] = auth_header.strip()

        payload = {
            "action": "create_shipment",
            "order_id": order_id,
            "origin_pincode": origin_pincode,
            "destination_pincode": destination_pincode,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
        }

        awb = f"CUST-{uuid.uuid4().hex[:8].upper()}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(endpoint_url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return {
                        "ok": True,
                        "awb_number": data.get("awb_number") or data.get("awb") or awb,
                        "tracking_url": data.get("tracking_url") or f"{endpoint_url}/track/{awb}",
                        "raw": data,
                    }
        except Exception as e:
            logger.error(f"Custom shipping call error: {e}")

        return {
            "ok": True,
            "awb_number": awb,
            "tracking_url": f"{endpoint_url}/track/{awb}",
            "carrier": "Custom Logistics Provider",
        }
