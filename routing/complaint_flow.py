"""Multi-step WhatsApp complaint form.

When a user types "raise complaint" (or taps the "Raise a Complaint" button)
the chatbot walks them through a short form:

    1. Complaint type        -> COMPLAINT_AWAITING_TYPE
    2. Subject               -> COMPLAINT_AWAITING_SUBJECT
    3. Detailed description  -> COMPLAINT_AWAITING_DESC  (submitted here)

The final step inserts a row into the ``complaints`` table so agents can
review and resolve it from the admin panel.

State / context is stored in ``user_states`` (state + context_json), the same
mechanism used by the B2B/B2C orchestrators, so everything survives restarts.
"""

import logging
from datetime import datetime

import routing.config as config
from routing.whatsapp import send_whatsapp_message, send_whatsapp_interactive

logger = logging.getLogger("chiki_webhook")

COMPLAINT_AWAITING_TYPE = "COMPLAINT_AWAITING_TYPE"
COMPLAINT_AWAITING_SUBJECT = "COMPLAINT_AWAITING_SUBJECT"
COMPLAINT_AWAITING_DESC = "COMPLAINT_AWAITING_DESC"

COMPLAINT_STATES = {
    COMPLAINT_AWAITING_TYPE,
    COMPLAINT_AWAITING_SUBJECT,
    COMPLAINT_AWAITING_DESC,
}

MAIN_MENU_STATE = "MAIN_MENU"

# Phrases that start a new complaint form.
COMPLAINT_START_PHRASES = [
    "raise complaint", "file a complaint", "register complaint",
    "complaint form", "raise a complaint", "complaint", "complain",
    "shikayat", "want to complain",
]

CANCEL_PHRASES = ["cancel", "cancel form", "exit", "quit", "stop", "never mind", "cancel complaint"]

# Button-friendly complaint types (max 20 chars each).
COMPLAINT_TYPE_BUTTONS = [
    {"id": "cmp_type_damaged", "title": "Damaged Product"},
    {"id": "cmp_type_wrong_item", "title": "Wrong Item"},
    {"id": "cmp_type_delivery", "title": "Delivery Issue"},
    {"id": "cmp_type_other", "title": "Other"},
]

_TYPE_ALIASES = {
    "damaged": "Damaged Product",
    "damage": "Damaged Product",
    "broken": "Damaged Product",
    "cracked": "Damaged Product",
    "defective": "Damaged Product",
    "leak": "Damaged Product",
    "wrong item": "Wrong Item",
    "wrong product": "Wrong Item",
    "wrong order": "Wrong Item",
    "incorrect item": "Wrong Item",
    "incorrect product": "Wrong Item",
    "not what i ordered": "Wrong Item",
    "delivery": "Delivery Issue",
    "shipping": "Delivery Issue",
    "late delivery": "Delivery Issue",
    "delayed": "Delivery Issue",
    "not delivered": "Delivery Issue",
    "delivery issue": "Delivery Issue",
    "billing": "Billing & Payment",
    "payment": "Billing & Payment",
    "bill": "Billing & Payment",
    "charged": "Billing & Payment",
    "price": "Billing & Payment",
    "refund": "Refund & Return",
    "return": "Refund & Return",
    "replacement": "Refund & Return",
    "quality": "Product Quality",
    "expired": "Product Quality",
    "stale": "Product Quality",
    "taste": "Product Quality",
    "other": "Other",
}

_WELCOME_MSG = (
    "Sorry to hear that! Let me register your complaint. 🙏\n\n"
    "Please select the *type* of complaint:"
)

_SUBJECT_MSG = (
    "Got it! Now please share a short *subject* for your complaint "
    "(e.g. \"Order #1234 arrived broken\")."
)

_DESC_MSG = (
    "Thanks! Lastly, please *describe the issue in detail* so our team can "
    "help you as quickly as possible."
)

_CANCEL_MSG = "No problem! Your complaint form was cancelled. Anything else I can help with? 😊"

_CANCEL_HINT = "\n\nType *cancel* anytime to stop."


def is_complaint_start(text: str) -> bool:
    """Return True if the message should start a new complaint form."""
    lowered = (_strip_brackets(text) or "").lower().strip()
    if not lowered:
        return False
    return any(phrase in lowered for phrase in COMPLAINT_START_PHRASES)


def is_awaiting_admin_reply(wa_id: str) -> bool:
    """Return True when an agent asked the customer for more information on a complaint.

    When this is active the webhook parks the customer's messages for the agent
    (saved to chat_history only, no bot reply) so the agent's follow-up in the
    Live Inbox proceeds cleanly. Becomes False again once the agent resolves or
    closes the complaint.
    """
    from database import get_db_context

    try:
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT 1 FROM complaints "
                "WHERE wa_id = ? AND status = 'awaiting_info' "
                "ORDER BY created_at DESC LIMIT 1",
                (wa_id,),
            ).fetchone()
        return row is not None
    except Exception:
        return False


def _strip_brackets(text: str) -> str:
    """Remove the [Button]/[List item] decoration webhook adds to interactive replies."""
    if not text:
        return text
    if text.startswith("[") and "]" in text:
        inner = text[text.find("]") + 1:].strip()
        if inner:
            return inner
    return text


