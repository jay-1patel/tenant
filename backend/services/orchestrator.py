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
import re

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


async def _send_b2c_menu(wa_id: str, tenant_id: str = None):
    """Send active tenant's published profile menu using Smart Switch (Buttons <=3, List >3)."""
    from bots.customer_b2c import menus
    from services.whatsapp_sender import send_list_menu, send_button_message

    menu_payload = menus.get_main_menu(wa_id, tenant_id=tenant_id)
    if menu_payload.get("type") == "buttons":
        await send_button_message(
            wa_id,
            body=menu_payload.get("text", "Options"),
            buttons=menu_payload.get("buttons", []),
        )
    else:
        await send_list_menu(
            wa_id,
            header=menu_payload.get("header", ""),
            body=menu_payload.get("body", "What would you like to explore today?"),
            button_text=menu_payload.get("button_text", "Show Options"),
            sections=menu_payload.get("sections", []),
        )


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

    # A new inbound message reopens a conversation that was previously resolved,
    # so it reappears in the live inbox instead of staying hidden forever.
    try:
        from database import reopen_conversation_on_inbound
        reopen_conversation_on_inbound(wa_id)
    except Exception as exc:
        logger.debug(f"Could not reopen conversation for {wa_id}: {exc}")

    with get_db_context() as conn:
        # 1. Check Human Handover first (Global rule)
        user_state = conn.execute(
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

        # ── Single-Number Testing Mode: WhatsApp in-chat tenant switcher ──
        msg_lower = (message or "").strip().lower()
        if msg_lower in ("#tenants", "#switch", "#tenant", "#testbot"):
            from shared.tenancy import store
            from database import get_active_test_tenant
            current_active = get_active_test_tenant() or tenant_id
            all_tenants = store.list_tenants()
            lines = [
                "🧪 *WhatsApp Tenant Switcher (Single-Number Testing)*",
                f"Current Active: *{current_active}*",
                "",
                "Available tenants to test:",
            ]
            for idx, t in enumerate(all_tenants, 1):
                t_name = t.get("display_name") or t.get("company_name") or t.get("slug")
                t_slug = t.get("slug") or str(t.get("id"))
                t_vert = t.get("vertical", "generic")
                active_marker = " 🟢 (ACTIVE)" if (t_slug == current_active or str(t.get("id")) == str(current_active)) else ""
                lines.append(f"{idx}️⃣ *{t_name}* (`{t_slug}`){active_marker}\n   Vertical: _{t_vert}_\n   Switch: `#tenant {t_slug}` or `#tenant {idx}`")
            lines.append("\n👉 Reply with `#tenant <name/number>` to switch instantly!")
            await send_text_message(wa_id, "\n".join(lines))
            return {
                "status": "processed",
                "messages": drain_captured(),
                "new_state": None,
                "human_handover": False,
                "user_type": "b2c",
                "error": None,
            }

        if msg_lower in ("#info", "#status", "#whoami"):
            from database import get_active_test_tenant
            from shared.tenancy.loader import get_tenant_profile
            from shared.tenancy.resolver import resolve_tenant_for_user
            current_active = get_active_test_tenant() or resolve_tenant_for_user(wa_id) or tenant_id or "default"
            prof = get_tenant_profile(current_active)
            brand_name = prof.brand.name if (prof and prof.brand and prof.brand.name) else current_active
            tagline = prof.brand.tagline if (prof and prof.brand and prof.brand.tagline) else "Multi-tenant Chatbot"
            buttons_count = len(prof.menu.buttons) if (prof and prof.menu and prof.menu.buttons) else 0
            menu_mode = "⚡ Quick Reply Buttons (<=3)" if 1 <= buttons_count <= 3 else "📋 WhatsApp List Drawer (>3)"

            chunk_count = 0
            try:
                with get_db_context() as conn:
                    row = conn.execute("SELECT COUNT(*) as c FROM knowledge_base WHERE tenant_id=?", (current_active,)).fetchone()
                    chunk_count = row[0] if row else 0
            except Exception:
                pass

            info_lines = [
                f"🏢 *Tenant Profile: {brand_name}*",
                f"• *Tenant ID / Slug:* `{current_active}`",
                f"• *Tagline:* {tagline}",
                f"• *Menu Mode:* {menu_mode} ({buttons_count} options)",
                f"• *Indexed Knowledge Chunks:* {chunk_count}",
                "",
                "💡 *Testing Commands:*",
                "• `#tenants` - List all testable tenants",
                "• `#tenant <name>` - Switch active tenant",
                "• `#menu` - Resend active tenant menu",
                "• `#info` - Show this tenant diagnostic",
            ]
            await send_text_message(wa_id, "\n".join(info_lines))
            return {
                "status": "processed",
                "messages": drain_captured(),
                "new_state": None,
                "human_handover": False,
                "user_type": "b2c",
                "error": None,
            }

        if msg_lower == "#menu":
            flow_runner.clear_flow(wa_id)
            with get_db_context() as conn:
                conn.execute(
                    "UPDATE user_states SET state = 'B2C_MAIN_MENU', context_json = '{}', updated_at = CURRENT_TIMESTAMP WHERE wa_id = ?",
                    (wa_id,),
                )
            await _send_b2c_menu(wa_id, tenant_id=tenant_id)
            return {
                "status": "processed",
                "messages": drain_captured(),
                "new_state": "B2C_MAIN_MENU",
                "human_handover": False,
                "user_type": "b2c",
                "error": None,
            }

        if msg_lower.startswith(("#tenant ", "#switch ")):
            from database import set_active_test_tenant
            from shared.tenancy import store
            parts = message.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            all_tenants = store.list_tenants()
            matched = None
            if target.isdigit():
                num = int(target)
                if 1 <= num <= len(all_tenants):
                    matched = all_tenants[num - 1]
            if not matched:
                for t in all_tenants:
                    s = str(t.get("slug") or "").lower()
                    i = str(t.get("id") or "").lower()
                    name = str(t.get("display_name") or t.get("company_name") or "").lower()
                    vert = str(t.get("vertical") or "").lower()
                    t_target = target.lower()
                    if (
                        t_target in (s, i)
                        or t_target in name
                        or t_target in vert
                        or (t_target == "bank" and "bank" in s)
                        or (t_target in ("travel", "tour") and "wanderly" in s)
                        or (t_target in ("finance", "capital") and "northwind" in s)
                        or (t_target in ("it", "tech", "software") and "leeway" in s)
                        or (t_target in ("shop", "snack", "food") and "troo" in s)
                        or (t_target in ("realestate", "real_estate", "property", "realty", "skyline") and "skyline" in s)
                    ):
                        matched = t
                        break

            if matched:
                chosen_id = matched.get("slug") or str(matched.get("id"))
                set_active_test_tenant(chosen_id)
                disp = matched.get("display_name") or matched.get("company_name") or chosen_id
                vert = matched.get("vertical", "generic")
                await send_text_message(
                    wa_id,
                    f"✅ *Active Tenant Switched!*\nNow testing: *{disp}* ({vert})\nAll incoming messages are now routed to this tenant."
                )
                await _send_b2c_menu(wa_id, tenant_id=chosen_id)
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": "B2C_MAIN_MENU",
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }
            else:
                await send_text_message(
                    wa_id,
                    f"❌ Tenant '{target}' not found. Send `#tenants` to see the full list of available tenants."
                )
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": None,
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }

        # 0. Check Main Menu & Cancel triggers
        clean_btn = (message or "").strip().lower()
        clean_btn = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", clean_btn).strip()
        is_menu_cmd = (
            clean_btn in ("main menu", "menu", "show options", "options", "start", "hi", "hello", "hey", "restart", "start over")
            or message in ("main_menu", "menu_main", "menu_start")
        )
        is_cancel_cmd = clean_btn in (
            "cancel", "stop", "exit", "quit", "abort", "back", "home", "leave", "close", "nevermind", "never mind"
        )

        if is_menu_cmd or is_cancel_cmd:
            flow_runner.clear_flow(wa_id)
            with get_db_context() as conn:
                conn.execute(
                    "UPDATE user_states SET state = 'B2C_MAIN_MENU', context_json = '{}', updated_at = CURRENT_TIMESTAMP WHERE wa_id = ?",
                    (wa_id,),
                )
            if is_cancel_cmd:
                await send_text_message(
                    wa_id,
                    "Okay, I've cancelled that. Type *menu* anytime to see options, or feel free to ask any question! 🙏"
                )
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": "B2C_MAIN_MENU",
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }
            else:
                await _send_b2c_menu(wa_id, tenant_id=tenant_id)
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": "B2C_MAIN_MENU",
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }

        # If user clicked a menu or action button, clear any stale flow & state first
        if message and (message.startswith(("menu_", "b2c_", "flow:", "flow_")) or clean_btn.startswith("menu_")):
            flow_runner.clear_flow(wa_id)
            with get_db_context() as conn:
                conn.execute(
                    "UPDATE user_states SET state = 'B2C_MAIN_MENU', context_json = '{}', updated_at = CURRENT_TIMESTAMP WHERE wa_id = ?",
                    (wa_id,),
                )
            user_state = ("B2C_MAIN_MENU", "{}")

        # 1. If user is currently running a flow, advance the flow with their reply
        if flow_runner.is_running(wa_id):
            outcome = flow_runner.handle_reply(wa_id, message, tenant_id=tenant_id)
            if outcome and outcome.get("handled"):
                if outcome.get("messages"):
                    from services.whatsapp_sender import send_button_message
                    for msg in outcome["messages"]:
                        if isinstance(msg, dict) and msg.get("type") == "buttons":
                            await send_button_message(wa_id, msg.get("text", ""), msg.get("buttons", []))
                        else:
                            await send_text_message(wa_id, msg)
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": user_state[0] if user_state else None,
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }
            # If outcome was not handled (user asked a question / broke flow),
            # clear any leftover state and allow fall-through to answer question directly!
            if outcome and not outcome.get("handled"):
                flow_runner.clear_flow(wa_id)
                with get_db_context() as conn:
                    conn.execute(
                        "UPDATE user_states SET state = 'B2C_MAIN_MENU', context_json = '{}', updated_at = CURRENT_TIMESTAMP WHERE wa_id = ?",
                        (wa_id,),
                    )
                user_state = ("B2C_MAIN_MENU", "{}")

        # 2. Check flow trigger for button ID or typed text (e.g. 'book a callback', 'schedule meeting')
        flow_name = (
            flow_runner.flow_for_button(wa_id, message, tenant_id=tenant_id)
            or flow_runner.flow_for_text(wa_id, message, tenant_id=tenant_id)
        )
        if flow_name:
            outcome = flow_runner.start_flow(wa_id, flow_name, tenant_id=tenant_id)
            if outcome.get("handled") and outcome.get("messages"):
                from services.whatsapp_sender import send_button_message
                for msg in outcome["messages"]:
                    if isinstance(msg, dict) and msg.get("type") == "buttons":
                        await send_button_message(wa_id, msg.get("text", ""), msg.get("buttons", []))
                    else:
                        await send_text_message(wa_id, msg)
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": outcome.get("new_state", "B2C_MAIN_MENU"),
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
            from routing.button_actions import get_contextual_buttons
            from services.whatsapp_sender import send_button_message
            buttons = get_contextual_buttons(message, tenant_id=tenant_id, wa_id=wa_id, limit=3)
            if buttons:
                await send_button_message(wa_id, synthesized, buttons)
            else:
                await send_text_message(wa_id, synthesized)
            return {
                "status": "processed",
                "messages": drain_captured(),
                "new_state": "B2C_MAIN_MENU",
                "human_handover": False,
                "user_type": "b2c",
                "error": None,
            }

        # Check service query
        if service_answers.is_service_query(message):
            service_reply = service_answers.answer_for_text(wa_id, message, tenant_id=tenant_id)
            if service_reply:
                from faq.service import synthesize_intent_answer
                synthesized = await synthesize_intent_answer(
                    raw_content=service_reply,
                    intent_name="Services",
                    user_query=message,
                    tenant_id=tenant_id,
                )
                from routing.button_actions import get_contextual_buttons
                from services.whatsapp_sender import send_button_message
                buttons = get_contextual_buttons("services", tenant_id=tenant_id, wa_id=wa_id, limit=3)
                if buttons:
                    await send_button_message(wa_id, synthesized, buttons)
                else:
                    await send_text_message(wa_id, synthesized)
                return {
                    "status": "processed",
                    "messages": drain_captured(),
                    "new_state": "B2C_MAIN_MENU",
                    "human_handover": False,
                    "user_type": "b2c",
                    "error": None,
                }
    except Exception as exc:
        logger.debug(f"Tenant profile intent routing fallback for {wa_id}: {exc}")

    # 2. Determine User Type (B2B vs B2C)
    with get_db_context() as conn:
        is_distributor = conn.execute(
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

        with get_db_context() as conn:
            if user_state:
                # Update only state/context; preserve human_handover and lang.
                conn.execute(
                    "UPDATE user_states SET state=?, context_json=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE wa_id=?",
                    (new_state, json.dumps(updated_context), wa_id),
                )
            else:
                conn.execute(
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
