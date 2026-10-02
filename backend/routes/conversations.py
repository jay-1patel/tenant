"""Tenant-scoped conversations: chat history, live inbox and complaints.

The legacy routes under ``/api/admin`` and ``/api/complaints`` are single-tenant
and global. This router is the tenant-owned path the console uses, so a tenant
console sees only its own customers:

    GET    /api/admin/tenants/{tenant_id}/conversations
    GET    /api/admin/tenants/{tenant_id}/conversations/{wa_id}
    GET    /api/admin/tenants/{tenant_id}/chat-history
    GET    /api/admin/tenants/{tenant_id}/inbox
    PUT    /api/admin/tenants/{tenant_id}/inbox/handover/{wa_id}
    POST   /api/admin/tenants/{tenant_id}/inbox/assign
    POST   /api/admin/tenants/{tenant_id}/inbox/resolve/{wa_id}
    GET    /api/admin/tenants/{tenant_id}/agents
    GET    /api/admin/tenants/{tenant_id}/complaints
    PUT    /api/admin/tenants/{tenant_id}/complaints/{ticket_id}
    POST   /api/admin/tenants/{tenant_id}/complaints/{ticket_id}/reply

`chat_history` is stamped with `tenant_id` by the live webhook, which resolves
the owner from the inbound WABA phone-id (`shared.tenancy.resolver`). Rows
written before that column existed fall back to the tenant on their state row
(`user_states.tenant_id`). Complaints carry tenant_id directly.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from database import get_db, get_db_context, set_human_handover
from routes.auth import get_current_admin, has_permission, require_tenant_access, security

logger = logging.getLogger("conversations")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}", tags=["conversations"])

ALLOWED_STATUSES = {"open", "in_progress", "awaiting_info", "resolved", "closed"}
ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}


# ── auth ──────────────────────────────────────────────────────────────────

def _require(perm: str):
    def dependency(
        request: Request,
        tenant_id: str,
        principal: dict = Depends(require_tenant_access()),
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        if principal.get("type") == "tenant":
            return principal
        if not has_permission(get_current_admin(request, credentials), perm):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action",
            )
        return principal
    return dependency


#: A conversation belongs to a tenant when the row is stamped with it, or - for
#: rows written before `chat_history` carried a tenant - when its state row does.
#: Two placeholders: the tenant id, twice.
_TENANT_SCOPE = (
    "(ch.tenant_id = ? OR (ch.tenant_id IS NULL AND ch.wa_id IN "
    "(SELECT wa_id FROM user_states WHERE tenant_id = ?)))"
)


# ── conversation threads ──────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(
    tenant_id: str,
    limit: int = Query(100, le=500),
    search: Optional[str] = Query(None),
    principal: dict = Depends(_require("chat_history")),
):
    """One row per customer: who they are, the last line, and the counts."""
    conn = get_db()
    try:
        sql = f"""
            SELECT
                ch.wa_id,
                MAX(ch.created_at) AS last_message_at,
                COUNT(*) AS turns,
                SUM(CASE WHEN ch.response IS NULL OR ch.response = '' THEN 1 ELSE 0 END) AS inbound
            FROM chat_history ch
            WHERE {_TENANT_SCOPE}
        """
        params: list = [tenant_id, tenant_id]
        if search:
            sql += " AND (ch.wa_id LIKE ? OR ch.sender_name LIKE ? OR ch.message LIKE ?)"
            params.extend([f"%{search}%"] * 3)
        sql += " GROUP BY ch.wa_id ORDER BY last_message_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()

        threads = []
        for row in rows:
            wa_id = row["wa_id"]
            last = conn.execute(
                "SELECT message, response, sender_name FROM chat_history "
                "WHERE wa_id = ? ORDER BY id DESC LIMIT 1",
                (wa_id,),
            ).fetchone()
            state = conn.execute(
                "SELECT human_handover, state, handover_resolved_at FROM user_states WHERE tenant_id = ? AND wa_id = ?",
                (tenant_id, wa_id),
            ).fetchone()
            handover = bool(state["human_handover"]) if state else False
            threads.append({
                "wa_id": wa_id,
                "name": (last["sender_name"] if last else None) or wa_id,
                "last_message": (last["message"] if last else "") or "",
                "last_at": row["last_message_at"],
                "turns": row["turns"],
                "inbound": row["inbound"] or 0,
                "handover": handover,
                "bot_state": state["state"] if state else None,
            })
        return {"conversations": threads, "count": len(threads)}
    finally:
        conn.close()


@router.get("/conversations/{wa_id}")
def get_conversation(
    tenant_id: str,
    wa_id: str,
    limit: int = Query(300, le=1000),
    principal: dict = Depends(_require("chat_history")),
):
    conn = get_db()
    try:
        owns = conn.execute(
            f"SELECT 1 FROM chat_history ch WHERE {_TENANT_SCOPE} AND ch.wa_id = ? LIMIT 1",
            (tenant_id, tenant_id, wa_id),
        ).fetchone()
        if not owns:
            raise HTTPException(status_code=404, detail="This conversation does not belong to this tenant")

        rows = conn.execute(
            "SELECT * FROM chat_history WHERE wa_id = ? ORDER BY id ASC LIMIT ?",
            (wa_id, limit),
        ).fetchall()
        messages = []
        for r in rows:
            item = dict(r)
            # Rows are stored as "[route] user message" + the bot's response.
            raw = item.get("message") or ""
            item["user_message"] = raw.split("] ", 1)[1] if raw.startswith("[") and "] " in raw else raw
            messages.append(item)
        return {"wa_id": wa_id, "messages": messages}
    finally:
        conn.close()


@router.get("/chat-history")
def chat_history(
    tenant_id: str,
    days: int = Query(30, ge=1, le=1095),
    search: Optional[str] = Query(None),
    wa_id: Optional[str] = Query(None),
    limit: int = Query(500, le=2000),
    principal: dict = Depends(_require("chat_history")),
):
    conn = get_db()
    try:
        sql = f"""
            SELECT ch.*, (SELECT sender_name FROM chat_history n WHERE n.wa_id = ch.wa_id
                          ORDER BY n.id DESC LIMIT 1) AS sender_name
            FROM chat_history ch
            WHERE {_TENANT_SCOPE}
              AND ch.created_at >= DATE('now', ?)
        """
        params: list = [tenant_id, tenant_id, f"-{days} days"]
        if wa_id:
            sql += " AND ch.wa_id = ?"
            params.append(wa_id)
        if search:
            sql += " AND (ch.wa_id LIKE ? OR ch.message LIKE ? OR ch.response LIKE ?)"
            params.extend([f"%{search}%"] * 3)
        sql += " ORDER BY ch.created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return {"history": [dict(r) for r in rows]}
    finally:
        conn.close()


# ── live inbox (human handover) ───────────────────────────────────────────

@router.get("/inbox")
def inbox_queue(
    tenant_id: str,
    include_resolved: bool = False,
    principal: dict = Depends(_require("view_inbox")),
):
    conn = get_db()
    try:
        where = "" if include_resolved else "AND us.handover_resolved_at IS NULL"
        rows = conn.execute(
            f"""
            SELECT
                ch.wa_id,
                MAX(ch.created_at) AS last_message_at,
                (SELECT message FROM chat_history c2 WHERE c2.wa_id = ch.wa_id
                 ORDER BY c2.id DESC LIMIT 1) AS last_message,
                (SELECT COUNT(*) FROM chat_history c3 WHERE c3.wa_id = ch.wa_id) AS turn_count,
                us.state AS bot_state,
                COALESCE(us.human_handover, 0) AS human_handover
            FROM chat_history ch
            LEFT JOIN user_states us ON us.wa_id = ch.wa_id AND us.tenant_id = ?
            WHERE {_TENANT_SCOPE} {where}
            GROUP BY ch.wa_id
            ORDER BY human_handover DESC, last_message_at DESC
            """,
            (tenant_id, tenant_id, tenant_id),
        ).fetchall()

        queue = []
        for row in rows:
            assignment = conn.execute(
                "SELECT agent_id FROM conversation_assignments WHERE wa_id = ?",
                (row["wa_id"],),
            ).fetchone()
            queue.append({
                "wa_id": row["wa_id"],
                "name": row["wa_id"],
                "last_message": row["last_message"] or "",
                "last_message_at": row["last_message_at"],
                "turns": row["turn_count"] or 0,
                "bot_state": row["bot_state"],
                "handover_mode": "human" if row["human_handover"] else "bot",
                "assigned_agent_id": assignment["agent_id"] if assignment else None,
            })
        handoff = sum(1 for c in queue if c["handover_mode"] == "human")
        return {"queue": queue, "count": len(queue), "handoff_count": handoff}
    finally:
        conn.close()


class HandoverBody(BaseModel):
    mode: str  # "bot" | "human"


class AssignBody(BaseModel):
    wa_id: str
    agent_id: str


@router.put("/inbox/handover/{wa_id}")
def set_handover(
    tenant_id: str,
    wa_id: str,
    body: HandoverBody,
    principal: dict = Depends(_require("view_inbox")),
):
    if body.mode not in ("bot", "human"):
        raise HTTPException(status_code=400, detail="mode must be 'bot' or 'human'")
    set_human_handover(wa_id, active=(body.mode == "human"), tenant_id=tenant_id)
    logger.info(f"INBOX_HANDOVER | tenant={tenant_id} | wa={wa_id} | mode={body.mode}")
    return {"status": "ok", "wa_id": wa_id, "mode": body.mode}


@router.post("/inbox/assign")
def assign_conversation(
    tenant_id: str,
    body: AssignBody,
    principal: dict = Depends(_require("view_inbox")),
):
    with get_db_context() as conn:
        conn.execute(
            """INSERT INTO conversation_assignments (wa_id, agent_id, assigned_at)
               VALUES (?, ?, ?)
               ON CONFLICT(wa_id) DO UPDATE SET
                 agent_id = excluded.agent_id, assigned_at = excluded.assigned_at""",
            (body.wa_id, body.agent_id, datetime.utcnow().isoformat()),
        )
    return {"status": "ok", "wa_id": body.wa_id, "agent_id": body.agent_id}


RESOLVED_MESSAGE = (
    "Thank you for your patience! Your query has been resolved. "
    "The chatbot is now available if you need anything else. 🙏"
)


@router.post("/inbox/resolve/{wa_id}")
def resolve_handoff(
    tenant_id: str,
    wa_id: str,
    reply: bool = True,
    principal: dict = Depends(_require("view_inbox")),
):
    set_human_handover(wa_id, active=False, tenant_id=tenant_id)
    sent = False
    if reply:
        try:
            from routing.config import SEND2_USERNAME, SEND2_PASSWORD
            if SEND2_USERNAME and SEND2_PASSWORD:
                from routing.whatsapp import send_whatsapp_message
                sent = bool(send_whatsapp_message(wa_id, RESOLVED_MESSAGE))
        except Exception as exc:  # pragma: no cover - depends on live credentials
            logger.warning(f"Could not send resolve message to {wa_id}: {exc}")
    logger.info(f"INBOX_RESOLVED | tenant={tenant_id} | wa={wa_id} | notified={sent}")
    return {"status": "ok", "wa_id": wa_id, "notified": sent, "message": RESOLVED_MESSAGE}


class InboxReply(BaseModel):
    message: str = ""
    attachment: Optional[dict] = None


@router.post("/inbox/{wa_id}/reply")
def reply_to_customer(
    tenant_id: str,
    wa_id: str,
    body: InboxReply,
    principal: dict = Depends(_require("view_inbox")),
):
    """Send an agent's message to the customer and keep the bot out of the way."""
    message = (body.message or "").strip()
    attach = body.attachment or None
    if attach and attach.get("url"):
        # WhatsApp media sending is disabled project-wide, so an attachment is
        # shared as its hosted URL in the message body.
        name = attach.get("name") or "attachment"
        line = f"\U0001F4CE {name}: {attach['url']}"
        message = f"{message}\n{line}" if message else line
    if not message:
        raise HTTPException(status_code=400, detail="message or attachment is required")

    conn = get_db()
    try:
        owns = conn.execute(
            f"SELECT 1 FROM chat_history ch WHERE {_TENANT_SCOPE} AND ch.wa_id = ? LIMIT 1",
            (tenant_id, tenant_id, wa_id),
        ).fetchone()
    finally:
        conn.close()
    if not owns:
        raise HTTPException(status_code=404, detail="This conversation does not belong to this tenant")

    try:
        from routing.whatsapp import send_whatsapp_message
        sent = bool(send_whatsapp_message(wa_id, message))
    except Exception as exc:
        logger.error(f"inbox reply send failed: {exc}")
        sent = False
    if not sent:
        raise HTTPException(status_code=502, detail="WhatsApp message could not be sent")

    try:
        from database import save_chat
        save_chat(
            wa_id,
            principal.get("username", "agent"),
            message,
            response="[sent by agent]",
            route="agent",
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(f"inbox reply: could not save chat history: {exc}")

    set_human_handover(wa_id, active=True, tenant_id=tenant_id)
    logger.info(f"INBOX_REPLIED | tenant={tenant_id} | wa={wa_id} | by={principal.get('username')}")
    return {"status": "ok", "wa_id": wa_id, "sent": sent}


@router.post("/inbox/attach")
async def attach_inbox_file(
    tenant_id: str,
    data: dict,
    principal: dict = Depends(_require("view_inbox")),
):
    """Host a file so an agent can share it with a customer.

    WhatsApp media sending is disabled project-wide, so the descriptor's URL is
    included in the reply text rather than sent as native media.
    """
    from routes.admin import decode_attachment_body, store_chat_attachment

    filename, content, media_type = decode_attachment_body(data)
    return await store_chat_attachment(filename, content, media_type)


@router.get("/agents")
def list_agents(tenant_id: str, principal: dict = Depends(_require("view_inbox"))):
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT a.username AS agent_id, a.username,
                   COALESCE(ao.status, 'offline') AS status
            FROM admins a
            LEFT JOIN agent_status ao ON ao.agent_id = a.username
            ORDER BY a.username
            """
        ).fetchall()
        return {"agents": [dict(r) for r in rows]}
    finally:
        conn.close()


# ── complaints ────────────────────────────────────────────────────────────

@router.get("/complaints")
def list_complaints(
    tenant_id: str,
    status: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
    principal: dict = Depends(_require("view_complaints")),
):
    conn = get_db()
    try:
        sql = "SELECT * FROM complaints WHERE tenant_id = ?"
        params: list = [tenant_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()

        complaints = []
        for r in rows:
            item = dict(r)
            item["name"] = item.get("wa_id") or "unknown"
            user_row = conn.execute(
                "SELECT message FROM chat_history WHERE wa_id = ? "
                "AND (response IS NULL OR response = '') ORDER BY id DESC LIMIT 1",
                (item.get("wa_id"),),
            ).fetchone()
            item["last_user_message"] = (user_row["message"] if user_row else "") or ""
            complaints.append(item)
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM complaints WHERE tenant_id = ? AND status = 'open'",
            (tenant_id,),
        ).fetchone()["c"]
        return {"complaints": complaints, "count": len(complaints), "open_count": open_count or 0}
    finally:
        conn.close()


class ComplaintPatch(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None


@router.put("/complaints/{ticket_id}")
def update_complaint(
    tenant_id: str,
    ticket_id: str,
    body: ComplaintPatch,
    principal: dict = Depends(_require("manage_complaints")),
):
    if not any([body.status, body.priority, body.assigned_to is not None]):
        raise HTTPException(status_code=400, detail="Nothing to update")
    if body.status and body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(ALLOWED_STATUSES)}")
    if body.priority and body.priority not in ALLOWED_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"priority must be one of {sorted(ALLOWED_PRIORITIES)}")

    now = datetime.utcnow().isoformat()
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id FROM complaints WHERE ticket_id = ? AND tenant_id = ?",
            (ticket_id, tenant_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found for this tenant")

        updates, params = [], []
        if body.status:
            updates.append("status = ?")
            params.append(body.status)
            if body.status in ("resolved", "closed"):
                updates.append("resolved_at = ?")
                params.append(now)
        if body.priority:
            updates.append("priority = ?")
            params.append(body.priority)
        if body.assigned_to is not None:
            updates.append("assigned_to = ?")
            params.append(body.assigned_to)
        updates.append("updated_at = ?")
        params.append(now)
        params.extend([ticket_id, tenant_id])
        conn.execute(
            f"UPDATE complaints SET {', '.join(updates)} WHERE ticket_id = ? AND tenant_id = ?", params
        )
    return {"status": "ok", "ticket_id": ticket_id}


class ComplaintReply(BaseModel):
    message: str
    status: Optional[str] = None


@router.post("/complaints/{ticket_id}/reply")
def reply_complaint(
    tenant_id: str,
    ticket_id: str,
    body: ComplaintReply,
    principal: dict = Depends(_require("manage_complaints")),
):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    if body.status and body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(ALLOWED_STATUSES)}")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT wa_id FROM complaints WHERE ticket_id = ? AND tenant_id = ?",
            (ticket_id, tenant_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Complaint not found for this tenant")
    wa_id = row["wa_id"]
    if not wa_id:
        raise HTTPException(status_code=400, detail="Complaint has no customer to reply to")

    try:
        from routing.whatsapp import send_whatsapp_message
        sent = bool(send_whatsapp_message(wa_id, message))
    except Exception as exc:
        logger.error(f"reply_complaint send failed: {exc}")
        sent = False
    if not sent:
        raise HTTPException(status_code=502, detail="WhatsApp message could not be sent")

    try:
        from database import save_chat
        save_chat(wa_id, principal.get("username", "agent"), message,
                  response="[sent via complaint]", route="complaint")
    except Exception as exc:
        logger.warning(f"reply_complaint: could not save chat history: {exc}")

    if body.status:
        now = datetime.utcnow().isoformat()
        with get_db_context() as conn:
            updates = ["status = ?", "updated_at = ?"]
            params = [body.status, now]
            if body.status in ("resolved", "closed"):
                updates.append("resolved_at = ?")
                params.append(now)
            params.extend([ticket_id, tenant_id])
            conn.execute(
                f"UPDATE complaints SET {', '.join(updates)} WHERE ticket_id = ? AND tenant_id = ?",
                params,
            )

    if body.status in ("awaiting_info", "in_progress"):
        set_human_handover(wa_id, True, tenant_id=tenant_id)
    elif body.status in ("resolved", "closed"):
        set_human_handover(wa_id, False, tenant_id=tenant_id)

    logger.info(f"COMPLAINT_REPLIED | tenant={tenant_id} | {ticket_id} | to={wa_id} | status={body.status or 'unchanged'}")
    return {"status": "ok", "ticket_id": ticket_id, "wa_id": wa_id, "sent": sent, "new_status": body.status}


@router.delete("/complaints/{ticket_id}")
def delete_complaint(
    tenant_id: str,
    ticket_id: str,
    principal: dict = Depends(_require("manage_complaints")),
):
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id FROM complaints WHERE ticket_id = ? AND tenant_id = ?",
            (ticket_id, tenant_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found for this tenant")
        conn.execute("DELETE FROM complaints WHERE ticket_id = ? AND tenant_id = ?", (ticket_id, tenant_id))
    return {"status": "ok", "ticket_id": ticket_id}
