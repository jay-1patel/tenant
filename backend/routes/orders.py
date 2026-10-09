"""Admin API for orders placed through the WhatsApp bot.

Order rows are created by the B2B (``bots/distributor_b2b``) and B2C
(``bots/customer_b2c``) workflows, as well as the KB bot. Agents use these
endpoints to review, filter, update status, and manage orders from the Admin
Panel.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_db, get_db_context, record_admin_audit_event
from routes.auth import require_permission

logger = logging.getLogger("orders")
router = APIRouter(prefix="/api/orders")

ALLOWED_STATUSES = {
    "placed",
    "confirmed",
    "processing",
    "shipped",
    "delivered",
    "completed",
    "cancelled",
    "returned",
}
ALLOWED_PAYMENT_STATUSES = {"pending", "paid", "failed", "refunded", "cod"}


# ── Models ────────────────────────────────────────────────────────────────

class OrderUpdate(BaseModel):
    status: Optional[str] = None  # placed | confirmed | ... | cancelled | returned
    payment_status: Optional[str] = None  # pending | paid | failed | refunded
    payment_method: Optional[str] = None
    delivery_date: Optional[str] = None
    tier: Optional[str] = None
    discount_applied: Optional[float] = None
    total_amount: Optional[float] = None
    notes: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────

def _row_to_dict(conn, row) -> dict:
    d = dict(row)
    raw = d.get("items", "[]")
    if isinstance(raw, str):
        try:
            d["items"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d["items"] = []
    # Resolve a display name: prefer stored customer_name, otherwise fall
    # back to the latest sender name seen in chat_history for that WA ID.
    if not d.get("customer_name"):
        try:
            name_row = conn.execute(
                "SELECT sender_name FROM chat_history WHERE wa_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (d.get("wa_id"),),
            ).fetchone()
            d["customer_name"] = name_row["sender_name"] if name_row else None
        except Exception:
            d["customer_name"] = None
    return d


# ── List ───────────────────────────────────────────────────────────────────

@router.get("")
def list_orders(
    status: Optional[str] = Query(None),
    order_type: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    q: str = Query(""),
    limit: int = Query(200, le=500),
    current_admin: dict = Depends(require_permission("view_orders")),
):
    """List orders with optional status / type / payment filters and search."""
    conn = get_db()
    try:
        clauses = ["1=1"]
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if order_type:
            clauses.append("order_type = ?")
            params.append(order_type)
        if payment_status:
            clauses.append("payment_status = ?")
            params.append(payment_status)
        if q.strip():
            like = f"%{q.strip()}%"
            clauses.append(
                "(order_number LIKE ? OR wa_id LIKE ? "
                "OR customer_name LIKE ? OR customer_mobile LIKE ?)"
            )
            params.extend([like, like, like, like])
        sql = "SELECT * FROM orders WHERE " + " AND ".join(clauses) + " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        orders = [_row_to_dict(conn, r) for r in rows]

        counts = {
            "total": conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"] or 0,
            "placed": conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='placed'").fetchone()["c"] or 0,
            "delivered": conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status IN ('delivered','completed')").fetchone()["c"] or 0,
            "cancelled": conn.execute("SELECT COUNT(*) AS c FROM orders WHERE status='cancelled'").fetchone()["c"] or 0,
            "revenue": conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) AS v FROM orders "
                "WHERE status NOT IN ('cancelled','returned')"
            ).fetchone()["v"] or 0,
        }
        return {"orders": orders, "count": len(orders), "counts": counts}
    finally:
        conn.close()


# ── Stats ─────────────────────────────────────────────────────────────────

@router.get("/stats")
def order_stats(current_admin: dict = Depends(require_permission("view_orders"))):
    """Aggregate order statistics for the Orders page header and analytics."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(total_amount), 0) AS revenue, "
            "SUM(CASE WHEN status='placed' THEN 1 ELSE 0 END) AS placed, "
            "SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled, "
            "SUM(CASE WHEN status IN ('delivered','completed') THEN 1 ELSE 0 END) AS delivered "
            "FROM orders"
        ).fetchone()
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM orders GROUP BY status"
        ).fetchall()
        type_rows = conn.execute(
            "SELECT order_type, COUNT(*) AS c FROM orders GROUP BY order_type"
        ).fetchall()
        return {
            "total": row["total"] if row else 0,
            "revenue": row["revenue"] if row else 0,
            "placed": row["placed"] if row else 0,
            "cancelled": row["cancelled"] if row else 0,
            "delivered": row["delivered"] if row else 0,
            "by_status": {r["status"]: r["c"] for r in status_rows},
            "by_type": {r["order_type"]: r["c"] for r in type_rows},
        }
    finally:
        conn.close()


# ── Single ─────────────────────────────────────────────────────────────────

@router.get("/{order_id}")
def get_order(
    order_id: str,
    current_admin: dict = Depends(require_permission("view_orders")),
):
    """Fetch one order by its id or order_number."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ? OR order_number = ?",
            (order_id, order_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"order": _row_to_dict(conn, row)}
    finally:
        conn.close()


# ── Update status / payment / details ─────────────────────────────────────

@router.put("/{order_id}")
def update_order(
    order_id: str,
    body: OrderUpdate,
    current_admin: dict = Depends(require_permission("manage_orders")),
):
    """Partially update an order (status, payment_status, delivery date, ...)."""
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nothing to update")

    if body.status is not None and body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(ALLOWED_STATUSES)}")
    if body.payment_status is not None and body.payment_status not in ALLOWED_PAYMENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"payment_status must be one of {sorted(ALLOWED_PAYMENT_STATUSES)}",
        )

    fields = []
    values: list = []
    for field, value in payload.items():
        fields.append(f"{field} = ?")
        values.append(value)
    values.append(order_id)

    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id FROM orders WHERE id = ? OR order_number = ?",
            (order_id, order_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        conn.execute(
            f"UPDATE orders SET {', '.join(fields)} WHERE id = ?",
            values + [row["id"]],
        )
        
        # Record audit event for order update
        record_admin_audit_event(
            conn,
            action="order_updated",
            actor=current_admin,
            resource_type="order",
            resource_id=row["id"],
            details={
                "order_id": order_id,
                "updated_fields": list(payload.keys())
            }
        )

    logger.info(f"ORDER_UPDATED | {order_id} | {payload} | by {current_admin.get('username')}")
    return {"status": "ok", "order_id": order_id, "updated": payload}


# ── Delete ─────────────────────────────────────────────────────────────────

@router.delete("/{order_id}")
def delete_order(
    order_id: str,
    current_admin: dict = Depends(require_permission("manage_orders")),
):
    """Permanently remove an order record."""
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id, order_number FROM orders WHERE id = ? OR order_number = ?",
            (order_id, order_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        conn.execute("DELETE FROM orders WHERE id = ?", (row["id"],))
        
        # Record audit event for order deletion
        record_admin_audit_event(
            conn,
            action="order_deleted",
            actor=current_admin,
            resource_type="order",
            resource_id=row["id"],
            details={
                "order_id": order_id,
                "order_number": row["order_number"] if row["order_number"] else order_id
            }
        )
    logger.info(f"ORDER_DELETED | {order_id} | by {current_admin.get('username')}")
    return {"status": "ok", "order_id": order_id}