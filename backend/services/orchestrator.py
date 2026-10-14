"""
Unified orchestrator.

The main entry point for incoming WhatsApp messages. This module acts as a
router: based on the user type (B2B distributor vs B2C customer) it delegates
to the correct modular persona workflow and persists the resulting FSM state.

Shared infrastructure (WhatsApp sender, database context, RAG) is reused —
no duplication here.

This function captures every outgoing message via services.whatsapp_sender.
Callers can request capture-only mode when they own outbound delivery.
"""

import json
import logging

from database import get_db_context
from services.whatsapp_sender import begin_capture, drain_captured, end_capture

logger = logging.getLogger("orchestrator")


async def process_incoming_message(
    wa_id: str, message: str, *, capture_only: bool = False
) -> dict:
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
    capture_tokens = begin_capture(capture_only=capture_only)

    try:
        return await _process_captured_message(wa_id, message)
    finally:
        end_capture(capture_tokens)


async def _process_captured_message(wa_id: str, message: str) -> dict:
    # Customer directory: whoever talks to the bot gets a record on their very
    # first message, whichever channel delivered it (Meta webhook, send2 push,
    # or the send2 poller). Keyed on (tenant_id, wa_id) so nobody is duplicated
    # and later messages only refresh the row. Runs before the handover early
    # return below, so an agent-handled chat still registers the contact.
    try:
        from database import get_request_tenant, set_request_tenant, _resolve_tenant, touch_customer
        effective_tenant = get_request_tenant() or _resolve_tenant()
        set_request_tenant(effective_tenant)
        touch_customer(effective_tenant, wa_id, "")
    except Exception as exc:
        logger.debug(f"Could not touch customer {wa_id}: {exc}")

    with get_db_context() as db:
        # 1. Check Human Handover first (Global rule)
        user_state = db.execute(
            "SELECT state, context_json, human_handover FROM user_states WHERE wa_id=?",
            (wa_id,),
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

        # 1b. Check Tenant Profile Intents, Flows, and Services
        try:
            from shared.tenancy.resolver import resolve_tenant_for_user
            try:
                from services import intent_answers, flow_runner, service_answers
            except ImportError:
                from backend.services import intent_answers, flow_runner, service_answers
            from services.whatsapp_sender import send_text_message

            tenant_id = resolve_tenant_for_user(wa_id)

            # 1. If user is currently running a flow, advance the flow with their reply
            if flow_runner.is_running(wa_id):
                outcome = flow_runner.handle_reply(wa_id, message, tenant_id=tenant_id)
                if outcome and outcome.get("handled"):
                    if outcome.get("messages"):
                        for msg in outcome["messages"]:
                            await send_text_message(wa_id, msg)
                    return {
                        "status": "processed",
                        "messages": drain_captured(),
                        "new_state": user_state[0] if user_state else None,
                        "human_handover": False,
                        "user_type": "b2c",
                        "error": None,
                    }

            # 2. Check flow trigger for button ID or typed text (e.g. 'book a callback', 'schedule meeting')
            flow_name = (
                flow_runner.flow_for_button(wa_id, message, tenant_id=tenant_id)
                or flow_runner.flow_for_text(wa_id, message, tenant_id=tenant_id)
            )
            if flow_name:
                outcome = flow_runner.start_flow(wa_id, flow_name, tenant_id=tenant_id)
                if outcome.get("handled") and outcome.get("messages"):
                    for msg in outcome["messages"]:
                        await send_text_message(wa_id, msg)
                    return {
                        "status": "processed",
                        "messages": drain_captured(),
                        "new_state": outcome.get("new_state", user_state[0] if user_state else None),
                        "human_handover": False,
                        "user_type": "b2c",
                        "error": None,
                    }

            # 3. Check intent by button ID, menu row title, or typed text (Careers, Technologies, Projects, Benefits, etc.)
            # Resolve the raw answer (intent or button) and synthesize it via the LLM
            intent_reply = (
                intent_answers.answer_for_button(wa_id, message, tenant_id=tenant_id)
                or intent_answers.answer_for_menu_title(wa_id, message, tenant_id=tenant_id)
                or intent_answers.answer_for_intent(wa_id, message, tenant_id=tenant_id)
                or intent_answers.answer_for_text(wa_id, message, tenant_id=tenant_id)
            )
            if intent_reply:
                from faq.service import synthesize_intent_answer
                synthesized = await synthesize_intent_answer(
                    raw_content=intent_reply,
                    intent_name=message,
                    user_query=message,
                    tenant_id=tenant_id,
                )
                await send_text_message(wa_id, synthesized)
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": user_state[0] if user_state else None,
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }

            # Check service query
            if service_answers.is_service_query(message):
                service_reply = service_answers.answer_for_text(wa_id, message, tenant_id=tenant_id)
                if service_reply:
                    # Services are stored as structured DB rows; pass them
                    # through the LLM (Ollama) like every other answer instead
                    # of replying with the raw stored text.
                    from faq.service import synthesize_intent_answer
                    synthesized = await synthesize_intent_answer(
                        raw_content=service_reply,
                        intent_name="Services",
                        user_query=message,
                        tenant_id=tenant_id,
                    )
                    await send_text_message(wa_id, synthesized)
                    return {
                        "status": "processed",
                        "messages": drain_captured(),
                        "new_state": user_state[0] if user_state else None,
                        "human_handover": False,
                        "user_type": "b2c",
                        "error": None,
                    }
        except Exception as exc:
            logger.debug(f"Tenant profile intent routing fallback for {wa_id}: {exc}")

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
                    "WHERE wa_id=?",
                    (new_state, json.dumps(updated_context), wa_id),
                )
            else:
                db.execute(
                    "INSERT INTO user_states (wa_id, state, context_json, lang, updated_at) "
                    "VALUES (?, ?, ?, 'en', CURRENT_TIMESTAMP)",
                    (wa_id, new_state, json.dumps(updated_context)),
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
