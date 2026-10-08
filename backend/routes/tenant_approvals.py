"""Tenant registration/publish requests and superadmin review.

Admins can view and edit the tenant registration panel and tenant profiles,
but their changes do not go live directly: every registration or publish an
admin (or sub admin) submits lands here as a pending request, and only a super
admin's approval applies it:

    POST /api/tenant-change-requests              -> submit (admin / sub admin)
    GET  /api/tenant-change-requests              -> the requester's own requests
    GET  /api/admin/tenant-change-requests        -> review queue (super admin)
    GET  /api/admin/tenant-change-requests/{id}/events
    POST /api/admin/tenant-change-requests/{id}/decision -> approve / reject

Approving a ``create_tenant`` request registers the tenant, saves the
submitted snapshot as its draft and publishes version 1. Approving a
``publish_profile`` request publishes exactly the snapshot the requester
submitted (captured from the draft at submission time), so the super admin
always approves what was reviewed, not what the draft looks like later.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

<<<<<<< HEAD
from database import get_db, get_db_context
=======
from database import get_db, get_db_context, record_admin_audit_event
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
from routes.auth import get_current_admin, has_permission

logger = logging.getLogger("tenant-approvals")

router = APIRouter(tags=["tenant-approvals"])

RequestType = Literal["create_tenant", "publish_profile"]
RequestStatus = Literal["pending", "approved", "rejected"]


class TenantChangeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    request_type: RequestType
    tenant_id: str = Field(min_length=1, max_length=64)
    tenant: Optional[dict] = None
    snapshot: Optional[dict] = None
    note: str = Field(default="", max_length=2000)

    @field_validator("tenant_id", "note")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=2000)


def _require_super_admin(admin: dict) -> None:
    # Do not use require_permission here: super admins bypass permissions while
    # tenant admins may be granted arbitrary permission switches.
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access is required")


def _require_submitter(admin: dict) -> dict:
    """Only non-super admins with the manage_operations grant may queue changes."""
    if admin.get("role") not in ("admin", "sub_admin"):
        raise HTTPException(
            status_code=403,
            detail="Super admins apply tenant changes directly; this queue is for admins",
        )
    if not has_permission(admin, "manage_operations"):
        raise HTTPException(status_code=403, detail="The manage_operations permission is required")
    return admin


def _request_dict(row) -> dict:
    out = dict(row)
    try:
        out["payload"] = json.loads(out.pop("payload_json") or "{}")
    except (ValueError, TypeError):
        out["payload"] = {}
        out.pop("payload_json", None)
    return out


def _enrich_with_tenant(rows) -> list:
    """Attach the tenant registry record (display name, vertical, bound phone)
    so the review queue can show everything the admin entered — the WhatsApp
    number is bound to the tenants table, not the profile snapshot."""
    if not rows:
        return []
    tenant_ids = {str(r["tenant_id"]) for r in rows}
    with get_db_context() as conn:
        records = {}
        for tid in tenant_ids:
            record = conn.execute(
                "SELECT id, display_name, vertical, waba_phone_id FROM tenants WHERE id = ?",
                (tid,),
            ).fetchone()
            if record:
                records[tid] = dict(record)
    out = []
    for row in rows:
        request = _request_dict(row)
        record = records.get(str(row["tenant_id"]), {})
        request["tenant_display_name"] = record.get("display_name") or row["tenant_id"]
        request["tenant_vertical"] = record.get("vertical") or ""
        request["tenant_waba_phone_id"] = record.get("waba_phone_id") or ""
        out.append(request)
    return out


async def _parse_body(request: Request, model):
    try:
        return model.model_validate(await request.json())
    except ValidationError as exc:
        errors = [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=errors) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc


def _add_event(
    conn,
    request_id: int,
    *,
    actor: dict,
    event_type: str,
    old_status: Optional[str],
    new_status: str,
    note: str = "",
) -> None:
    conn.execute(
        """INSERT INTO tenant_change_request_events
           (request_id, actor_id, actor_username, actor_role, event_type,
            old_status, new_status, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            request_id,
            actor.get("id"),
            actor.get("username", ""),
            actor.get("role", ""),
            event_type,
            old_status,
            new_status,
            note,
        ),
    )


# ── submission ────────────────────────────────────────────────────────────

@router.post("/api/tenant-change-requests", status_code=201)
async def create_change_request(
    request: Request,
    current_admin: dict = Depends(get_current_admin),
):
    body = await _parse_body(request, TenantChangeCreate)
    return _create_change_request(body, current_admin)


