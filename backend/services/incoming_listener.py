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
    normalize_reply_buttons,
)

logger = logging.getLogger("IncomingListener")

# Poll cadence in seconds.
POLL_INTERVAL_SECONDS = 5

# How far back each poll window reaches. Processed message IDs are persisted
# in `processed_inbound_messages` (backend/database.py), so a restart cannot
# re-answer rows already handled — the window only needs to cover the time the
# listener is briefly offline between polls.
POLL_WINDOW_MINUTES = 15

# Request timeout for each poll attempt.
HTTP_TIMEOUT_SECONDS = 10.0

# In-memory dedup fast path (the durable record lives in SQLite). Keep bounded.
_processed_message_ids: set = set()
_MAX_PROCESSED_IDS = 5000


def _cleanup_processed_ids() -> None:
    """Keep the processed-IDs set bounded."""
    if len(_processed_message_ids) > _MAX_PROCESSED_IDS:
        _processed_message_ids.clear()


def _record_processed(message_id: str, wa_id: str) -> None:
    """Mark a message as handled in both the in-memory set and SQLite.

    The SQLite record is authoritative: the poll window overlaps by design and
    the app restarts, so an in-memory-only set would let old rows get answered
    again after every restart ("sending without messaging anything").
    """
    _processed_message_ids.add(message_id)
    try:
        from database import mark_inbound_processed
        mark_inbound_processed(message_id, wa_id)
    except Exception as e:
        logger.warning(f"Could not persist processed id {message_id}: {e}")


def _was_processed(message_id: str) -> bool:
    if message_id in _processed_message_ids:
        return True
    try:
        from database import was_inbound_processed
        return was_inbound_processed(message_id)
    except Exception as e:
        logger.warning(f"Could not check processed id {message_id}: {e}")
        return False


def _reply_text(outgoing: list) -> str:
    """Concatenate the reply text for chat_history logging."""
    parts = []
    for msg in outgoing or []:
        # Include live-sent messages too: in live mode every captured message
        # carries sent_live=True, so skipping them left chat_history empty.
        if msg.get("type") == "text" and msg.get("text"):
            parts.append(msg["text"])
        elif msg.get("type") == "list" and msg.get("body"):
            parts.append(msg["body"])
        elif msg.get("type") == "buttons" and msg.get("text"):
            parts.append(msg["text"])
    return "\n".join(p for p in parts if p.strip())[:2000]


def _record_chat(wa_id: str, sender_name: str, text: str, outgoing: list) -> None:
    """Persist the exchange so the admin console shows it in chat history."""
    reply = _reply_text(outgoing)
    if not text or not reply:
        return
    try:
        from database import save_chat
        save_chat(wa_id, sender_name or "", text, reply, route="send2")
    except Exception as e:
        logger.warning(f"Could not save chat for {wa_id}: {e}")


def _record_poll(wa_id: str, text: str) -> None:
    """Write a webhook_logs row so the admin webhook stats are non-empty."""
    try:
        from database import log_webhook
        log_webhook("incoming", "send2/poll", {"wa_id": wa_id, "message": (text or "")[:500]})
    except Exception as e:
        logger.warning(f"Could not log poll webhook for {wa_id}: {e}")


