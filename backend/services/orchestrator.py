"""
Unified orchestrator.

The main entry point for incoming WhatsApp messages. This module acts as a
router: based on the user type (B2B distributor vs B2C customer) it delegates
to the correct modular persona workflow and persists the resulting FSM state.

Shared infrastructure (WhatsApp sender, database context, RAG) is reused —
no duplication here.

This function captures every outgoing message (via services.whatsapp_sender
capture mode) so the caller (e.g. services.incoming_listener) can retrieve and
send exactly what would be shown to a real WhatsApp connection.
"""

import json
import logging

from database import get_db_context
from services.whatsapp_sender import begin_capture, drain_captured

logger = logging.getLogger("orchestrator")


async def process_incoming_message(wa_id: str, message: str) -> dict:
    """Route a single incoming message through the correct persona workflow.

    Returns a dict describing the outcome:
        {
            "messages": [ {type: text|buttons|list, ...}, ... ],
            "new_state": str | None,
            "human_handover": bool,
            "user_type": "b2b" | "b2c" | None,
            "status": "processed" | "ignored" | "error",
            "error": str | None,
        }
    """
    # Capture every outgoing message produced while processing this message.
    begin_capture()

    with get_db_context() as db:
        # 1. Check Human Handover first (Global rule)
        from database import get_request_tenant, _resolve_tenant
        tid = get_request_tenant() or _resolve_tenant()
        user_state = db.execute(
            "SELECT state, context_json, human_handover FROM user_states WHERE tenant_id=? AND wa_id=?",
            (tid, wa_id),
        ).fetchone()
        if user_state and user_state[2] == 1:  # human_handover is True
            # Admin is handling it in the React UI; do nothing.
            return {
                "messages": [],
                "new_state": None,
                "human_handover": True,
                "user_type": None,
                "status": "ignored",
                "error": None,
            }

        # 2. Determine User Type (B2B vs B2C)
        is_distributor = db.execute(
            "SELECT 1 FROM distributors WHERE wa_id=?", (wa_id,)
        ).fetchone()

        current_state = user_state[0] if user_state else None
        try:
            context = json.loads(user_state[1]) if user_state and user_state[1] else {}
        except (json.JSONDecodeError, TypeError):
            context = {}

        # 3. Route to correct modular workflow
        if is_distributor:
            from bots.distributor_b2b.workflows import handle_b2b_message
            result = await handle_b2b_message(wa_id, message, current_state, context)
            new_state_prefix = "B2B_"
            user_type = "b2b"
        else:
            from bots.customer_b2c.workflows import handle_b2c_message
            result = await handle_b2c_message(wa_id, message, current_state, context)
            new_state_prefix = "B2C_"
            user_type = "b2c"

        # 4. Update State in DB (real schema uses context_json)
        new_state = current_state
        updated_context = context
        if result and "new_state" in result:
            updated_context = result.get("context", context)
            new_state = result["new_state"]
            if not new_state or not new_state.startswith(new_state_prefix):
                new_state = f"{new_state_prefix}{new_state}" if new_state else current_state

            if user_state:
                # Update only state/context; preserve human_handover and lang.
                db.execute(
                    "UPDATE user_states SET state=?, context_json=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE tenant_id=? AND wa_id=?",
                    (new_state, json.dumps(updated_context), tid, wa_id),
                )
            else:
                db.execute(
                    "INSERT INTO user_states (tenant_id, wa_id, state, context_json, lang, updated_at) "
                    "VALUES (?, ?, ?, ?, 'en', CURRENT_TIMESTAMP)",
                    (tid, wa_id, new_state, json.dumps(updated_context)),
                )

    messages = drain_captured()

    handover = any(m.get("type") == "text" and "human" in (m.get("text") or "").lower()
                   for m in messages)

    return {
        "messages": messages,
        "new_state": new_state,
        "human_handover": handover,
        "user_type": user_type,
        "status": "processed",
        "error": None,
    }
