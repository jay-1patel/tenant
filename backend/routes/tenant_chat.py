"""Tenant-scoped internal admin chat.

The existing ``/api/admin/chat`` routes are a single-tenant, global admin lobby.
This module adds a parallel, tenant-owned chat so a brand's staff only see and
talk to each other, with messages separated by ``tenant_id``.

    GET    /api/admin/tenants/{tenant_id}/chat/users
    POST   /api/admin/tenants/{tenant_id}/chat/send
    DELETE /api/admin/tenants/{tenant_id}/chat/message/{msg_id}
    WS     /api/admin/tenants/{tenant_id}/chat/ws/{username}

The manager keys rooms by tenant, so presence and broadcasts never leak across
brands. It is deliberately separate from the global ``ChatManager`` so the
single-tenant deployment keeps working untouched.
"""

import json
import logging
import jwt
from typing import Dict, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials

from routing.config import ADMIN_SECRET_KEY
from database import (
    get_admin_chat_history,
    get_all_admins_except,
    get_db_context,
    save_admin_chat_message,
    soft_delete_message_for_everyone,
    soft_delete_message_for_user,
)
from routes.auth import get_current_admin, has_permission, require_tenant_access, security
from routes.chat_admin import _strip_conn_id, make_chat_id

logger = logging.getLogger("tenant_chat")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}", tags=["tenant-chat"])


class TenantChatManager:
    """WebSocket rooms partitioned by tenant.

    ``connections[tenant_id][username]`` holds the live sockets for one user in
    one tenant; ``_meta`` remembers which tenant a socket belongs to so it can
    be cleaned up without a scan.
    """

    def __init__(self) -> None:
        self.connections: Dict[str, Dict[str, Set[WebSocket]]] = {}
        self._meta: Dict[WebSocket, str] = {}

    def _room(self, tenant_id: str) -> Dict[str, Set[WebSocket]]:
        return self.connections.setdefault(tenant_id, {})

    async def connect(self, websocket: WebSocket, tenant_id: str, raw_username: str) -> None:
        await websocket.accept()
        real = _strip_conn_id(raw_username)
        self._room(tenant_id).setdefault(real, set()).add(websocket)
        self._meta[websocket] = tenant_id
        await self.broadcast_online(tenant_id)

    def remove_ws(self, websocket: WebSocket) -> None:
        tenant_id = self._meta.pop(websocket, None)
        if not tenant_id:
            return
        room = self.connections.get(tenant_id)
        if not room:
            return
        for real, conns in list(room.items()):
            conns.discard(websocket)
            if not conns:
                del room[real]
        if not room:
            self.connections.pop(tenant_id, None)

    async def broadcast(self, tenant_id: str, message: dict, exclude: WebSocket = None) -> None:
        for conns in list(self._room(tenant_id).values()):
            for ws in list(conns):
                if ws is exclude:
                    continue
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    async def broadcast_online(self, tenant_id: str) -> None:
        room = self._room(tenant_id)
        online = list(room.keys())
        all_ws: Set[WebSocket] = set()
        for conns in room.values():
            all_ws.update(conns)
        for ws in all_ws:
            try:
                await ws.send_json({"type": "online_users", "users": online})
            except Exception:
                pass

    async def send_message(
        self,
        tenant_id: str,
        chat_id: str,
        raw_username: str,
        text: str,
        attachment: dict = None,
    ) -> dict:
        real = _strip_conn_id(raw_username)
        saved = save_admin_chat_message(chat_id, real, text, attachment=attachment, tenant_id=tenant_id)
        message = {
            "type": "message",
            "chat_id": chat_id,
            "username": real,
            "text": text,
            "message": text,
            "timestamp": saved["created_at"],
            "created_at": saved["created_at"],
            "id": saved["id"],
            "attachment": attachment,
        }
        await self.broadcast(tenant_id, message)
        return message


manager = TenantChatManager()


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


def _current_admin_username(request: Request, credentials: HTTPAuthorizationCredentials) -> str:
    return get_current_admin(request, credentials).get("username", "")