def _create_change_request(body: TenantChangeCreate, current_admin: dict):
    _require_submitter(current_admin)
    from shared.tenancy import store as tenancy_store

    tenant_id = body.tenant_id
    payload: dict = {}
    summary = ""

    if body.request_type == "create_tenant":
        if tenancy_store.get_tenant(tenant_id):
            raise HTTPException(status_code=409, detail=f"tenant '{tenant_id}' already exists")

        from shared.tenancy import loader as _loader

        tenant_fields = body.tenant or {}
        try:
            # Fail before queueing the request if the vertical is unknown.
            _loader.build_profile(tenant_id, db_layer={}, file_layer={}, include_db=False)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid vertical: {exc}")

        payload = {
            "tenant": {
                "slug": tenant_fields.get("slug") or tenant_id,
                "vertical": tenant_fields.get("vertical") or "generic",
                "display_name": tenant_fields.get("display_name") or "",
                "waba_phone_id": tenant_fields.get("waba_phone_id") or "",
                "status": tenant_fields.get("status") or "active",
            },
            "snapshot": body.snapshot or {},
        }
        summary = (
            f"Register tenant '{tenant_id}'"
            f" ({payload['tenant']['display_name'] or tenant_id})"
        )
    else:
        tenant = tenancy_store.get_tenant(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="tenant not found")
        # Tenant-scoped admins may only queue publishes for their own tenant.
        admin_tenant = str(current_admin.get("tenant_id") or "").strip()
        if admin_tenant and admin_tenant != tenant_id:
            raise HTTPException(status_code=403, detail=f"Admin is scoped to tenant '{admin_tenant}'")

        draft = tenancy_store.get_draft(tenant_id)
        if not draft:
            raise HTTPException(
                status_code=400,
                detail=f"No draft exists for tenant '{tenant_id}' — save one first",
            )
        # Capture the draft as submitted: approval applies exactly this snapshot.
        payload = {"snapshot": draft}
        summary = f"Publish profile for tenant '{tenant_id}'"

    with get_db_context() as conn:
        duplicate = conn.execute(
            """SELECT id FROM tenant_change_requests
               WHERE request_type = ? AND tenant_id = ? AND status = 'pending'""",
            (body.request_type, tenant_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"A pending {body.request_type} request already exists for tenant '{tenant_id}'",
            )
        try:
            cursor = conn.execute(
                """INSERT INTO tenant_change_requests
                   (request_type, tenant_id, payload_json, summary, status,
                    requester_id, requester_username)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    body.request_type,
                    tenant_id,
                    json.dumps(payload, ensure_ascii=False),
                    summary,
                    current_admin.get("id"),
                    current_admin.get("username", ""),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "tenant_change_requests" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail=f"A pending request already exists for tenant '{tenant_id}'",
                ) from exc
            raise
        request_id = cursor.lastrowid
        _add_event(
            conn,
            request_id,
            actor=current_admin,
            event_type="submitted",
            old_status=None,
            new_status="pending",
            note=body.note,
        )
<<<<<<< HEAD
=======
        record_admin_audit_event(
            conn,
            action="tenant_change_request_submitted",
            actor=current_admin,
            resource_type="tenant_change_request",
            resource_id=request_id,
            tenant_id=tenant_id,
            details={"request_type": body.request_type},
        )
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
        row = conn.execute(
            "SELECT * FROM tenant_change_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
    logger.info(
        "TENANT_CHANGE_SUBMITTED | type=%s | tenant=%s | by=%s",
        body.request_type, tenant_id, current_admin.get("username"),
    )
    return {"request": _enrich_with_tenant([row])[0]}


# ── listing ────────────────────────────────────────────────────────────────

@router.get("/api/tenant-change-requests")
def list_my_requests(current_admin: dict = Depends(get_current_admin)):
    """The signed-in admin's own submissions, newest first."""
    _require_submitter(current_admin)
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM tenant_change_requests
               WHERE requester_id = ? ORDER BY created_at DESC, id DESC""",
            (current_admin.get("id"),),
        ).fetchall()
        return {"requests": _enrich_with_tenant(rows)}
    finally:
        conn.close()


@router.get("/api/admin/tenant-change-requests")
def list_all_requests(
    status: Optional[RequestStatus] = Query(default=None),
    current_admin: dict = Depends(get_current_admin),
):
    _require_super_admin(current_admin)
    conn = get_db()
    try:
        if status:
            rows = conn.execute(
                """SELECT * FROM tenant_change_requests WHERE status = ?
                   ORDER BY created_at DESC, id DESC""",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM tenant_change_requests
                   ORDER BY created_at DESC, id DESC"""
            ).fetchall()
        return {"requests": _enrich_with_tenant(rows)}
    finally:
        conn.close()


@router.get("/api/admin/tenant-change-requests/{request_id}/events")
def list_request_events(
    request_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    _require_super_admin(current_admin)
    conn = get_db()
    try:
        if not conn.execute(
            "SELECT 1 FROM tenant_change_requests WHERE id = ?", (request_id,)
        ).fetchone():
            raise HTTPException(status_code=404, detail="Request not found")
        rows = conn.execute(
            """SELECT id, request_id, actor_id, actor_username, actor_role, event_type,
                      old_status, new_status, note, created_at
               FROM tenant_change_request_events WHERE request_id = ? ORDER BY id""",
            (request_id,),
        ).fetchall()
        return {"events": [dict(row) for row in rows]}
    finally:
        conn.close()


# ── decision ────────────────────────────────────────────────────────────────

def _apply_request(row: dict) -> int:
    """Apply an approved request. Returns the published version number."""
    from shared.tenancy import cache as tenancy_cache
    from shared.tenancy import loader as tenancy_loader
    from shared.tenancy import store as tenancy_store
    from shared.tenancy.merge import merge_drafts

    payload = _request_dict(row)["payload"]
    tenant_id = row["tenant_id"]

    if row["request_type"] == "create_tenant":
        if tenancy_store.get_tenant(tenant_id):
            raise HTTPException(
                status_code=409,
                detail=f"tenant '{tenant_id}' already exists — reject this request",
            )
        tenant_fields = payload.get("tenant") or {}
<<<<<<< HEAD
        tenancy_store.ensure_tenant(
            tenant_id,
            slug=tenant_fields.get("slug") or tenant_id,
            vertical=tenant_fields.get("vertical") or "generic",
            waba_phone_id=tenant_fields.get("waba_phone_id") or "",
            display_name=tenant_fields.get("display_name") or "",
            status=tenant_fields.get("status") or "active",
        )
=======
        with get_db_context() as conn:
            tenancy_store.ensure_tenant(
                tenant_id,
                slug=tenant_fields.get("slug") or tenant_id,
                vertical=tenant_fields.get("vertical") or "generic",
                waba_phone_id=tenant_fields.get("waba_phone_id") or "",
                display_name=tenant_fields.get("display_name") or "",
                status=tenant_fields.get("status") or "active",
                conn=conn,
            )
            record_admin_audit_event(
                conn,
                action="tenant_created",
                actor={"id": row.get("reviewer_id"), "username": row.get("reviewer_username"), "role": "super_admin"},
                resource_type="tenant",
                resource_id=tenant_id,
                tenant_id=tenant_id,
                details={"approved_request": True, "request_type": row["request_type"]},
            )
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
        snapshot = payload.get("snapshot") or {}
    else:
        if not tenancy_store.get_tenant(tenant_id):
            raise HTTPException(status_code=404, detail="tenant not found")
        # Apply exactly what was reviewed: the submitted snapshot over the
        # draft as it stood when the request was queued.
        draft = tenancy_store.get_draft(tenant_id) or {}
        snapshot = merge_drafts(draft, payload.get("snapshot") or {})

    try:
        profile = tenancy_loader.validate_merged_profile(tenant_id, snapshot)
    except tenancy_loader.ProfileValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"The submitted profile failed validation, nothing applied: {exc}",
        )

    tenancy_store.save_draft(tenant_id, snapshot, updated_by=row.get("requester_username", ""))
    by = f"{row.get('requester_username', '')} (approved)"
    version = tenancy_store.publish_version(tenant_id, snapshot, published_by=by)
    tenancy_cache.purge(tenant_id)
    logger.info(
        "TENANT_CHANGE_APPLIED | type=%s | tenant=%s | version=%s",
        row["request_type"], tenant_id, version,
    )
    return version


@router.post("/api/admin/tenant-change-requests/{request_id}/decision")
async def decide_request(
    request_id: int,
    request: Request,
    current_admin: dict = Depends(get_current_admin),
):
    _require_super_admin(current_admin)
    body = await _parse_body(request, DecisionBody)
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM tenant_change_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="Only pending requests can be reviewed")

    if body.decision == "approved":
        record = dict(row)
        version = _apply_request(record)
    else:
        version = None

    decided_at = datetime.now(timezone.utc).isoformat()
    with get_db_context() as conn:
        updated = conn.execute(
            """UPDATE tenant_change_requests
               SET status = ?, reviewer_id = ?, reviewer_username = ?, decision_note = ?,
                   decided_at = ?, applied = ?, applied_version = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'pending'""",
            (
                body.decision,
                current_admin.get("id"),
                current_admin.get("username", ""),
                body.note,
                decided_at,
                1 if body.decision == "approved" else 0,
                version,
                request_id,
            ),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="Request was already reviewed")
        _add_event(
            conn,
            request_id,
            actor=current_admin,
            event_type="decision",
            old_status="pending",
            new_status=body.decision,
            note=body.note,
        )
<<<<<<< HEAD
=======
        record_admin_audit_event(
            conn,
            action="tenant_change_request_reviewed",
            actor=current_admin,
            resource_type="tenant_change_request",
            resource_id=request_id,
            tenant_id=row["tenant_id"],
            details={"decision": body.decision, "request_type": row["request_type"]},
        )
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
        result = conn.execute(
            "SELECT * FROM tenant_change_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
    logger.info(
        "TENANT_CHANGE_DECIDED | id=%s | tenant=%s | decision=%s | by=%s",
        request_id, row["tenant_id"], body.decision, current_admin.get("username"),
    )
    return {
        "request": _enrich_with_tenant([result])[0],
        "message": (
            f"Approved and applied — tenant '{row['tenant_id']}' is live on version {version}."
            if body.decision == "approved"
            else "Request rejected. The requester can submit a corrected one."
        ),
    }
