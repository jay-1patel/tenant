"""Tenant-scoped Customers and Orders APIs for the admin console."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db, get_db_context
from routes.auth import require_tenant_admin_permission
from routes.orders import ALLOWED_PAYMENT_STATUSES, ALLOWED_STATUSES, OrderUpdate


logger = logging.getLogger("tenant_operations")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}", tags=["tenant-operations"])


@router.get("/customers")
def list_tenant_customers(
    tenant_id: str,
    q: str = Query("", max_length=100),
    limit: int = Query(200, le=1000),
    current_admin: dict = Depends(require_tenant_admin_permission("view_customers")),
):
    """Aggregate this tenant's customers without mixing rows for shared WA IDs."""
    conn = get_db()
    try:
        customer_rows = conn.execute(
            """SELECT wa_id FROM (
                   SELECT wa_id FROM orders WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
                   UNION
                   SELECT wa_id FROM complaints WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
                   UNION
                   SELECT wa_id FROM chat_history WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
                   UNION
                   SELECT wa_id FROM user_states WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
               )""",
            (tenant_id, tenant_id, tenant_id, tenant_id),
        ).fetchall()
        wa_ids = [row["wa_id"] for row in customer_rows]
        needle = q.strip().lower()
        customers = []

        for wa_id in wa_ids:
            order_name = conn.execute(
                """SELECT customer_name FROM orders
                   WHERE tenant_id = ? AND wa_id = ? AND customer_name IS NOT NULL AND customer_name != ''
                   ORDER BY id DESC LIMIT 1""",
                (tenant_id, wa_id),
            ).fetchone()
            sender_name = conn.execute(
                """SELECT sender_name FROM chat_history
                   WHERE tenant_id = ? AND wa_id = ? AND sender_name IS NOT NULL AND sender_name != ''
                   ORDER BY id DESC LIMIT 1""",
                (tenant_id, wa_id),
            ).fetchone()
            mobile = conn.execute(
                """SELECT customer_mobile FROM orders
                   WHERE tenant_id = ? AND wa_id = ? AND customer_mobile IS NOT NULL AND customer_mobile != ''
                   ORDER BY id DESC LIMIT 1""",
                (tenant_id, wa_id),
            ).fetchone()
            name = (order_name["customer_name"] if order_name else None) or (sender_name["sender_name"] if sender_name else None) or wa_id
            mobile_value = mobile["customer_mobile"] if mobile else None

            if needle and not any(needle in str(value or "").lower() for value in (wa_id, name, mobile_value)):
                continue

            order_count = conn.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE tenant_id = ? AND wa_id = ?",
                (tenant_id, wa_id),
            ).fetchone()["c"] or 0
            complaint_count = conn.execute(
                "SELECT COUNT(*) AS c FROM complaints WHERE tenant_id = ? AND wa_id = ?",
                (tenant_id, wa_id),
            ).fetchone()["c"] or 0
            open_complaints = conn.execute(
                """SELECT COUNT(*) AS c FROM complaints
                   WHERE tenant_id = ? AND wa_id = ? AND status NOT IN ('resolved','closed')""",
                (tenant_id, wa_id),
            ).fetchone()["c"] or 0
            spent = conn.execute(
                """SELECT COALESCE(SUM(total_amount), 0) AS v FROM orders
                   WHERE tenant_id = ? AND wa_id = ? AND status NOT IN ('cancelled','returned')""",
                (tenant_id, wa_id),
            ).fetchone()["v"] or 0
            last_active = conn.execute(
                """SELECT MAX(last_seen) AS l FROM (
                       SELECT MAX(created_at) AS last_seen FROM chat_history WHERE tenant_id = ? AND wa_id = ?
                       UNION ALL
                       SELECT MAX(created_at) AS last_seen FROM orders WHERE tenant_id = ? AND wa_id = ?
                       UNION ALL
                       SELECT MAX(created_at) AS last_seen FROM complaints WHERE tenant_id = ? AND wa_id = ?
                       UNION ALL
                       SELECT MAX(updated_at) AS last_seen FROM user_states WHERE tenant_id = ? AND wa_id = ?
                   )""",
                (tenant_id, wa_id, tenant_id, wa_id, tenant_id, wa_id, tenant_id, wa_id),
            ).fetchone()["l"]
            customers.append({
                "wa_id": wa_id,
                "name": name,
                "mobile": mobile_value,
                "total_orders": order_count,
                "total_complaints": complaint_count,
                "open_complaints": open_complaints,
                "total_spent": round(float(spent), 2),
                "last_active": last_active,
            })

        customers.sort(key=lambda customer: customer["last_active"] or "", reverse=True)
        customers = customers[:limit]
        return {"customers": customers, "count": len(customers)}
    finally:
        conn.close()


