"""Background listener for send2.digital incoming WhatsApp messages.

send2.digital stores incoming WhatsApp messages in their system. This module
polls the `incoming-report` endpoint every N seconds to fetch new messages,
processes them through the orchestrator, and sends replies via send2.digital's
`session-msg-send` API.

The listener deduplicates messages by `messageid` (WhatsApp message ID) so the
same message isn't processed twice even if the poll overlaps.

This module exposes `poll_incoming_messages()`, an endless async loop that runs
until the server shuts down or `stop_event` is set.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx

from routing.config import (
    SEND2_USERNAME,
    SEND2_PASSWORD,
    SEND2_INCOMING_URL,
)
from routing.whatsapp import (
    send_whatsapp_message,
    send_whatsapp_interactive,
    send_whatsapp_list_menu,
)

logger = logging.getLogger("IncomingListener")

# Poll cadence in seconds.
POLL_INTERVAL_SECONDS = 5

# Request timeout for each poll attempt.
HTTP_TIMEOUT_SECONDS = 10.0

async def _send_reply(wa_id: str, messages: list) -> None:
    """Send the orchestrator's captured messages via send2.digital.

    `messages` is a list of dicts like:
        {"type": "text", "text": "..."}
        {"type": "buttons", "text": "...", "buttons": [...]}
        {"type": "list", "header": "...", "body": "...", "button_text": "...", "sections": [...]}
    """
    for msg in messages:
        msg_type = msg.get("type", "text")
        try:
            if msg_type == "text":
                text = msg.get("text", "")
                if text:
                    send_whatsapp_message(wa_id, text)
                    logger.info(f"Sent text reply to {wa_id}: {text[:80]}...")

            elif msg_type == "buttons":
                text = msg.get("text", "")
                buttons = msg.get("buttons", [])
                if text and buttons:
                    # Convert button format: orchestrator returns {"id", "title"}
                    # send2.digital expects {"type": "reply", "reply": {"id", "title"}}
                    api_buttons = []
                    for btn in buttons:
                        api_buttons.append({
                            "type": "reply",
                            "reply": {
                                "id": btn.get("id", ""),
                                "title": btn.get("title", ""),
                            }
                        })
                    send_whatsapp_interactive(wa_id, text, api_buttons)
                    logger.info(f"Sent buttons reply to {wa_id}: {len(buttons)} buttons")

            elif msg_type == "list":
                header = msg.get("header", "")
                body = msg.get("body", "")
                button_text = msg.get("button_text", "Menu")
                sections = msg.get("sections", [])
                if body and sections:
                    send_whatsapp_list_menu(wa_id, header, body, button_text, sections)
                    logger.info(f"Sent list reply to {wa_id}: {len(sections)} sections")

            else:
                logger.warning(f"Unknown message type '{msg_type}' for {wa_id}")

        except Exception as e:
            logger.error(f"Failed to send {msg_type} reply to {wa_id}: {e}", exc_info=True)


async def poll_incoming_messages(stop_event: asyncio.Event = None) -> None:
    """Poll send2.digital for new incoming WhatsApp messages.

    Runs forever, sleeping `POLL_INTERVAL_SECONDS` between polls, until
    `stop_event` (if provided) is set. Each iteration fetches messages from
    the last hour, processes them through the orchestrator, and sends replies.
    """
    logger.info("Incoming message listener started (interval=%ds, url=%s)",
                POLL_INTERVAL_SECONDS, SEND2_INCOMING_URL)

    if not SEND2_USERNAME or not SEND2_PASSWORD:
        logger.error("SEND2_USERNAME or SEND2_PASSWORD not set — listener cannot start")
        return

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Incoming listener stopping")
            break

        try:
            # Fetch messages from the last hour to avoid missing any.
            now = datetime.now()
            from_date = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            to_date = now.strftime("%Y-%m-%d %H:%M:%S")

            payload = {
                "user_name": SEND2_USERNAME,
                "password": SEND2_PASSWORD,
                "from_date": from_date,
                "to_date": to_date,
            }

            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(SEND2_INCOMING_URL, json=payload)

                if response.status_code != 200:
                    logger.warning("Incoming report returned non-200: %s", response.status_code)
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                try:
                    messages = response.json()
                except json.JSONDecodeError:
                    # send2 returns plain text "No Data Found.." when the poll
                    # window has no new messages — that's a normal empty state,
                    # not an error worth logging on every poll.
                    if "No Data Found" in (response.text or ""):
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue
                    logger.warning("Incoming report returned non-JSON: %s", response.text[:200])
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                if not isinstance(messages, list):
                    logger.warning("Incoming report returned unexpected format: %s", type(messages))
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                # Process each new message.
                for msg in messages:
                    message_id = msg.get("messageid", "")
                    wa_id = str(msg.get("Number", "")).strip()
                    text = (msg.get("Message", "") or "").strip()
                    status = msg.get("status", "")
                    date_str = msg.get("Date", "")

                    # Skip if no message ID (test/dummy entries) or empty text.
                    if not message_id or not wa_id or not text:
                        continue

                    from services.dedup import is_duplicate
                    if is_duplicate(message_id, wa_id):
                        logger.info("Skipping duplicate message %s from %s", message_id, wa_id)
                        continue

                    logger.info(f"New message from {wa_id}: {text[:80]}... (id={message_id[:20]}...)")

                    try:
                        # Import here to avoid circular imports at module load.
                        from services.orchestrator import process_incoming_message

                        # Process through the orchestrator (captures outgoing messages).
                        result = await process_incoming_message(
                            wa_id, text, capture_only=True
                        )

                        # Send the captured replies via send2.digital.
                        outgoing = result.get("messages", [])
                        if outgoing:
                            await _send_reply(wa_id, outgoing)
                            logger.info(f"Processed and replied to {wa_id} ({len(outgoing)} messages)")
                        else:
                            logger.info(f"Processed {wa_id} but no outgoing messages")

                    except Exception as e:
                        logger.error(f"Failed to process message from {wa_id}: {e}", exc_info=True)

        except Exception as e:
            logger.error("Incoming listener poll failed: %s", e, exc_info=True)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
