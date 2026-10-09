"""Connected Payment and Logistics API Routes."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from database import get_db, get_db_context, record_admin_audit_event
from routes.auth import get_current_admin, has_permission, require_tenant_access
from services.integrations import (
    BlueDartService,
    CustomIntegrationService,
    RazorpayService,
    StripeService,
    XpressbeesService,
)

logger = logging.getLogger("integrations_router")
router = APIRouter(tags=["integrations"])


# ── Pydantic Request Models ───────────────────────────────────────────

class IntegrationConfigInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    api_type: Literal["payment_api", "order_api"]
    environment: Literal["sandbox", "production"] = "sandbox"
    is_active: bool = True
    credentials: Dict[str, Any] = Field(default_factory=dict)
    webhook_secret: str = ""


class TestConnectionInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    api_type: Literal["payment_api", "order_api"]
    environment: Literal["sandbox", "production"] = "sandbox"
    credentials: Dict[str, Any] = Field(default_factory=dict)


class CreatePaymentSessionInput(BaseModel):
    order_id: str
    amount: float = Field(gt=0)
    currency: str = "INR"
    provider: Optional[str] = None
    description: str = "Checkout Payment"
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class BookShipmentInput(BaseModel):
    order_id: str
    provider: Optional[str] = None
    origin_pincode: str
    destination_pincode: str
    customer_name: str
    customer_phone: str
    weight_kg: float = 0.5
    item_description: str = "Standard Package"
    cod: bool = False
    cod_amount: float = 0.0


# ── Helpers ───────────────────────────────────────────────────────────

def _mask_credentials(creds: Dict[str, Any]) -> Dict[str, Any]:
    """Mask sensitive keys for frontend display."""
    masked = {}
    for k, v in creds.items():
        if isinstance(v, str):
            if len(v) > 8 and any(secret_word in k.lower() for secret_word in ["key", "secret", "password", "token"]):
                masked[k] = f"{v[:4]}...{v[-4:]}"
            else:
                masked[k] = v
        else:
            masked[k] = v
    return masked


def _get_tenant_integration(conn, tenant_id: str, provider: str) -> Optional[dict]:
    row = conn.execute(
        """SELECT * FROM tenant_integrations WHERE tenant_id = ? AND LOWER(provider) = LOWER(?)""",
        (tenant_id, provider),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["credentials"] = json.loads(d.get("credentials_json") or "{}")
    except Exception:
        d["credentials"] = {}
    return d


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/api/tenants/{tenant_id}/integrations")
def list_integrations(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_access),
):
    """List all configured integrations and their live connection status."""
    with get_db_context() as conn:
        rows = conn.execute(
            """SELECT id, tenant_id, provider, api_type, environment, is_active,
                      credentials_json, webhook_secret, status, last_tested_at, last_error,
                      created_at, updated_at
               FROM tenant_integrations WHERE tenant_id = ? ORDER BY provider ASC""",
            (tenant_id,),
        ).fetchall()

    integrations = []
    for r in rows:
        d = dict(r)
        try:
            creds = json.loads(d.get("credentials_json") or "{}")
        except Exception:
            creds = {}
        d["credentials_masked"] = _mask_credentials(creds)
        d["has_credentials"] = bool(creds)
        del d["credentials_json"]
        integrations.append(d)

    return {"integrations": integrations}


@router.post("/api/tenants/{tenant_id}/integrations/{provider}/config")
async def save_integration_config(
    tenant_id: str,
    provider: str,
    body: IntegrationConfigInput,
    current_admin: dict = Depends(require_tenant_access),
):
    """Save or update real API credentials for Stripe, Razorpay, Blue Dart, Xpressbees or Custom."""
    prov = provider.lower().strip()
    with get_db_context() as conn:
        existing = _get_tenant_integration(conn, tenant_id, prov)
        creds = body.credentials or {}
        if existing and not creds:
            # Preserve existing if not overwritten with blanks
            creds = existing.get("credentials", {})

        creds_json = json.dumps(creds)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO tenant_integrations
               (tenant_id, provider, api_type, environment, is_active, credentials_json, webhook_secret, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'configured', ?)
               ON CONFLICT(tenant_id, provider) DO UPDATE SET
                   api_type = excluded.api_type,
                   environment = excluded.environment,
                   is_active = excluded.is_active,
                   credentials_json = excluded.credentials_json,
                   webhook_secret = excluded.webhook_secret,
                   status = 'configured',
                   updated_at = excluded.updated_at""",
            (
                tenant_id,
                prov,
                body.api_type,
                body.environment,
                1 if body.is_active else 0,
                creds_json,
                body.webhook_secret,
                now,
            ),
        )
        record_admin_audit_event(
            conn,
            action="integration_configured",
            actor=current_admin,
            resource_type="integration",
            resource_id=f"{tenant_id}/{prov}",
            tenant_id=tenant_id,
            details={
                "provider": prov,
                "api_type": body.api_type,
                "environment": body.environment,
                "is_active": body.is_active,
                "has_webhook_secret": bool(body.webhook_secret),
                "configured_keys": sorted(creds.keys()),
            },
        )

    return {
        "ok": True,
        "message": f"{provider.capitalize()} integration configuration saved successfully",
        "provider": prov,
        "has_credentials": bool(creds),
    }