async def _send_reply(wa_id: str, messages: list) -> None:
    """Send the orchestrator's captured messages via send2.digital.

    `messages` is a list of dicts like:
        {"type": "text", "text": "..."}
        {"type": "buttons", "text": "...", "buttons": [...]}
        {"type": "list", "header": "...", "body": "...", "button_text": "...", "sections": [...]}
    """
    for msg in messages:
        if msg.get("sent_live"):
            # Already delivered to WhatsApp by whatsapp_sender during orchestrator run
            logger.info(f"Skipping reply to {wa_id} — already sent live by sender")
            continue
        msg_type = msg.get("type", "text")
        try:
            if msg_type == "text":
                text = msg.get("text", "")
                if text:
                    send_whatsapp_message(wa_id, text)
                    logger.info(f"Sent text reply to {wa_id}: {text[:80]}...")

            elif msg_type == "buttons":
                text = msg.get("text", "")
                # Buttons arrive already nested ({"type":"reply","reply":{...}})
                # from the workflows; normalize tolerates flat {"id","title"} too.
                api_buttons = normalize_reply_buttons(msg.get("buttons", []))
                if text and api_buttons:
                    # Convert to interactive list menu because send2.digital's incoming-report
                    # returns Message: null for WhatsApp quick-reply button taps. List menu selections
                    # return the selected option title in Message, ensuring 100% reliable clicks.
                    rows = []
                    for b in api_buttons:
                        r = b.get("reply", {})
                        bid = r.get("id", "")
                        btitle = r.get("title", "")[:24]
                        if bid and btitle:
                            rows.append({
                                "id": bid,
                                "title": btitle,
                                "description": "",
                            })
                    if rows:
                        send_whatsapp_list_menu(
                            to=wa_id,
                            header_text="Leeway Softech",
                            body_text=text,
                            button_text="Select Option",
                            sections=[{"title": "Options", "rows": rows}],
                        )
                        logger.info(f"Sent options list menu to {wa_id}: {len(rows)} options")
                    else:
                        send_whatsapp_message(wa_id, text)
                        logger.info(f"Sent text reply (no valid buttons) to {wa_id}")
                elif text:
                    send_whatsapp_message(wa_id, text)
                    logger.info(f"Sent text reply (no valid buttons) to {wa_id}")

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
            # Fetch messages from the recent window (processed-ID ledger in
            # SQLite makes overlap + restarts safe, so no 1-hour re-scan).
            now = datetime.now()
            from_date = (now - timedelta(minutes=POLL_WINDOW_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
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
                    sender_name = str(msg.get("Name") or msg.get("SenderName") or "").strip()

                    # Skip if no message ID (test/dummy entries).
                    if not message_id or not wa_id:
                        continue

                    # Only inbound rows spawn a bot reply + customer record;
                    # outbound statuses (sent/delivered/failed/read) are handled
                    # by the reporters and must not echo back.
                    if status and str(status).strip().lower() in (
                        "sent", "delivered", "failed", "read",
                    ):
                        continue

                    # Skip if already processed (memory + persisted ledger).
                    if _was_processed(message_id):
                        continue

                    if not text:
                        # send2.digital's incoming-report API returns Message=null when a user taps
                        # a WhatsApp quick-reply button. Handle it gracefully by sending the list options.
                        if str(status).strip().lower() == "received":
                            logger.info(f"Handling unmapped button click (null text) from {wa_id} id={message_id[:20]}")
                            try:
                                from bots.customer_b2c import menus
                                from routing.whatsapp import send_whatsapp_list_menu
                                menu_data = menus.get_main_menu(wa_id)
                                send_whatsapp_list_menu(
                                    to=wa_id,
                                    header_text=menu_data.get("header", "Leeway Softech"),
                                    body_text="I received your selection! Please choose an option from the menu below:",
                                    button_text=menu_data.get("button_text", "Show Options"),
                                    sections=menu_data.get("sections", []),
                                )
                            except Exception as ex:
                                logger.error(f"Failed to handle null message fallback: {ex}")
                            _record_processed(message_id, wa_id)
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

                        # Mark as processed only after the reply was sent so a
                        # crash mid-send retries instead of dropping the answer.
                        _record_processed(message_id, wa_id)
                        _record_chat(wa_id, sender_name, text, outgoing)
                        _record_poll(wa_id, text)

                    except Exception as e:
                        logger.error(f"Failed to process message from {wa_id}: {e}", exc_info=True)

                # Periodic cleanup of the processed-IDs set.
                _cleanup_processed_ids()

        except Exception as e:
            logger.error("Incoming listener poll failed: %s", e, exc_info=True)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
