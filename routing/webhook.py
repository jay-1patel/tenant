import json
import logging
import time
from fastapi import APIRouter, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse
import routing.config as config
from routing.database import get_db_context, log_webhook, save_chat, set_request_tenant
from routing.whatsapp import send_whatsapp_message, send_whatsapp_interactive, send_whatsapp_list_menu, _resolve_media_url, _normalize_msg_type
from routing.message import (
    process_message, DOCUMENT_BUTTON_ID, is_direct_media_query,
    build_catalog_text_fallback,
)
from routing.classifier import classify_query
from routing.button_actions import get_action, BUTTON_REGISTRY
from backend.integrations.company_api import log_incoming_message, log_outgoing_message

logger = logging.getLogger("chiki_webhook")
router = APIRouter()

_processed_ids = set()

# Phrases that trigger human handover
# Campaign consent (WhatsApp policy): STOP unsubscribes from broadcasts,
# START resubscribes. Every audience count excludes opted-out contacts.
OPT_OUT_PHRASES = {"stop", "unsubscribe", "opt out", "optout", "stop messages"}
OPT_IN_PHRASES = {"start", "subscribe", "resubscribe"}
OPT_OUT_CONFIRMATION = (
    "You have been unsubscribed from campaign messages. "
    "You will not receive any more broadcasts.\n\n"
    "Type *start* anytime to subscribe again."
)
OPT_IN_CONFIRMATION = "Welcome back! You will receive campaign messages again. \U0001f64f"

HUMAN_HANDOVER_PHRASES = [
    "human", "agent", "real person", "talk to a human", "speak to a human",
    "customer support", "representative", "talk to agent", "speak to agent",
    "connect me", "connect to", "talk to someone", "speak to someone",
    "real human", "live person", "live agent",
]

HANDOVER_CONFIRMATION = "You're now connected to a human agent. Please hold on while we pick up your conversation. 🙏\n\nType *hi* anytime to continue with the chatbot."

HANDOVER_BOT_RESUME = "You're back with the bot. How can I help you? 🙏"

_PENDING_DOC_EXPIRY_SECONDS = 30 * 60
_pending_docs = {}