@router.post("/api/tenants/{tenant_id}/integrations/{provider}/test")
async def test_integration_connection(
    tenant_id: str,
    provider: str,
    body: Optional[TestConnectionInput] = None,
    current_admin: dict = Depends(require_tenant_access),
):
    """Perform a live API connection test with Stripe, Razorpay, Blue Dart, Xpressbees or Custom."""
    prov = provider.lower().strip()
    creds = body.credentials if (body and body.credentials) else {}
    env = body.environment if body else "sandbox"

    with get_db_context() as conn:
        if not creds:
            existing = _get_tenant_integration(conn, tenant_id, prov)
            if existing:
                creds = existing.get("credentials", {})
                env = existing.get("environment", "sandbox")

        if not creds:
            raise HTTPException(status_code=400, detail="No credentials configured to test")

        test_result = {"ok": False, "error": "Unknown provider"}

        # Route test to specific service
        if "stripe" in prov:
            api_key = creds.get("secret_key") or creds.get("api_key") or ""
            test_result = await StripeService.test_connection(api_key)
        elif "razorpay" in prov:
            key_id = creds.get("key_id") or creds.get("api_key") or ""
            key_secret = creds.get("key_secret") or creds.get("secret") or ""
            test_result = await RazorpayService.test_connection(key_id, key_secret)
        elif "bluedart" in prov or "blue_dart" in prov:
            customer_code = creds.get("customer_code") or ""
            license_key = creds.get("license_key") or ""
            login_id = creds.get("login_id") or "BD_USER"
            test_result = await BlueDartService.test_connection(customer_code, license_key, login_id, sandbox=(env == "sandbox"))
        elif "xpressbees" in prov:
            email = creds.get("email") or ""
            password = creds.get("password") or ""
            token = creds.get("token") or creds.get("api_token") or ""
            test_result = await XpressbeesService.test_connection(email, password, token, sandbox=(env == "sandbox"))
        elif "custom" in prov:
            endpoint_url = creds.get("endpoint_url") or creds.get("api_url") or ""
            auth_header = creds.get("auth_header") or creds.get("api_key") or ""
            test_result = await CustomIntegrationService.test_connection(endpoint_url, auth_header)

        # Update integration status in DB
        new_status = "verified" if test_result.get("ok") else "error"
        last_error = "" if test_result.get("ok") else test_result.get("error", "Test failed")
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """UPDATE tenant_integrations
               SET status = ?, last_tested_at = ?, last_error = ?, updated_at = ?
               WHERE tenant_id = ? AND LOWER(provider) = LOWER(?)""",
            (new_status, now, last_error, now, tenant_id, prov),
        )

        record_admin_audit_event(
            conn,
            action="integration_tested",
            actor=current_admin,
            outcome="success" if test_result.get("ok") else "failure",
            resource_type="integration",
            resource_id=f"{tenant_id}/{prov}",
            tenant_id=tenant_id,
            details={
                "provider": prov,
                "environment": env,
                "test_status": new_status,
                "error": last_error or None,
            },
        )

    return {
        "ok": test_result.get("ok", False),
        "provider": prov,
        "status": new_status,
        "details": test_result,
    }


# ── Payment Operations ────────────────────────────────────────────────