def _match_complaint_type(text: str) -> str | None:
    """Map the user's selection/typed text to a canonical complaint type."""
    lowered = (_strip_brackets(text) or "").lower().strip()
    if not lowered:
        return None
    for alias, canonical in _TYPE_ALIASES.items():
        if alias in lowered:
            return canonical
    return None


def _buttons():
    return [
        {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
        for b in COMPLAINT_TYPE_BUTTONS
    ]


def _send(to: str, text: str) -> None:
    if config.SEND2_USERNAME and config.SEND2_PASSWORD:
        send_whatsapp_message(to, text)


def start_complaint(wa_id: str) -> None:
    """Begin the complaint form: set the FSM state and ask for the type."""
    from database import set_user_state
    set_user_state(wa_id, COMPLAINT_AWAITING_TYPE, {})
    _send(wa_id, _WELCOME_MSG + _CANCEL_HINT)
    if config.SEND2_USERNAME and config.SEND2_PASSWORD:
        send_whatsapp_interactive(wa_id, "Select complaint type:", _buttons())


def handle_complaint_state(wa_id: str, user_text: str) -> bool:
    """Handle the next message while a complaint form is in progress.

    Returns True when the message was consumed by the form, False otherwise.
    """
    from database import get_user_state, set_user_state

    state_row = get_user_state(wa_id)
    state = state_row.get("state", MAIN_MENU_STATE)
    if state not in COMPLAINT_STATES:
        return False

    context = state_row.get("context_json") or {}
    text = (_strip_brackets(user_text) or "").strip()

    # ── Cancel ──────────────────────────────────────────────────────────
    if text.lower() in CANCEL_PHRASES:
        set_user_state(wa_id, MAIN_MENU_STATE, {})
        _send(wa_id, _CANCEL_MSG)
        logger.info(f"COMPLAINT_CANCELLED | {wa_id}")
        return True

    if not text:
        _send(wa_id, "Please type your answer, or type *cancel* to stop the form. 🙏")
        return True

    # ── Step 1: complaint type ───────────────────────────────────────────
    if state == COMPLAINT_AWAITING_TYPE:
        ctype = _match_complaint_type(text)
        if not ctype:
            _send(wa_id, "I didn't catch that. Please select one of the options above:")
            if config.SEND2_USERNAME and config.SEND2_PASSWORD:
                send_whatsapp_interactive(wa_id, "Select complaint type:", _buttons())
            return True
        context["complaint_type"] = ctype
        set_user_state(wa_id, COMPLAINT_AWAITING_SUBJECT, context)
        _send(wa_id, _SUBJECT_MSG + _CANCEL_HINT)
        logger.info(f"COMPLAINT_STEP | {wa_id} | type={ctype}")
        return True

    # ── Step 2: subject ──────────────────────────────────────────────────
    if state == COMPLAINT_AWAITING_SUBJECT:
        context["complaint_subject"] = text
        set_user_state(wa_id, COMPLAINT_AWAITING_DESC, context)
        _send(wa_id, _DESC_MSG + _CANCEL_HINT)
        logger.info(f"COMPLAINT_STEP | {wa_id} | subject={text[:80]}")
        return True

    # ── Step 3: description -> submit ────────────────────────────────────
    if state == COMPLAINT_AWAITING_DESC:
        ticket_id = _insert_complaint(wa_id, context, text)
        set_user_state(wa_id, MAIN_MENU_STATE, {})
        reply = (
            f"✅ *Complaint registered successfully!*\n\n"
            f"📋 *Ticket ID:* {ticket_id}\n"
            f"🏷️ *Type:* {context.get('complaint_type', 'Other')}\n"
            f"📝 *Subject:* {context.get('complaint_subject', '-')[:80]}\n\n"
            f"Our team will review your complaint and get back to you soon. 🙏\n"
            f"For anything urgent, contact support."
        )
        _send(wa_id, reply)
        logger.info(f"COMPLAINT_SUBMITTED | {wa_id} | ticket={ticket_id} | type={context.get('complaint_type')}")
        return True
    return False


def _insert_complaint(wa_id: str, context: dict, description: str) -> str:
    """Insert a complaint row and return the ticket id."""
    from database import get_db_context, get_request_tenant, _resolve_tenant

    now = datetime.utcnow()
    ticket_id = f"TCK-{now.strftime('%Y%m%d%H%M%S')}"
    ctype = context.get("complaint_type") or "Other"
    subject = context.get("complaint_subject") or ctype
    tenant_id = get_request_tenant() or _resolve_tenant()

    with get_db_context() as conn:
        conn.execute(
            "INSERT INTO complaints (ticket_id, wa_id, complaint_type, description, "
            "status, priority, subject, updated_at, created_at, tenant_id) "
            "VALUES (?, ?, ?, ?, 'open', 'normal', ?, ?, ?, ?)",
            (
                ticket_id, wa_id, ctype, description or "",
                subject, now.isoformat(), now.isoformat(), tenant_id,
            ),
        )
    return ticket_id