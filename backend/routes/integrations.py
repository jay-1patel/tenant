"""Superadmin surface for delivery/payment integration requests.

A chatbot onboarding flow collects each client's delivery and payment API
details and files them as `pending` integration_requests. These routes let a
super admin review, approve, or reject them. Approval publishes the provider
config into the tenant's live profile so checkout and order flows start using
it immediately — no other wiring needed.

All routes require the super_admin role: provider credentials are secrets and
tenant-bound, so sub-admins and tenant tokens do not see them.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from database import (
    get_db,
    list_integration_requests,
    update_integration_request_status,
)
from routes.auth import get_current_admin
from shared.tenancy import integrations as integ

logger = logging.getLogger("routes.integrations")

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _require_super_admin(current_admin: dict = Depends(get_current_admin)) -> dict:
    if current_admin.get("role") != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="Only a super admin can review integration requests",
        )
    return current_admin


class ReviewBody(BaseModel):
    note: Optional[str] = Field(default="")


def _masked_request(req: dict) -> dict:
    out = {
        "id": req.get("id"),
        "tenant_id": req.get("tenant_id"),
        "wa_id": req.get("wa_id"),
        "status": req.get("status"),
        "review_note": req.get("review_note"),
        "reviewed_by": req.get("reviewed_by"),
        "reviewed_at": req.get("reviewed_at"),
        "created_at": req.get("created_at"),
        "delivery_provider": req.get("delivery_provider"),
        "delivery_provider_label": integ.provider_label("delivery", req.get("delivery_provider") or ""),
        "payment_provider": req.get("payment_provider"),
        "payment_provider_label": integ.provider_label("payment", req.get("payment_provider") or ""),
    }
    full = req.get("reviewed_by") is not None and req.get("reviewed_by") != ""
    out["delivery_config"] = (
        req.get("delivery_config") if full else integ.mask_config(req.get("delivery_config") or {})
    )
    out["payment_config"] = (
        req.get("payment_config") if full else integ.mask_config(req.get("payment_config") or {})
    )
    return out


@router.get("/pending")
def list_pending(current_admin: dict = Depends(_require_super_admin)):
    """Requests awaiting review, newest first. Secrets are masked."""
    return {"requests": [_masked_request(r) for r in list_integration_requests(status="pending")]}


@router.get("")
def list_all(status: Optional[str] = None, tenant_id: Optional[str] = None,
             current_admin: dict = Depends(_require_super_admin)):
    """All requests, optionally filtered by status and tenant."""
    return {"requests": [_masked_request(r) for r in
                         list_integration_requests(status=status, tenant_id=tenant_id)]}


@router.get("/providers")
def list_providers(current_admin: dict = Depends(_require_super_admin)):
    """The known-provider registry with the config fields each one needs."""
    return {
        "delivery": [
            {"id": pid, "label": integ.provider_label("delivery", pid),
             "config_fields": integ.config_fields("delivery", pid)}
            for pid in integ.known_providers("delivery")
        ],
        "payment": [
            {"id": pid, "label": integ.provider_label("payment", pid),
             "config_fields": integ.config_fields("payment", pid)}
            for pid in integ.known_providers("payment")
        ],
    }


@router.get("/tenant/{tenant_id}")
def tenant_integrations(tenant_id: str,
                        current_admin: dict = Depends(_require_super_admin)):
    """The live (approved) integrations for one tenant."""
    return {
        "tenant_id": tenant_id,
        "delivery": integ.get_active(tenant_id, "delivery"),
        "payment": integ.get_active(tenant_id, "payment"),
    }


@router.post("/{req_id}/approve")
def approve(req_id: int, current_admin: dict = Depends(_require_super_admin)):
    """Approve a pending request and wire it into the tenant's live profile."""
    from database import get_integration_request
    req = get_integration_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Integration request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {req.get('status')}")

    ok = integ.apply_to_profile(
        req.get("tenant_id"), req, reviewed_by=current_admin.get("username", ""),
    )
    if not ok:
        raise HTTPException(
            status_code=500,
            detail="Could not apply the integration to the tenant profile; see server logs",
        )
    update_integration_request_status(
        req_id, "approved", reviewed_by=current_admin.get("username", ""),
    )
    logger.info("INTEGRATION_APPROVED | req=%s | tenant=%s | by=%s",
                req_id, req.get("tenant_id"), current_admin.get("username"))
    return {"ok": True, "id": req_id, "status": "approved"}


@router.post("/{req_id}/reject")
def reject(req_id: int, body: ReviewBody = None,
           current_admin: dict = Depends(_require_super_admin)):
    """Reject a pending request with an optional note for the record."""
    from database import get_integration_request
    req = get_integration_request(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Integration request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {req.get('status')}")

    note = (body.note if body else None) or ""
    update_integration_request_status(
        req_id, "rejected", reviewed_by=current_admin.get("username", ""), review_note=note,
    )
    logger.info("INTEGRATION_REJECTED | req=%s | tenant=%s | by=%s",
                req_id, req.get("tenant_id"), current_admin.get("username"))
    return {"ok": True, "id": req_id, "status": "rejected", "note": note}