@router.get("/orders")
def list_tenant_orders(
    tenant_id: str,
    status: Optional[str] = Query(None),
    order_type: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    q: str = Query(""),
    limit: int = Query(200, le=500),
    current_admin: dict = Depends(require_tenant_admin_permission("view_orders")),
):
    conn = get_db()
    try:
        clauses = ["tenant_id = ?"]
        params: list = [tenant_id]
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
            clauses.append("(order_number LIKE ? OR wa_id LIKE ? OR customer_name LIKE ? OR customer_mobile LIKE ?)")
            params.extend([like, like, like, like])
        rows = conn.execute(
            f"SELECT * FROM orders WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        orders = [_row_to_dict(conn, row, tenant_id) for row in rows]
        counts = _order_counts(conn, tenant_id)
        return {"orders": orders, "count": len(orders), "counts": counts}
    finally:
        conn.close()


@router.get("/orders/stats")
def tenant_order_stats(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_admin_permission("view_orders")),
):
    conn = get_db()
    try:
        return _order_stats(conn, tenant_id)
    finally:
        conn.close()


@router.get("/orders/{order_id}")
def get_tenant_order(
    tenant_id: str,
    order_id: str,
    current_admin: dict = Depends(require_tenant_admin_permission("view_orders")),
):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE tenant_id = ? AND (id = ? OR order_number = ?)",
            (tenant_id, order_id, order_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"order": _row_to_dict(conn, row, tenant_id)}
    finally:
        conn.close()


@router.put("/orders/{order_id}")
def update_tenant_order(
    tenant_id: str,
    order_id: str,
    body: OrderUpdate,
    current_admin: dict = Depends(require_tenant_admin_permission("manage_orders")),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if body.status is not None and body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(ALLOWED_STATUSES)}")
    if body.payment_status is not None and body.payment_status not in ALLOWED_PAYMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"payment_status must be one of {sorted(ALLOWED_PAYMENT_STATUSES)}")

    fields, values = [], []
    for field, value in payload.items():
        fields.append(f"{field} = ?")
        values.append(value)
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id FROM orders WHERE tenant_id = ? AND (id = ? OR order_number = ?)",
            (tenant_id, order_id, order_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        cursor = conn.execute(
            f"UPDATE orders SET {', '.join(fields)} WHERE id = ? AND tenant_id = ?",
            values + [row["id"], tenant_id],
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "ok", "order_id": order_id, "updated": payload}


@router.delete("/orders/{order_id}")
def delete_tenant_order(
    tenant_id: str,
    order_id: str,
    current_admin: dict = Depends(require_tenant_admin_permission("manage_orders")),
):
    with get_db_context() as conn:
        cursor = conn.execute(
            "DELETE FROM orders WHERE tenant_id = ? AND (id = ? OR order_number = ?)",
            (tenant_id, order_id, order_id),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "ok", "order_id": order_id}


def _order_counts(conn, tenant_id: str) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(CASE WHEN status='placed' THEN 1 ELSE 0 END), 0) AS placed,
                  COALESCE(SUM(CASE WHEN status IN ('delivered','completed') THEN 1 ELSE 0 END), 0) AS delivered,
                  COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END), 0) AS cancelled,
                  COALESCE(SUM(CASE WHEN status NOT IN ('cancelled','returned') THEN total_amount ELSE 0 END), 0) AS revenue
           FROM orders WHERE tenant_id = ?""",
        (tenant_id,),
    ).fetchone()
    return {
        "total": row["total"] or 0,
        "placed": row["placed"] or 0,
        "delivered": row["delivered"] or 0,
        "cancelled": row["cancelled"] or 0,
        "revenue": row["revenue"] or 0,
    }


def _order_stats(conn, tenant_id: str) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS total, COALESCE(SUM(total_amount), 0) AS revenue,
                  SUM(CASE WHEN status='placed' THEN 1 ELSE 0 END) AS placed,
                  SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled,
                  SUM(CASE WHEN status IN ('delivered','completed') THEN 1 ELSE 0 END) AS delivered
           FROM orders WHERE tenant_id = ?""",
        (tenant_id,),
    ).fetchone()
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS c FROM orders WHERE tenant_id = ? GROUP BY status",
        (tenant_id,),
    ).fetchall()
    type_rows = conn.execute(
        "SELECT order_type, COUNT(*) AS c FROM orders WHERE tenant_id = ? GROUP BY order_type",
        (tenant_id,),
    ).fetchall()
    return {
        "total": row["total"] if row else 0,
        "revenue": row["revenue"] if row else 0,
        "placed": row["placed"] if row else 0,
        "cancelled": row["cancelled"] if row else 0,
        "delivered": row["delivered"] if row else 0,
        "by_status": {item["status"]: item["c"] for item in status_rows},
        "by_type": {item["order_type"]: item["c"] for item in type_rows},
    }


def _row_to_dict(conn, row, tenant_id: str) -> dict:
    item = dict(row)
    raw = item.get("items", "[]")
    if isinstance(raw, str):
        try:
            item["items"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            item["items"] = []
    if not item.get("customer_name"):
        name = conn.execute(
            """SELECT sender_name FROM chat_history
               WHERE tenant_id = ? AND wa_id = ?
               ORDER BY id DESC LIMIT 1""",
            (tenant_id, item.get("wa_id")),
        ).fetchone()
        item["customer_name"] = name["sender_name"] if name else None
    return item
