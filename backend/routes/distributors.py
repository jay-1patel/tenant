import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db_context, record_admin_audit_event
from routes.auth import require_permission, require_tenant_access
from shared.tenancy.schemas import is_valid_email, is_valid_phone

logger = logging.getLogger("distributors")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}/distributors", tags=["distributors"])


# ── Pydantic models ────────────────────────────────────────────────────

class DistributorCreate(BaseModel):
    wa_id: str
    name: str = ""
    phone: str = ""
    email: str = ""
    region: str = ""
    city: str = ""
    address: str = ""
    service_area: str = ""
    tier: str = "Bronze"
    product_interests: list[str] = []
    sales_volume: float = 0
    last_order_value: float = 0
    outstanding_payments: float = 0
    notes: str = ""


class DistributorUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    region: str | None = None
    city: str | None = None
    address: str | None = None
    service_area: str | None = None
    tier: str | None = None
    product_interests: list[str] | None = None
    sales_volume: float | None = None
    last_order_value: float | None = None
    outstanding_payments: float | None = None
    notes: str | None = None


# ── Helpers ─────────────────────────────────────────────────────────────

def _contact_errors(name=None, phone=None, email=None, wa_id=None):
    """Collect the compulsory / format problems with one submission.

    None means "not part of this submission" (partial updates only validate
    the fields they actually carry).
    """
    errors = []
    if name is not None and not str(name).strip():
        errors.append("name is required")
    if phone is not None:
        if not str(phone).strip():
            errors.append("phone is required")
        elif not is_valid_phone(phone):
            errors.append(
                "phone must be a country code followed by a 10-digit number, "
                "e.g. +91 98765 43210"
            )
    if email is not None:
        if not str(email).strip():
            errors.append("email is required")
        elif not is_valid_email(email):
            errors.append("email must be a valid address, e.g. name@company.com")
    if wa_id is not None and not re.fullmatch(r"\d{15}", wa_id):
        errors.append("the WhatsApp phone number id must be exactly 15 digits")
    return errors