@router.post("/api/tenants/{tenant_id}/payments/create-session")
async def create_payment_session(
    tenant_id: str,
    body: CreatePaymentSessionInput,
    current_admin: dict = Depends(require_tenant_access),
):
    """Create a real payment link / session using active payment integration (Stripe, Razorpay, or Custom)."""
    with get_db_context() as conn:
        prov = (body.provider or "").lower().strip()
        if not prov:
            # Pick active verified payment provider
            row = conn.execute(
                """SELECT provider, credentials_json FROM tenant_integrations
                   WHERE tenant_id = ? AND api_type = 'payment_api' AND is_active = 1
                   ORDER BY CASE WHEN status = 'verified' THEN 1 ELSE 2 END ASC LIMIT 1""",
                (tenant_id,),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=400,
                    detail="No active payment gateway configured. Please configure Stripe, Razorpay, or Custom Payment first.",
                )
            prov = row["provider"]
            creds = json.loads(row["credentials_json"] or "{}")
        else:
            integration = _get_tenant_integration(conn, tenant_id, prov)
            if not integration:
                raise HTTPException(status_code=404, detail=f"Provider '{prov}' is not configured for this tenant")
            creds = integration.get("credentials", {})

        result = {"ok": False, "error": "Provider not supported"}

        if "stripe" in prov:
            api_key = creds.get("secret_key") or creds.get("api_key") or ""
            result = await StripeService.create_checkout_session(
                api_key=api_key,
                amount=body.amount,
                currency=body.currency,
                order_id=body.order_id,
                description=body.description,
                customer_email=body.customer_email,
                success_url=body.success_url,
                cancel_url=body.cancel_url,
            )
        elif "razorpay" in prov:
            key_id = creds.get("key_id") or creds.get("api_key") or ""
            key_secret = creds.get("key_secret") or creds.get("secret") or ""
            result = await RazorpayService.create_payment_link(
                key_id=key_id,
                key_secret=key_secret,
                amount=body.amount,
                currency=body.currency,
                order_id=body.order_id,
                customer_name=body.customer_name,
                customer_phone=body.customer_phone,
                customer_email=body.customer_email,
                description=body.description,
            )
        elif "custom" in prov:
            endpoint_url = creds.get("endpoint_url") or creds.get("api_url") or ""
            auth_header = creds.get("auth_header") or creds.get("api_key") or ""
            result = await CustomIntegrationService.process_custom_payment(
                endpoint_url=endpoint_url,
                auth_header=auth_header,
                amount=body.amount,
                currency=body.currency,
                order_id=body.order_id,
                customer_phone=body.customer_phone,
            )

        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Payment link generation failed"))

        # Save payment transaction in DB
        payment_id = result.get("payment_link_id") or result.get("session_id") or result.get("payment_id") or ""
        payment_url = result.get("payment_url") or ""

        conn.execute(
            """INSERT INTO tenant_payments
               (tenant_id, order_id, provider, amount, currency, payment_id, session_id, payment_url, status, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created', ?)""",
            (
                tenant_id,
                body.order_id,
                prov,
                body.amount,
                body.currency,
                payment_id,
                result.get("session_id"),
                payment_url,
                json.dumps(result),
            ),
        )

    return {
        "ok": True,
        "provider": prov,
        "order_id": body.order_id,
        "payment_url": payment_url,
        "payment_id": payment_id,
        "amount": body.amount,
        "currency": body.currency,
    }


# ── Shipping Operations ───────────────────────────────────────────────

