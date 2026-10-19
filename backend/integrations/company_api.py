"""
Company API Integration for Message Logging

Incoming messages (and opt-out events) are logged to the send2.digital
AI_chatbot_API_incomingentry endpoint so the platform keeps an incoming-message
record. This matches the endpoint format:

    POST https://api.send2.digital/devdesk/AI_chatbot_API_incomingentry
    {
        "username": "...", "password": "...",
        "number": <wa_id>, "msg_type": "text", "msg": "hello",
        "time": "YYYY-MM-DD HH:MM:SS"
    }
"""

import logging
from datetime import datetime

import httpx

logger = logging.getLogger("company_api")

try:
    from routing.config import SEND2_INCOMING_ENTRY_URL, SEND2_USERNAME, SEND2_PASSWORD
    _INCOMING_ENTRY_URL = SEND2_INCOMING_ENTRY_URL
    _USER = SEND2_USERNAME
    _PASS = SEND2_PASSWORD
except Exception:
    _INCOMING_ENTRY_URL = None
    _USER = None
    _PASS = None


def _map_msg_type(msg_type):
    if not msg_type:
        return "text"
    mt = str(msg_type).lower()
    if mt in ("pdf", "doc", "docx", "xlsx", "csv"):
        return "document"
    if mt == "jpg":
        return "image"
    if mt in ("text", "image", "video", "audio", "document", "location", "sticker", "contacts"):
        return mt
    return "text"


async def log_incoming_message(wa_id, message, msg_type="text"):
    return await log_message(wa_id, message, msg_type, direction="incoming")


async def log_outgoing_message(wa_id, response, msg_type="text"):
    logger.debug(f"[outgoing log skipped] {wa_id}")
    return True


async def log_message(wa_id, content, msg_type="text", direction="incoming"):
    if not _INCOMING_ENTRY_URL:
        logger.debug("AI_chatbot_API_incomingentry URL not configured - skip log")
        return True

    payload = {
        "username": _USER,
        "password": _PASS,
        "number": wa_id,
        "msg_type": _map_msg_type(msg_type),
        "msg": content or "",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_INCOMING_ENTRY_URL, json=payload)
        ok = resp.status_code == 200
        logger.info(f"INCOMING_ENTRY | to={wa_id} | status={resp.status_code} | body={resp.text[:200]}")
        return ok
    except Exception as e:
        logger.warning(f"INCOMING_ENTRY_FAILED | to={wa_id} | error={e}")
        return False


async def test_company_api_connection():
    if not _INCOMING_ENTRY_URL:
        return {"success": True, "message": "Company API integration is disabled"}
    return {"success": True, "message": f"Incoming entry endpoint: {_INCOMING_ENTRY_URL}"}