def _row_to_dict(row) -> dict:
    d = dict(row)
    raw = d.get("product_interests", "[]")
    if isinstance(raw, str):
        try:
            d["product_interests"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d["product_interests"] = []
    return d


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("")
def list_distributors(
    tenant_id: str,
    q: str = "",
    region: str = "",
    tier: str = "",
    current_admin: dict = Depends(require_tenant_access),
):
    """List this tenant's distributors, with optional search / filter."""
    with get_db_context() as conn:
        clauses, params = ["tenant_id = ?"], [tenant_id]

        if q:
            clauses.append(
                "(wa_id LIKE ? OR name LIKE ? OR phone LIKE ? OR email LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like])

        if region:
            clauses.append("region = ?")
            params.append(region)

        if tier:
            clauses.append("tier = ?")
            params.append(tier)

        rows = conn.execute(
            f"SELECT * FROM distributors WHERE {' AND '.join(clauses)} "
            "ORDER BY name COLLATE NOCASE ASC",
            params,
        ).fetchall()

    return {"distributors": [_row_to_dict(r) for r in rows]}


@router.get("/count")
def distributor_count(
    tenant_id: str,
    region: str = "",
    tier: str = "",
    product_interest: str = "",
    current_admin: dict = Depends(require_tenant_access),
):
    """Count this tenant's distributors matching optional segment filters.
    Used by Campaign Builder for the live 'target N distributors' preview.
    """
    with get_db_context() as conn:
        clauses, params = ["tenant_id = ?"], [tenant_id]

        if region:
            clauses.append("region = ?")
            params.append(region)

        if tier:
            clauses.append("tier = ?")
            params.append(tier)

        if product_interest:
            clauses.append("product_interests LIKE ?")
            params.append(f"%{product_interest}%")

        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM distributors WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()

    return {"count": row["cnt"] if row else 0}


@router.get("/lookup/{wa_id}")
def lookup_distributor(
    tenant_id: str,
    wa_id: str,
    current_admin: dict = Depends(require_tenant_access),
):
    """Fetch one of this tenant's distributors by WhatsApp ID."""
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM distributors WHERE wa_id = ? AND tenant_id = ?",
            (wa_id, tenant_id),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Distributor '{wa_id}' not found")

    return _row_to_dict(row)


@router.post("")
def create_distributor(
    tenant_id: str,
    body: DistributorCreate,
    current_admin: dict = Depends(require_permission("manage_distributors")),
):
    """Add a new distributor to this tenant."""
    wa_id = body.wa_id.strip()

    if not wa_id:
        raise HTTPException(400, "wa_id is required")

    errors = _contact_errors(name=body.name, phone=body.phone, email=body.email, wa_id=wa_id)
    if errors:
        raise HTTPException(422, "; ".join(errors))

    with get_db_context() as conn:
        existing = conn.execute(
            "SELECT 1 FROM distributors WHERE wa_id = ?", (wa_id,)
        ).fetchone()

        if existing:
            raise HTTPException(409, f"Distributor with wa_id '{wa_id}' already exists")

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """INSERT INTO distributors
                (wa_id, tenant_id, name, phone, email, region, city, address, service_area,
                 tier, product_interests, sales_volume, last_order_value, outstanding_payments,
                 notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                wa_id,
                tenant_id,
                body.name,
                body.phone,
                body.email,
                body.region,
                body.city,
                body.address,
                body.service_area,
                body.tier,
                json.dumps(body.product_interests),
                body.sales_volume,
                body.last_order_value,
                body.outstanding_payments,
                body.notes,
                now,
                now,
            ),
        )
        record_admin_audit_event(
            conn,
            action="distributor_created",
            actor=current_admin,
            resource_type="distributor",
            resource_id=wa_id,
            tenant_id=tenant_id,
            details={
                "wa_id": wa_id,
                "name": str(body.name)[:100],
                "phone": str(body.phone)[:30],
                "region": str(body.region)[:50],
                "tier": str(body.tier)[:30],
            },
        )

    logger.info(f"DISTRIBUTOR_CREATED | tenant={tenant_id} | wa_id={wa_id} | name={body.name}")
    return {"ok": True, "wa_id": wa_id}


@router.put("/{wa_id}")
def update_distributor(
    tenant_id: str,
    wa_id: str,
    body: DistributorUpdate,
    current_admin: dict = Depends(require_permission("manage_distributors")),
):
    """Update one of this tenant's distributors (partial update — only sent fields)."""
    updates = body.model_dump(exclude_unset=True)

    errors = _contact_errors(
        name=updates.get("name"),
        phone=updates.get("phone"),
        email=updates.get("email"),
    )
    if errors:
        raise HTTPException(422, "; ".join(errors))

    fields, values = [], []

    for field, value in updates.items():
        if field == "product_interests":
            value = json.dumps(value)
        fields.append(f"{field} = ?")
        values.append(value)

    if not fields:
        raise HTTPException(400, "Nothing to update")

    fields.append("updated_at = ?")
    values.append(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    values.extend([wa_id, tenant_id])

    with get_db_context() as conn:
        before = conn.execute(
            "SELECT name, phone, email, region, tier FROM distributors WHERE wa_id = ? AND tenant_id = ?",
            (wa_id, tenant_id),
        ).fetchone()

        result = conn.execute(
            f"UPDATE distributors SET {', '.join(fields)} WHERE wa_id = ? AND tenant_id = ?",
            values,
        )

        if result.rowcount == 0:
            raise HTTPException(404, f"Distributor '{wa_id}' not found")

        changes = {}
        if before:
            for k in ("name", "phone", "email", "region", "tier"):
                if k in updates and updates[k] is not None and before[k] != updates[k]:
                    changes[k] = {"before": before[k], "after": updates[k]}

        record_admin_audit_event(
            conn,
            action="distributor_updated",
            actor=current_admin,
            resource_type="distributor",
            resource_id=wa_id,
            tenant_id=tenant_id,
            details={
                "wa_id": wa_id,
                "changed_fields": sorted(updates.keys()),
                "changes": changes,
            },
        )

    logger.info(f"DISTRIBUTOR_UPDATED | tenant={tenant_id} | wa_id={wa_id}")
    return {"ok": True}


@router.delete("/{wa_id}")
def delete_distributor(
    tenant_id: str,
    wa_id: str,
    current_admin: dict = Depends(require_permission("manage_distributors")),
):
    """Delete one of this tenant's distributors."""
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT name, phone, region FROM distributors WHERE wa_id = ? AND tenant_id = ?",
            (wa_id, tenant_id),
        ).fetchone()

        result = conn.execute(
            "DELETE FROM distributors WHERE wa_id = ? AND tenant_id = ?",
            (wa_id, tenant_id),
        )

        if result.rowcount == 0:
            raise HTTPException(404, f"Distributor '{wa_id}' not found")

        record_admin_audit_event(
            conn,
            action="distributor_deleted",
            actor=current_admin,
            resource_type="distributor",
            resource_id=wa_id,
            tenant_id=tenant_id,
            details={
                "wa_id": wa_id,
                "name": (row["name"] if row else "")[:100],
                "phone": (row["phone"] if row else "")[:30],
            },
        )

    logger.info(f"DISTRIBUTOR_DELETED | tenant={tenant_id} | wa_id={wa_id}")
    return {"ok": True}
