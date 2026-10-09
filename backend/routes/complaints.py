"""Admin API for the complaints raised through the WhatsApp bot.

Complaint rows are created by the multi-step form in ``routing.complaint_flow``
(or by the B2B/B2C ticket flows). Agents use these endpoints to review, update,
assign, resolve, and delete complaints.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_db, get_db_context, set_human_handover, record_admin_audit_event
from routes.auth import require_permission

logger = logging.getLogger("complaints")
router = APIRouter(prefix="/api/complaints")

ALLOWED_STATUSES = {"open", "in_progress", "awaiting_info", "resolved", "closed"}


# ── Models ────────────────────────────────────────────────────────────────

class ComplaintUpdate(BaseModel):
    status: Optional[str] = None  # open | in_progress | awaiting_info | resolved | closed
    assigned_to: Optional[str] = None
    priority: Optional[str] = None  # low | normal | high | urgent


class ComplaintReply(BaseModel):
    message: str
    status: Optional[str] = None  # also update complaint status after replying


# ── List ──────────────────────────────────────────────────────────────────

@router.get("")
def list_complaints(
    status: Optional[str] = Query(None),
    wa_id: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
    current_admin: dict = Depends(require_permission("view_complaints")),
):
    conn = get_db()
    try:
        sql = "SELECT * FROM complaints WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if wa_id:
            sql += " AND wa_id = ?"
            params.append(wa_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        complaints = []
        for r in rows:
            item = dict(r)
            try:
                name_row = conn.execute(
                    "SELECT sender_name FROM chat_history WHERE wa_id = ? ORDER BY id DESC LIMIT 1",
                    (item.get("wa_id"),),
                ).fetchone()
                item["name"] = (name_row["sender_name"] if name_row else None) or item.get("wa_id")
            except Exception:
                item["name"] = item.get("wa_id")
            # Latest user reply (excludes admin's "[sent via complaint]" messages)
            try:
                user_row = conn.execute(
                    "SELECT message FROM chat_history "
                    "WHERE wa_id = ? AND (response IS NULL OR response = '') "
                    "ORDER BY id DESC LIMIT 1",
                    (item.get("wa_id"),),
                ).fetchone()
                item["last_user_message"] = (user_row["message"] if user_row else None) or ""
            except Exception:
                item["last_user_message"] = ""
            complaints.append(item)
        open_count = conn.execute("SELECT COUNT(*) AS c FROM complaints WHERE status = 'open'").fetchone()["c"]
        return {"complaints": complaints, "count": len(complaints), "open_count": open_count or 0}
    finally:
        conn.close()


# ── Single ─────────────────────────────────────────────────────────────────

@router.get("/{ticket_id}")
def get_complaint(
    ticket_id: str,
    current_admin: dict = Depends(require_permission("view_complaints")),
):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM complaints WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found")
        return {"complaint": dict(row)}
    finally:
        conn.close()


# ── Update status / assignment / priority ─────────────────────────────────

@router.put("/{ticket_id}")
def update_complaint(
    ticket_id: str,
    body: ComplaintUpdate,
    current_admin: dict = Depends(require_permission("manage_complaints")),
):
    if not any([body.status, body.assigned_to, body.priority]):
        raise HTTPException(status_code=400, detail="Nothing to update")

    allowed_statuses = ALLOWED_STATUSES
    if body.status and body.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed_statuses)}")

    now = datetime.utcnow().isoformat()
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id, status FROM complaints WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found")

        updates = []
        params: list = []
        if body.status:
            updates.append("status = ?")
            params.append(body.status)
            if body.status in ("resolved", "closed"):
                updates.append("resolved_at = ?")
                params.append(now)
        if body.assigned_to is not None:
            updates.append("assigned_to = ?")
            params.append(body.assigned_to)
        if body.priority:
            updates.append("priority = ?")
            params.append(body.priority)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(ticket_id)

        conn.execute(f"UPDATE complaints SET {', '.join(updates)} WHERE ticket_id = ?", params)
        
        # Record audit event for complaint update
        changed_fields = []
        if body.status:
            changed_fields.append(f"status:{body.status}")
        if body.assigned_to is not None:
            changed_fields.append(f"assigned_to:{body.assigned_to}")
        if body.priority:
            changed_fields.append(f"priority:{body.priority}")
            
        record_admin_audit_event(
            conn,
            action="complaint_updated",
            actor=current_admin,
            resource_type="complaint",
            resource_id=row["id"],
            details={
                "ticket_id": ticket_id,
                "changed_fields": changed_fields
            }
        )

    return {"status": "ok", "ticket_id": ticket_id, "updated": {k: v for k, v in body.dict().items() if v is not None}}


# ── Convenience: resolve ──────────────────────────────────────────────────

@router.post("/{ticket_id}/resolve")
def resolve_complaint(
    ticket_id: str,
    current_admin: dict = Depends(require_permission("manage_complaints")),
):
    now = datetime.utcnow().isoformat()
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id FROM complaints WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found")
        conn.execute(
            "UPDATE complaints SET status='resolved', resolved_at=?, updated_at=? WHERE ticket_id=?",
            (now, now, ticket_id),
        )
        
        # Record audit event for complaint resolution
        record_admin_audit_event(
            conn,
            action="complaint_resolved",
            actor=current_admin,
            resource_type="complaint",
            resource_id=row["id"],
            details={
                "ticket_id": ticket_id,
                "resolved_at": now
            }
        )
    return {"status": "ok", "ticket_id": ticket_id, "resolved": True}


# ── Reply to the customer on WhatsApp ─────────────────────────────────────

@router.post("/{ticket_id}/reply")
def reply_complaint(
    ticket_id: str,
    body: ComplaintReply,
    current_admin: dict = Depends(require_permission("manage_complaints")),
):
    """Send a WhatsApp message back to the customer who raised the complaint.

    Optionally pushes the complaint to a new status (resolved / awaiting_info /
    in_progress) at the same time. The message is also written to chat_history
    so it shows up in the agent inbox.
    """
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    if body.status and body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(ALLOWED_STATUSES)}")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT ticket_id, wa_id, subject FROM complaints WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Complaint not found")
    wa_id = row["wa_id"]
    if not wa_id:
        raise HTTPException(status_code=400, detail="Complaint has no customer WA ID to reply to")

    # ── Send the WhatsApp message ──
    try:
        from routing.whatsapp import send_whatsapp_message
        sent = send_whatsapp_message(wa_id, message)
    except Exception as e:
        logger.error(f"reply_complaint send failed: {e}")
        sent = False
    if not sent:
        raise HTTPException(status_code=502, detail="WhatsApp message could not be sent")

    # ── Persist to chat history (shows in agent inbox) ──
    try:
        from database import save_chat
        save_chat(wa_id, current_admin.get("username", "agent"), message, response="[sent via complaint]", route="complaint")
    except Exception as e:
        logger.warning(f"reply_complaint: could not save chat history: {e}")

    # ── Update complaint status if requested ──
    if body.status:
        now = datetime.utcnow().isoformat()
        with get_db_context() as conn:
            updates = ["status = ?", "updated_at = ?"]
            params = [body.status, now]
            if body.status in ("resolved", "closed"):
                updates.append("resolved_at = ?")
                params.append(now)
            params.append(ticket_id)
            conn.execute(f"UPDATE complaints SET {', '.join(updates)} WHERE ticket_id = ?", params)

    # ── Keep the Live Inbox conversation visible ──
    # Engaging the customer (awaiting info / in progress) brings the
    # conversation back into the human inbox queue (clears handover_resolved_at)
    # so the customer's follow-up messages are visible to the agent. Resolving
    # the complaint hands control back to the chatbot.
    if body.status in ("awaiting_info", "in_progress"):
        set_human_handover(wa_id, True)
        logger.info(f"COMPLAINT_HANDOVER_ON | {ticket_id} | {wa_id} | conversation visible in inbox")
    elif body.status in ("resolved", "closed"):
        set_human_handover(wa_id, False)
        logger.info(f"COMPLAINT_HANDOVER_OFF | {ticket_id} | {wa_id} | bot resumed")

    logger.info(f"COMPLAINT_REPLIED | {ticket_id} | to={wa_id} | status={body.status or 'unchanged'} | by={current_admin.get('username')}")
    return {"status": "ok", "ticket_id": ticket_id, "wa_id": wa_id, "sent": sent, "new_status": body.status}


# ── Delete ─────────────────────────────────────────────────────────────────

@router.delete("/{ticket_id}")
def delete_complaint(
    ticket_id: str,
    current_admin: dict = Depends(require_permission("manage_complaints")),
):
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id, wa_id, complaint_type, description FROM complaints WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found")
        conn.execute("DELETE FROM complaints WHERE ticket_id = ?", (ticket_id,))
        
        # Record audit event for complaint deletion
        record_admin_audit_event(
            conn,
            action="complaint_deleted",
            actor=current_admin,
            resource_type="complaint",
            resource_id=row["id"],
            details={
                "ticket_id": ticket_id,
                "wa_id": row["wa_id"],
                "complaint_type": row["complaint_type"],
                "description": row["description"]
            }
        )
    logger.info(f"COMPLAINT_DELETED | {ticket_id} | by {current_admin.get('username')}")
    return {"status": "ok", "ticket_id": ticket_id}