@router.get("/chat/users")
def list_tenant_chat_users(
    tenant_id: str,
    request: Request,
    principal: dict = Depends(_require("chat_history")),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """The other admins, each with the last message in this tenant's thread."""
    if principal.get("type") == "tenant":
        username = principal.get("label") or ""
    else:
        username = _current_admin_username(request, credentials)

    is_global_admin = principal.get("type") != "tenant" and principal.get("role") == "super_admin"
    admins = get_all_admins_except(
        username,
        tenant_id=tenant_id,
        include_all=is_global_admin,
    )
    result = []
    with get_db_context() as conn:
        for admin in admins:
            cid = make_chat_id(username, admin)
            row = conn.execute(
                """SELECT username, message, created_at, attachment_json
                   FROM admin_chat_messages
                   WHERE chat_id = ? AND tenant_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (cid, tenant_id),
            ).fetchone()
            last = None
            if row:
                last = {
                    "username": row["username"],
                    "message": row["message"],
                    "created_at": row["created_at"],
                    "attachment": json.loads(row["attachment_json"]) if row["attachment_json"] else None,
                }
            result.append({
                "username": admin,
                "chat_id": cid,
                "last_message": last,
            })
    return {"users": result}


@router.post("/chat/send")
async def send_tenant_chat_message(
    tenant_id: str,
    data: dict,
    request: Request,
    principal: dict = Depends(_require("chat")),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    chat_id = data.get("chat_id", "")
    text = (data.get("text") or "").strip()
    attachment = data.get("attachment")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")
    if not text and not attachment:
        raise HTTPException(status_code=400, detail="message is empty")

    if principal.get("type") == "tenant":
        username = principal.get("label") or "tenant"
    else:
        username = _current_admin_username(request, credentials)

    message = await manager.send_message(tenant_id, chat_id, username, text, attachment=attachment)
    return {"status": "ok", "message": message}


@router.post("/chat/attach")
async def attach_tenant_chat_file(
    tenant_id: str,
    data: dict,
    principal: dict = Depends(_require("chat")),
):
    """Host a file and return its descriptor, for sending as a chat attachment."""
    from routes.admin import decode_attachment_body, store_chat_attachment

    filename, content, media_type = decode_attachment_body(data)
    return await store_chat_attachment(filename, content, media_type)


@router.delete("/chat/message/{msg_id}")
def delete_tenant_chat_message(
    tenant_id: str,
    msg_id: int,
    principal: dict = Depends(_require("chat")),
):
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT tenant_id FROM admin_chat_messages WHERE id = ?", (msg_id,)
        ).fetchone()
    if not row or (row["tenant_id"] not in (tenant_id, None)):
        raise HTTPException(status_code=404, detail="Message not found for this tenant")
    soft_delete_message_for_everyone(msg_id)
    return {"status": "ok"}


@router.websocket("/chat/ws/{username}")
async def tenant_chat_websocket(
    websocket: WebSocket,
    tenant_id: str,
    username: str,
    token: str = Query(None),
    conn_id: str = Query("chat"),
):
    if not token:
        await websocket.close(code=4001)
        return
    try:
        payload = jwt.decode(token, ADMIN_SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        await websocket.close(code=4001)
        return
    # The socket may only speak as the identity it authenticated as.
    if payload.get("sub") != username:
        await websocket.close(code=4001)
        return

    raw_username = f"{username}:{conn_id}"
    await manager.connect(websocket, tenant_id, raw_username)
    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get("type")
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
            elif kind == "message" and (data.get("text", "").strip() or data.get("attachment")):
                chat_id = data.get("chat_id", "")
                if not chat_id:
                    continue
                await manager.send_message(
                    tenant_id,
                    chat_id,
                    raw_username,
                    data.get("text", "").strip(),
                    attachment=data.get("attachment"),
                )
            elif kind == "load_history":
                chat_id = data.get("chat_id", "")
                if chat_id:
                    history = get_admin_chat_history(chat_id, username=username, tenant_id=tenant_id)
                    await websocket.send_json({"type": "history", "chat_id": chat_id, "messages": history})
            elif kind == "delete_message":
                msg_id = data.get("message_id")
                scope = data.get("scope", "everyone")
                if msg_id is not None:
                    if scope == "me":
                        soft_delete_message_for_user(msg_id, username)
                    else:
                        soft_delete_message_for_everyone(msg_id)
                await manager.broadcast(tenant_id, {"type": "delete_message", "message_id": msg_id})
    except WebSocketDisconnect:
        manager.remove_ws(websocket)
        await manager.broadcast_online(tenant_id)
    except Exception as exc:
        logger.error("Tenant chat WebSocket error: %s", exc)
        manager.remove_ws(websocket)
        await manager.broadcast_online(tenant_id)