def _handle_campaign_opt_out(user_text: str, wa_id: str, sender_name: str, tenant_id) -> bool:
    """STOP/START handling for campaign broadcasts (WhatsApp opt-in policy).

    Returns True when the message was consumed, so the bot does not also reply.
    Opt-outs live in campaign_opt_outs; every audience count excludes them.
    """
    text = (user_text or "").strip().lower()
    if text not in OPT_OUT_PHRASES and text not in OPT_IN_PHRASES:
        return False

    tid = tenant_id or "default"
    try:
        with get_db_context() as conn:
            # Safe on a routing-only deployment where the backend schema has
            # not been created yet.
            conn.execute(
                """CREATE TABLE IF NOT EXISTS campaign_opt_outs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    wa_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_campaign_opt_outs "
                "ON campaign_opt_outs(tenant_id, wa_id)"
            )
            if text in OPT_OUT_PHRASES:
                conn.execute(
                    "INSERT OR IGNORE INTO campaign_opt_outs (tenant_id, wa_id) VALUES (?, ?)",
                    (tid, wa_id),
                )
                reply = OPT_OUT_CONFIRMATION
                event = "stop"
            else:
                conn.execute(
                    "DELETE FROM campaign_opt_outs WHERE tenant_id = ? AND wa_id = ?",
                    (tid, wa_id),
                )
                reply = OPT_IN_CONFIRMATION
                event = "start"
    except Exception as exc:
        logger.error(f"Campaign opt-out handling failed for {wa_id}: {exc}")
        return False

    save_chat(wa_id, sender_name, user_text, reply, "campaign_opt_out")
    send_whatsapp_message(wa_id, reply)
    logger.info(f"CAMPAIGN_CONSENT | {event} | tenant={tid} | wa_id={wa_id}")
    return True


def _is_doc_button_reply(message) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("type") != "interactive":
        return False
    interactive = message.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return False
    return interactive.get("button_reply", {}).get("id") == DOCUMENT_BUTTON_ID


def _wants_human_agent(text: str) -> bool:
    """Return True if the user message requests a human agent."""
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in HUMAN_HANDOVER_PHRASES)


def _set_human_handover(wa_id: str, enabled: bool = True) -> None:
    """Set or clear the human_handover flag for a user."""
    try:
        from database import set_human_handover
        set_human_handover(wa_id, enabled)
        logger.info(f"HANDOVER {'ENABLED' if enabled else 'DISABLED'} for {wa_id}")
    except Exception as e:
        logger.error(f"Failed to set handover for {wa_id}: {e}")


def _is_handover_active(wa_id: str) -> bool:
    """Check if human_handover is currently active for a user."""
    import sqlite3
    db_path = config.DB_PATH if hasattr(config, 'DB_PATH') else None
    if not db_path:
        return False
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT human_handover FROM user_states WHERE wa_id = ?", (wa_id,)
        ).fetchone()
        conn.close()
        return row is not None and row[0] == 1
    except Exception:
        return False


def _pop_pending_doc(wa_id):
    doc = _pending_docs.pop(wa_id, None)
    if not doc:
        return None
    if time.time() - doc.get("created_at", 0) > _PENDING_DOC_EXPIRY_SECONDS:
        return None
    return doc


def _extract_button_press(message) -> tuple[str, str]:
    """Return (button_id, button_title) from an interactive button_reply, or ('', '')."""
    if not isinstance(message, dict) or message.get("type") != "interactive":
        return "", ""
    interactive = message.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return "", ""
    reply = interactive.get("button_reply", {})
    return (reply.get("id", "") or "", reply.get("title", "") or "")


def _extract_pressed_id(message) -> str:
    """Machine id of ANY interactive tap — quick-reply button or list row.

    Used only by the profile-flow dispatch (Phase 3): list taps previously
    flowed through as title text, and the registry dispatch below must keep
    seeing only button_reply ids so legacy behaviour is untouched.
    """
    if not isinstance(message, dict) or message.get("type") != "interactive":
        return ""
    interactive = message.get("interactive", {})
    if interactive.get("type") == "button_reply":
        return (interactive.get("button_reply", {}) or {}).get("id", "") or ""
    if interactive.get("type") == "list_reply":
        return (interactive.get("list_reply", {}) or {}).get("id", "") or ""
    return ""


def _resolve_public(url: str) -> str:
    """Resolve a stored/local media URL to a public HTTPS URL."""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    try:
        from kb.services.whatsapp import resolve_public_media_url
        resolved = resolve_public_media_url(url)
        if resolved:
            return resolved
    except Exception:
        pass
    return _resolve_media_url(url)


def _find_doc_by_source(source_stem: str):
    """Find an uploaded FAQ/KB document whose filename contains the source stem."""
    import os
    if not source_stem:
        return None
    upload_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "uploaded_files")
    for sub in ("faq", "kb", ""):
        folder = os.path.normpath(os.path.join(upload_root, sub))
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            stem, ext = os.path.splitext(fname)
            if source_stem.lower() in stem.lower() and ext.lower() in (".txt", ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"):
                return os.path.join(folder, fname)
    return None


def _handover_blocked(wa_id: str):
    """Refusal payload when this user's tenant has human_handover switched off.

    Returns None when the feature is on (or tenancy is unavailable), so the
    legacy single-tenant behaviour is untouched.
    """
    try:
        from shared.tenancy.gating import guard_result
        return guard_result(wa_id, "human_handover")
    except Exception as exc:
        logger.debug(f"handover gate unavailable: {exc}")
        return None


async def _handle_registry_button(wa_id: str, sender_name: str, action: dict, start_time: float) -> bool:
    """Execute a registry button action directly. Returns True if handled."""
    kind = action.get("kind")
    payload = action.get("payload", "")

    if kind == "handover":
        blocked = _handover_blocked(wa_id)
        if blocked:
            save_chat(wa_id, sender_name, action["title"], blocked["message"], "refusal")
            if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                send_whatsapp_message(wa_id, blocked["message"])
            logger.info(f"HANDOVER_BLOCKED | {wa_id} | human_handover off for tenant")
            return True
        _set_human_handover(wa_id, enabled=True)
        save_chat(wa_id, sender_name, action["title"], HANDOVER_CONFIRMATION, "human_handover")
        if config.SEND2_USERNAME and config.SEND2_PASSWORD:
            send_whatsapp_message(wa_id, HANDOVER_CONFIRMATION)
        logger.info(f"HANDOVER_TRIGGERED | {wa_id} | via button {action['id']}")
        return True

    if kind == "document":
        # Document delivery is disabled — answer via the FAQ pipeline as text.
        query = payload or action.get("title") or ""
        response = await process_message(query, wa_id)
        response_text = response.get("answer", "") or (
            "Please ask your question and I'll answer it right here. 🙏"
        )
        save_chat(wa_id, sender_name, action["title"], response_text, "faq")
        if config.SEND2_USERNAME and config.SEND2_PASSWORD:
            send_whatsapp_message(wa_id, response_text)
        logger.info(f"BUTTON_DOC_DISABLED_AS_TEXT | {wa_id} | action={action['id']}")
        return True

    if kind == "question" and payload:
        # Re-run the pipeline with the action's payload as the query.
        response = await process_message(payload, wa_id)
        response_text = response.get("answer", "")
        media_url = response.get("media_url")
        media_type = response.get("media_type")
        # Media is never sent anymore — replies go out as text only.
        if media_type:
            media_url = None
            media_type = None
        save_chat(wa_id, sender_name, action["title"], response_text, response.get("query_type", "faq"))
        if config.SEND2_USERNAME and config.SEND2_PASSWORD:
            interactive = response.get("interactive")
            if interactive and interactive.get("type") == "button" and interactive.get("buttons"):
                sent = send_whatsapp_interactive(wa_id, response_text, interactive["buttons"])
                if sent and media_url and any(
                    b.get("reply", {}).get("id") == DOCUMENT_BUTTON_ID for b in interactive["buttons"]
                ):
                    _pending_docs[wa_id] = {
                        "url": media_url, "type": media_type or "document", "created_at": time.time(),
                    }
                if not sent:
                    send_whatsapp_message(wa_id, response_text)
            else:
                if media_url and media_type and config.SEND_MEDIA:
                    media_url = _resolve_public(media_url)
                    if not send_whatsapp_message(wa_id, media_url, _normalize_msg_type(media_type)):
                        send_whatsapp_message(wa_id, response_text)
                else:
                    send_whatsapp_message(wa_id, response_text)
            await log_outgoing_message(wa_id, response_text, "text")
        logger.info(f"BUTTON_QUESTION | {wa_id} | action={action['id']} | payload={payload[:60]}")
        return True

    return False


def _is_duplicate(msg_id: str) -> bool:
    if not msg_id:
        return False
    if msg_id in _processed_ids:
        return True
    _processed_ids.add(msg_id)
    if len(_processed_ids) > 5000:
        _processed_ids.clear()
    return False


async def _process_and_reply(wa_id, sender_name, user_text, msg_type, message, msg_id, tenant_id=None):
    start_time = time.time()
    # Attribute everything this message writes (chat history, complaints, state)
    # to the tenant that owns the inbound phone number.
    if tenant_id:
        set_request_tenant(tenant_id)
        try:
            from backend.services import state_manager as sm
            sm.set_tenant(wa_id, tenant_id)
        except Exception as exc:
            logger.debug(f"Could not stamp tenant {tenant_id} on {wa_id}: {exc}")
    try:
        # ── CHECK HUMAN HANDOVER ────────────────────────────────────────
        # While a human agent is handling the conversation, still save the
        # message so it appears in the agent inbox, BUT also let the bot
        # keep answering so the chat is never stuck.
        if _is_handover_active(wa_id):
            logger.info(f"HANDOVER_ACTIVE | {wa_id} | saving for agent, bot continues")
            save_chat(wa_id, sender_name, user_text, "", "human_handover")

        # ── CHECK IF USER WANTS A HUMAN AGENT ───────────────────────────
        if _wants_human_agent(user_text):
            blocked = _handover_blocked(wa_id)
            if blocked:
                # The tenant switched human handover off: refuse politely and
                # let the bot keep the conversation.
                save_chat(wa_id, sender_name, user_text, blocked["message"], "refusal")
                if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                    send_whatsapp_message(wa_id, blocked["message"])
                logger.info(f"HANDOVER_BLOCKED | {wa_id} | human_handover off for tenant")
                return
            _set_human_handover(wa_id, enabled=True)
            save_chat(wa_id, sender_name, user_text, HANDOVER_CONFIRMATION, "human_handover")
            if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                send_whatsapp_message(wa_id, HANDOVER_CONFIRMATION)
            logger.info(f"HANDOVER_TRIGGERED | {wa_id} | user requested human agent")
            return

        # ── PROFILE FLOW (multi-step form in progress, Phase 3) ────────
        # A running profile-defined flow consumes the reply directly (no LLM
        # / FAQ pipeline involvement). Only consumes when a flow is actually
        # running; otherwise this hook is invisible.
        try:
            from backend.services import flow_runner
            if flow_runner.is_running(wa_id):
                outcome = flow_runner.handle_reply(wa_id, user_text)
                if outcome:
                    for msg in outcome.get("messages", []):
                        if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                            send_whatsapp_message(wa_id, msg)
                    reply_text = "\n".join(outcome.get("messages", []))
                    save_chat(wa_id, sender_name, user_text, reply_text, "flow")
                    await log_incoming_message(wa_id, user_text, msg_type)
                    await log_outgoing_message(wa_id, reply_text, "text")
                    logger.info(f"FLOW_REPLY | {wa_id} | flow={outcome.get('flow')} | "
                                f"finished={outcome.get('finished')}")
                    return
        except Exception as e:
            logger.error(f"Profile flow reply handling failed (continuing): {e}")

        # Log incoming message to company API
        await log_incoming_message(wa_id, user_text, msg_type)

        if _is_doc_button_reply(message):
            # Document delivery is disabled — never send files to customers.
            _pop_pending_doc(wa_id)
            note = (
                "I no longer share documents in this chat, but I'd be happy to "
                "answer your question right here. Go ahead and ask! 🙏"
            )
            if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                send_whatsapp_message(wa_id, note)
                await log_outgoing_message(wa_id, note, "text")
            save_chat(wa_id, sender_name, user_text, note, "faq")
            send_status = "document_delivery_disabled"
            response_time_ms = int((time.time() - start_time) * 1000)
            log_webhook("outgoing", "/webhook/reply", json.dumps({
                "to": wa_id, "response": note
            }), 200, f"Reply {send_status} to {sender_name}", response_time_ms=response_time_ms)
            return

        # ── PROFILE-DEFINED FLOW START (Phase 3) ───────────────────────
        # A tapped menu row/button whose profile entry names a flow starts the
        # runner. Only a SUCCESSFUL start consumes the tap — a refused flow
        # (feature off, unknown) falls through to the pipeline below unchanged.
        pressed_id = _extract_pressed_id(message)
        if pressed_id and pressed_id.startswith("menu_"):
            try:
                from backend.services.menu_catalog import profile_button_status
                exists, available = profile_button_status(
                    pressed_id, wa_id=wa_id, tenant_id=tenant_id
                )
                if exists and not available:
                    note = "That menu option is no longer available. Please choose another option or ask our team for help."
                    if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                        send_whatsapp_message(wa_id, note)
                    save_chat(wa_id, sender_name, user_text, note, "menu_unavailable")
                    await log_outgoing_message(wa_id, note, "text")
                    return
                if not exists and pressed_id.startswith("menu_") and not pressed_id.startswith(("menu_faq", "menu_human", "menu_view_cart", "menu_new_arrivals")):
                    note = "That menu option is no longer available. Please type your question or ask our team for help."
                    if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                        send_whatsapp_message(wa_id, note)
                    save_chat(wa_id, sender_name, user_text, note, "menu_unavailable")
                    await log_outgoing_message(wa_id, note, "text")
                    return
            except Exception as e:
                logger.warning(f"Could not validate menu option {pressed_id}: {e}")

            try:
                from backend.services import flow_runner
                flow_name = flow_runner.flow_for_button(wa_id, pressed_id)
                if flow_name:
                    outcome = flow_runner.start_flow(wa_id, flow_name)
                    if outcome.get("handled") and outcome.get("messages"):
                        for msg in outcome["messages"]:
                            if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                                send_whatsapp_message(wa_id, msg)
                        reply_text = "\n".join(outcome["messages"])
                        save_chat(wa_id, sender_name, user_text, reply_text, "flow")
                        await log_outgoing_message(wa_id, reply_text, "text")
                        logger.info(f"FLOW_STARTED | {wa_id} | button={pressed_id} | "
                                    f"flow={outcome.get('flow')}")
                        response_time_ms = int((time.time() - start_time) * 1000)
                        log_webhook("outgoing", "/webhook/flow", json.dumps({
                            "to": wa_id, "button_id": pressed_id, "flow": outcome.get("flow")
                        }), 200, f"Flow {outcome.get('flow')} started",
                            response_time_ms=response_time_ms)
                        return
            except Exception as e:
                logger.error(f"Profile flow start failed for button {pressed_id}: {e}")

        # ── PROFILE-DEFINED INFORMATIONAL PANELS (Phase 3) ────────────
        # A tapped menu row whose profile entry names an intent (Technologies,
        # Portfolio, Careers, Benefits...) answers from the tenant's own
        # configured text. Only a found answer consumes the tap — everything
        # else falls through to the pipeline below unchanged.
        if pressed_id:
            try:
                from backend.services import intent_answers
                # Menu rows resolve via the profile button's intent field;
                # registry buttons carry the intent name as their id directly.
                panel_answer = (intent_answers.answer_for_button(wa_id, pressed_id, tenant_id)
                                or intent_answers.answer_for_intent(wa_id, pressed_id, tenant_id))
                if panel_answer:
                    if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                        send_whatsapp_message(wa_id, panel_answer)
                    save_chat(wa_id, sender_name, user_text, panel_answer, "intent")
                    await log_outgoing_message(wa_id, panel_answer, "text")
                    logger.info(f"PANEL_REPLY | {wa_id} | button={pressed_id}")
                    response_time_ms = int((time.time() - start_time) * 1000)
                    log_webhook("outgoing", "/webhook/panel", json.dumps({
                        "to": wa_id, "button_id": pressed_id
                    }), 200, f"Panel {pressed_id} answered",
                        response_time_ms=response_time_ms)
                    return
            except Exception as e:
                logger.error(f"Panel answer failed for button {pressed_id}: {e}")

        # ── ROUTE REGISTRY BUTTON PRESSES BY ID ─────────────────────────
        # Buttons generated from the button registry carry a machine id that
        # maps to an implemented action; execute it directly (no LLM).
        button_id, button_title = _extract_button_press(message)
        if button_id and button_id in BUTTON_REGISTRY:
            action = get_action(button_id)
            if action and await _handle_registry_button(wa_id, sender_name, action, start_time):
                response_time_ms = int((time.time() - start_time) * 1000)
                log_webhook("outgoing", "/webhook/button", json.dumps({
                    "to": wa_id, "button_id": button_id
                }), 200, f"Button {button_id} handled", response_time_ms=response_time_ms)
                return

        # Log incoming message to company API
        await log_incoming_message(wa_id, user_text, msg_type)

        response = await process_message(user_text, wa_id, raw_message=message, tenant_id=tenant_id)
        response_text = response.get("answer", "")

        # Log outgoing response to company API
        await log_outgoing_message(wa_id, response_text, msg_type)
        media_url = response.get("media_url")
        media_type = response.get("media_type")
        whatsapp_sent = response.get("whatsapp_sent", False)
        route = response.get("query_type", "faq")
        interactive = response.get("interactive")
        logger.info(f"process_message returned: media_url={media_url}, media_type={media_type}, whatsapp_sent={whatsapp_sent}")
        save_chat(wa_id, sender_name, user_text, response_text, route)

        # Media (image/video/audio/document) is no longer sent to customers.
        # Strip any media payload and any "View/Download Document" button so no
        # branch below attempts to send a file or image (those sends fail with
        # 503 anyway); replies always go out as text buttons/text.
        if media_type:
            media_url = None
            media_type = None
        if isinstance(interactive, dict) and interactive.get("buttons"):
            kept = [
                b for b in interactive["buttons"]
                if (b.get("reply") or {}).get("id") != DOCUMENT_BUTTON_ID
            ]
            interactive = {"type": "button", "buttons": kept} if kept else None

        send_status = "skipped"
        if whatsapp_sent:
            send_status = "sent_by_kb_bot"
            logger.info(f"KB bot already sent interactive reply to {wa_id}")
        elif config.SEND2_USERNAME and config.SEND2_PASSWORD:
            is_direct = is_direct_media_query(user_text)

            if is_direct and config.SEND_MEDIA:
                # Catalogue / new-arrival / product-list query. In
                # CATALOG_DELIVERY_MODE=products (default), `process_message`
                # already populated `interactive` with a native WhatsApp list
                # payload — let the list branch below handle it. In legacy
                # CATALOG_DELIVERY_MODE=pdf, fall back to the text+button
                # summary so we still send *something* useful.
                if interactive and interactive.get("type") == "list" and interactive.get("sections"):
                    list_sent = send_whatsapp_list_menu(
                        wa_id,
                        interactive.get("header", ""),
                        interactive.get("body", "") or response_text,
                        interactive.get("button_text") or interactive.get("button", "Menu"),
                        interactive.get("sections", []),
                        interactive.get("footer", ""),
                    )
                    if response_text and not interactive.get("body"):
                        send_whatsapp_message(wa_id, response_text)
                    send_status = "sent_list" if list_sent else "failed_list"
                    logger.info(f"CATALOG_LIST_SENT | {wa_id}")
                else:
                    summary = build_catalog_text_fallback(user_text)
                    if summary:
                        sent = send_whatsapp_interactive(wa_id, summary["text"], summary["buttons"])
                        send_status = "sent_catalog_summary" if sent else "sent_catalog_summary_failed"
                        logger.info(f"CATALOG_SUMMARY_SENT | {wa_id}")
                        if not sent and summary.get("text"):
                            send_whatsapp_message(wa_id, summary["text"])
                            send_status = "sent_catalog_summary_text"
                    elif response_text:
                        send_whatsapp_message(wa_id, response_text)
                        send_status = "sent"
            elif interactive and interactive.get("type") == "button" and interactive.get("buttons"):
                buttons = interactive["buttons"]
                sent = send_whatsapp_interactive(wa_id, response_text, buttons)
                send_status = "sent_interactive" if sent else "failed_interactive"
                logger.info(f"Interactive button reply {'sent' if sent else 'failed'} to {wa_id}")
                if not sent:
                    if media_url and media_type:
                        media_url = _resolve_media_url(media_url)
                        media_type = _normalize_msg_type(media_type)
                        media_sent = send_whatsapp_message(wa_id, media_url, media_type)
                        if media_sent:
                            send_status = "sent_media_fallback"
                        else:
                            send_whatsapp_message(wa_id, response_text)
                            send_status = "sent_text_fallback"
                    else:
                        send_whatsapp_message(wa_id, response_text)
                        send_status = "sent_text_fallback"
                    logger.info(f"Fallback after interactive fail: {send_status} to {wa_id}")
            elif interactive and interactive.get("type") == "list" and interactive.get("sections"):
                if response_text:
                    send_whatsapp_message(wa_id, response_text)
                list_sent = send_whatsapp_list_menu(
                    wa_id,
                    interactive.get("header", ""),
                    interactive.get("body", ""),
                    interactive.get("button_text") or interactive.get("button", "Menu"),
                    interactive.get("sections", []),
                    interactive.get("footer", ""),
                )
                send_status = "sent_list" if list_sent else "failed_list"
                logger.info(f"Interactive list reply {'sent' if list_sent else 'failed'} to {wa_id}")
            elif config.SEND_MEDIA and media_url and media_type:
                media_url = _resolve_media_url(media_url)
                media_type = _normalize_msg_type(media_type)
                send_whatsapp_message(wa_id, response_text)
                media_sent = send_whatsapp_message(wa_id, media_url, media_type)
                send_status = "sent_media" if media_sent else "failed_media"
            else:
                send_whatsapp_message(wa_id, response_text)
                send_status = "sent"
        else:
            logger.info("SEND2 credentials not set - reply skipped (check .env)")

        response_time_ms = int((time.time() - start_time) * 1000)
        log_webhook("outgoing", "/webhook/reply", json.dumps({
            "to": wa_id, "response": response_text
        }), 200, f"Reply {send_status} to {sender_name}", response_time_ms=response_time_ms)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        response_time_ms = int((time.time() - start_time) * 1000)
        log_webhook("incoming", "/webhook", json.dumps({"message_id": msg_id, "error": str(e)}), 500, f"Error: {e}", response_time_ms=response_time_ms)


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    logger.info(f"Webhook verification request: mode={hub_mode}, token={hub_verify_token}")
    log_webhook("incoming", "/webhook/verify", json.dumps({
        "hub_mode": hub_mode, "hub_verify_token": hub_verify_token, "hub_challenge": hub_challenge
    }), None, "Meta verification ping")

    if hub_mode == "subscribe" and hub_verify_token == config.WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        log_webhook("outgoing", "/webhook/verify", hub_challenge, 200, "Verification OK - returned challenge")
        return PlainTextResponse(content=str(hub_challenge))

    logger.warning(f"Webhook verification FAILED: mode={hub_mode}, token={hub_verify_token}")
    log_webhook("outgoing", "/webhook/verify", "Verification failed", 403, "Token mismatch")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    raw_payload = body.decode("utf-8", errors="replace")
    logger.info(f"Incoming webhook payload ({len(raw_payload)} bytes)")
    log_webhook("incoming", "/webhook", raw_payload[:5000], None, "Raw payload")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON payload: {e}")
        log_webhook("incoming", "/webhook", raw_payload[:2000], 400, f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("object") != "whatsapp_business_account":
        log_webhook("incoming", "/webhook", raw_payload[:2000], 200, f"Ignored non-WABA object: {payload.get('object')}")
        return {"status": "ignored", "object": payload.get("object")}

    entry = payload.get("entry") or [{}]
    changes = (entry[0].get("changes") or [{}])[0]
    value = changes.get("value") or {}

    if "statuses" in value:
        status = value["statuses"][0]
        logger.info(f"Status callback: id={status.get('id')} status={status.get('status')} "
                    f"timestamp={status.get('timestamp')}")
        log_webhook("incoming", "/webhook/status", json.dumps(status), 200,
                    f"Status: {status.get('status')} for msg_id: {status.get('id')}")
        return {"status": "ok", "type": "status"}

    if "messages" not in value:
        log_webhook("incoming", "/webhook", raw_payload[:3000], 200, "No messages or statuses in payload")
        return {"status": "no_messages"}

    message = value["messages"][0]
    contact = (value.get("contacts") or [{}])[0]

    wa_id = contact.get("wa_id", "")
    sender_name = (contact.get("profile") or {}).get("name", "Unknown")
    msg_type = message.get("type", "")
    msg_id = message.get("id", "")

    if msg_type == "text":
        user_text = message["text"]["body"]
    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type", "")
        if interactive_type == "button_reply":
            user_text = interactive.get("button_reply", {}).get("title", "[Button]")
        elif interactive_type == "list_reply":
            user_text = interactive.get("list_reply", {}).get("title", "[List item]")
        else:
            user_text = f"[{msg_type}:{interactive_type}]"
        logger.info(f"Interactive reply: type={interactive_type} text={user_text[:100]}")
    else:
        user_text = f"[{msg_type} message]"

    logger.info(f"Incoming message from {sender_name} ({wa_id}): {user_text[:100]}")
    log_webhook("incoming", "/webhook/message", json.dumps({
        "wa_id": wa_id, "sender_name": sender_name, "type": msg_type,
        "message": user_text, "message_id": msg_id
    }), 200, f"Message from {sender_name}")

    if _is_duplicate(msg_id):
        logger.info(f"Skipping duplicate message {msg_id}")
        return {"status": "ok", "type": "duplicate"}

    # Resolve the owning tenant from the inbound WABA phone-id before the
    # background task, so chat history and state are stamped with it.
    try:
        from shared.tenancy.resolver import resolve_tenant_from_payload
        tenant_id = resolve_tenant_from_payload(payload)
    except Exception as exc:
        logger.warning(f"Tenant resolution failed, using default: {exc}")
        tenant_id = None

    # Campaign consent wins over everything else: a STOP must unsubscribe even
    # mid-flow, and the contact must not get a marketing reply afterwards.
    if _handle_campaign_opt_out(user_text, wa_id, sender_name, tenant_id):
        return {"status": "ok", "type": "campaign_consent"}

    background_tasks.add_task(
        _process_and_reply, wa_id, sender_name, user_text, msg_type, message, msg_id, tenant_id
    )
    return {"status": "ok", "type": "accepted"}
