"""
send2.digital webhook endpoint.

Provides a ``POST /api/send2/webhook`` endpoint that accepts incoming WhatsApp
messages from send2.digital's push-based webhook (if configured in their
dashboard). This is an alternative to the polling-based ``incoming_listener.py``.

The endpoint accepts the send2.digital format:
    {
        "username": "xxxxx",
        "password": "xxxxx",
        "number": 918690983030,
        "msg_type": "text",
        "msg": "hello",
        "time": "2026-08-22 10:00:00"
    }

It processes the message through the orchestrator and sends replies via
send2.digital's session-msg-send API.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("send2_webhook")

router = APIRouter(prefix="/api/send2", tags=["send2"])


class Send2WebhookRequest(BaseModel):
    """Request body from send2.digital webhook."""
    username: str
    password: str
    number: int
    msg_type: str = "text"
    msg: str = ""
    time: Optional[str] = ""


@router.post("/webhook")
async def receive_send2_webhook(request: Send2WebhookRequest):
    """Process an incoming WhatsApp message from send2.digital.

    This endpoint can be configured as the webhook URL in send2.digital's
    dashboard. When a user sends a WhatsApp message, send2.digital will POST
    it here. The message is processed through the orchestrator and replies
    are sent back via send2.digital's API.
    """
    from routing.config import SEND2_USERNAME, SEND2_PASSWORD
    from routing.whatsapp import (
        send_whatsapp_message,
        send_whatsapp_interactive,
        send_whatsapp_list_menu,
        normalize_reply_buttons,
    )
    from services.orchestrator import process_incoming_message

    # Validate credentials (optional but recommended).
    if SEND2_USERNAME and SEND2_PASSWORD:
        if request.username != SEND2_USERNAME or request.password != SEND2_PASSWORD:
            logger.warning(f"Invalid credentials from {request.number}")
            raise HTTPException(status_code=401, detail="Invalid credentials")

    wa_id = str(request.number).strip()
    text = (request.msg or "").strip()

    if not wa_id or not text:
        logger.warning(f"Empty message from {wa_id}")
        return {"status": "ignored", "reason": "empty message"}

    logger.info(f"send2 webhook: from={wa_id} msg={text[:80]}...")

    try:
        # Process through the orchestrator (captures outgoing messages).
        result = await process_incoming_message(wa_id, text)

        # Send the captured replies via send2.digital.
        outgoing = result.get("messages", [])
        sent_count = 0

        for msg in outgoing:
            if msg.get("sent_live"):
                logger.info(f"Skipping send2_webhook reply to {wa_id} — already sent live by sender")
                sent_count += 1
                continue
            msg_type = msg.get("type", "text")
            try:
                if msg_type == "text":
                    reply_text = msg.get("text", "")
                    if reply_text:
                        send_whatsapp_message(wa_id, reply_text)
                        sent_count += 1

                elif msg_type == "buttons":
                    reply_text = msg.get("text", "")
                    # Buttons arrive already nested; normalize tolerates flat
                    # {"id","title"} and drops any missing reply.id (which would
                    # otherwise make WhatsApp reject the whole message).
                    api_buttons = normalize_reply_buttons(msg.get("buttons", []))
                    if reply_text and api_buttons:
                        send_whatsapp_interactive(wa_id, reply_text, api_buttons)
                        sent_count += 1
                    elif reply_text:
                        send_whatsapp_message(wa_id, reply_text)
                        sent_count += 1

                elif msg_type == "list":
                    header = msg.get("header", "")
                    body = msg.get("body", "")
                    button_text = msg.get("button_text", "Menu")
                    sections = msg.get("sections", [])
                    if body and sections:
                        send_whatsapp_list_menu(wa_id, header, body, button_text, sections)
                        sent_count += 1

            except Exception as e:
                logger.error(f"Failed to send {msg_type} reply to {wa_id}: {e}", exc_info=True)

        logger.info(f"send2 webhook processed: {wa_id} sent {sent_count} replies")
        return {
            "status": "processed",
            "wa_id": wa_id,
            "replies_sent": sent_count,
            "user_type": result.get("user_type"),
        }

    except Exception as e:
        logger.error(f"send2 webhook failed for {wa_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