@router.post("/api/tenants/{tenant_id}/shipping/book-shipment")
async def book_shipment(
    tenant_id: str,
    body: BookShipmentInput,
    current_admin: dict = Depends(require_tenant_access),
):
    """Book shipment and generate live AWB with Blue Dart, Xpressbees, or Custom."""
    with get_db_context() as conn:
        prov = (body.provider or "").lower().strip()
        if not prov:
            row = conn.execute(
                """SELECT provider, credentials_json FROM tenant_integrations
                   WHERE tenant_id = ? AND api_type = 'order_api' AND is_active = 1
                   ORDER BY CASE WHEN status = 'verified' THEN 1 ELSE 2 END ASC LIMIT 1""",
                (tenant_id,),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=400,
                    detail="No active shipping provider configured. Please configure Blue Dart, Xpressbees, or Custom Shipping first.",
                )
            prov = row["provider"]
            creds = json.loads(row["credentials_json"] or "{}")
        else:
            integration = _get_tenant_integration(conn, tenant_id, prov)
            if not integration:
                raise HTTPException(status_code=404, detail=f"Shipping provider '{prov}' is not configured")
            creds = integration.get("credentials", {})

        result = {"ok": False, "error": "Provider not supported"}

        if "bluedart" in prov or "blue_dart" in prov:
            result = await BlueDartService.book_shipment(
                customer_code=creds.get("customer_code", "DEMO_CUST"),
                license_key=creds.get("license_key", "DEMO_KEY"),
                login_id=creds.get("login_id", "BD_USER"),
                order_id=body.order_id,
                origin_pincode=body.origin_pincode,
                destination_pincode=body.destination_pincode,
                customer_name=body.customer_name,
                customer_phone=body.customer_phone,
                weight_kg=body.weight_kg,
                item_description=body.item_description,
                cod_amount=body.cod_amount if body.cod else 0.0,
            )
        elif "xpressbees" in prov:
            result = await XpressbeesService.book_shipment(
                order_id=body.order_id,
                origin_pincode=body.origin_pincode,
                destination_pincode=body.destination_pincode,
                customer_name=body.customer_name,
                customer_phone=body.customer_phone,
                token=creds.get("token") or creds.get("api_token"),
                weight_kg=body.weight_kg,
                cod=body.cod,
                cod_amount=body.cod_amount,
            )
        elif "custom" in prov:
            endpoint_url = creds.get("endpoint_url") or creds.get("api_url") or ""
            auth_header = creds.get("auth_header") or creds.get("api_key") or ""
            result = await CustomIntegrationService.process_custom_shipping(
                endpoint_url=endpoint_url,
                auth_header=auth_header,
                order_id=body.order_id,
                origin_pincode=body.origin_pincode,
                destination_pincode=body.destination_pincode,
                customer_name=body.customer_name,
                customer_phone=body.customer_phone,
            )

        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Shipment booking failed"))

        awb = result.get("awb_number", "")
        tracking_url = result.get("tracking_url", "")

        conn.execute(
            """INSERT INTO tenant_shipments
               (tenant_id, order_id, provider, awb_number, tracking_url, status, origin_pincode, destination_pincode, customer_name, customer_phone, raw_response)
               VALUES (?, ?, ?, ?, ?, 'booked', ?, ?, ?, ?, ?)""",
            (
                tenant_id,
                body.order_id,
                prov,
                awb,
                tracking_url,
                body.origin_pincode,
                body.destination_pincode,
                body.customer_name,
                body.customer_phone,
                json.dumps(result),
            ),
        )

    return {
        "ok": True,
        "provider": prov,
        "order_id": body.order_id,
        "awb_number": awb,
        "tracking_url": tracking_url,
        "status": "booked",
    }


@router.get("/api/tenants/{tenant_id}/shipping/track/{awb}")
async def track_shipment(
    tenant_id: str,
    awb: str,
    current_admin: dict = Depends(require_tenant_access),
):
    """Track shipment status by AWB."""
    with get_db_context() as conn:
        row = conn.execute(
            """SELECT * FROM tenant_shipments WHERE tenant_id = ? AND awb_number = ?""",
            (tenant_id, awb),
        ).fetchone()

        prov = row["provider"] if row else "bluedart"
        integration = _get_tenant_integration(conn, tenant_id, prov)
        creds = integration.get("credentials", {}) if integration else {}

        if "bluedart" in prov:
            return await BlueDartService.track_shipment(
                awb,
                license_key=creds.get("license_key", ""),
                login_id=creds.get("login_id", ""),
            )
        elif "xpressbees" in prov:
            return await XpressbeesService.track_shipment(
                awb,
                token=creds.get("token") or creds.get("api_token"),
            )
        else:
            return {
                "ok": True,
                "awb": awb,
                "status": "In Transit",
                "carrier": prov.capitalize(),
                "tracking_url": f"https://example.com/track/{awb}",
            }


# ── Webhook Handlers ──────────────────────────────────────────────────

@router.post("/api/webhooks/payments/{tenant_id}/{provider}")
async def payment_webhook(tenant_id: str, provider: str, request: Request):
    """Universal webhook handler for incoming payment events (Stripe / Razorpay)."""
    prov = provider.lower().strip()
    payload = await request.body()
    headers = request.headers

    with get_db_context() as conn:
        integration = _get_tenant_integration(conn, tenant_id, prov)
        secret = integration.get("webhook_secret", "") if integration else ""

        if "stripe" in prov:
            sig = headers.get("stripe-signature", "")
            if secret and not StripeService.verify_webhook_signature(payload, sig, secret):
                raise HTTPException(status_code=400, detail="Invalid Stripe signature")
        elif "razorpay" in prov:
            sig = headers.get("x-razorpay-signature", "")
            if secret and not RazorpayService.verify_webhook_signature(payload, sig, secret):
                raise HTTPException(status_code=400, detail="Invalid Razorpay signature")

    logger.info(f"Payment webhook received for tenant={tenant_id}, provider={prov}")
    return {"status": "received", "tenant_id": tenant_id, "provider": prov}
