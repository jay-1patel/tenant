"""B2B Distributor state-machine handler.

This module is the single entry point the orchestrator calls for B2B users:

    async def handle_b2b_message(wa_id, message, state, context, tier=None)

Every return value includes a ``new_state`` key so the orchestrator can persist
the next FSM state into ``user_states``. Cross-module imports (the shared
WhatsApp sender and sibling modules) are performed lazily inside functions to
avoid circular-import crashes at FastAPI startup.

The new order and ticket flows are delegated to ``order_flow`` and
``ticket_flow`` respectively (modular containment: all B2B logic lives under
bots/distributor_b2b/).
"""

import logging
import re

logger = logging.getLogger("b2b_workflows")


def _clean(text: str) -> str:
    """Lowercase and strip emoji so menu titles / list replies match keywords."""
    if not text:
        return ""
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)
    return " ".join((text or "").strip().lower().split())


def _states():
    from . import config
    return config


async def handle_b2b_message(wa_id: str, message: str, state: str, context: dict,
                             tier: str = None) -> dict:
    from services.whatsapp_sender import (
        send_text_message,
        send_button_message,
        send_list_menu,
    )
    from . import tools, menus

    cfg = _states()
    message = (message or "").strip()
    context = context or {}
    tier = (tier or tools.get_distributor_tier(wa_id)).strip() or "Bronze"

    # -- Delegate to the new order FSM --------------------------------------
    if state in {
        cfg.DIST_ORDER_START, cfg.DIST_BROWSE_PRODUCTS, cfg.DIST_SELECT_PRODUCTS,
        cfg.DIST_SET_QUANTITIES, cfg.DIST_REVIEW_ORDER, cfg.DIST_CONFIRM_ORDER,
        cfg.DIST_ASK_NAME, cfg.DIST_ASK_MOBILE, cfg.DIST_ASK_ADDRESS,
    }:
        from . import order_flow
        return await order_flow.handle_order_message(wa_id, message, state, context, tier)

    # -- Delegate to the new ticket FSM -------------------------------------
    if state in {
        cfg.DIST_TICKET_START, cfg.DIST_TICKET_CATEGORY,
        cfg.DIST_TICKET_DETAILS, cfg.DIST_TICKET_CREATED,
    }:
        from . import ticket_flow
        return await ticket_flow.handle_ticket_message(wa_id, message, state, context, tier)

    # -- Delegate to the new catalog FSM ------------------------------------
    if state in {
        cfg.B2B_VIEW_CATALOG, cfg.B2B_VIEW_PRICE_LIST, cfg.B2B_VIEW_SCHEMES,
    }:
        from . import catalog_flow
        return await catalog_flow.handle_catalog_message(wa_id, message, state, context, tier)

    # -- Delegate to the new finance FSM ------------------------------------
    if state in {
        cfg.B2B_AWAITING_PAYMENT_PROOF, cfg.B2B_AWAITING_INVOICE_ORDER_ID,
    }:
        from . import finance_flow
        return await finance_flow.handle_finance_message(wa_id, message, state, context, tier)

    # -- Main menu / start --------------------------------------------------
    if state == cfg.B2B_MAIN_MENU_STATE or not state:
        if message == "Main Menu" or not state or message.lower() in ("menu", "start", "hi", "hello"):
            await send_list_menu(wa_id, **menus.get_dist_main_menu())
            return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}
        # Route menu selections from the list menu (by row id or title).
        return await _handle_main_selection(wa_id, message, context, cfg, tier)

    # -- Track order: awaiting order id -------------------------------------
    if state == cfg.B2B_AWAITING_CALLBACK_TYPE:
        sel = _clean(message)
        if sel in ("virtual", "b2b_callback_virtual"):
            from database import get_db_context
            tenant_id = None
            with get_db_context() as conn:
                row = conn.execute("SELECT tenant_id FROM customers WHERE wa_id = ?", (wa_id,)).fetchone()
                if row:
                    tenant_id = row[0]
                else:
                    row = conn.execute("SELECT tenant_id FROM distributors WHERE wa_id = ?", (wa_id,)).fetchone()
                    if row:
                        tenant_id = row[0]
            if not tenant_id:
                tenant_id = "default"
                
            from services.google_meet_service import create_meeting
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            start_time = now.isoformat()
            end_time = (now + timedelta(hours=1)).isoformat()
            
            meet_result = await create_meeting(
                tenant_id=tenant_id,
                title="Virtual Meeting",
                start_time=start_time,
                end_time=end_time
            )
            if meet_result.get("ok"):
                from services.whatsapp_sender import send_text_message
                await send_text_message(wa_id, f"Here is your Google Meet link: {meet_result['meet_link']}")
            else:
                from services.whatsapp_sender import send_text_message
                await send_text_message(wa_id, "Sorry, I couldn't create a Google Meet link right now. A human agent will contact you shortly.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE}
        elif sel in ("personal", "b2b_callback_personal"):
            from services.whatsapp_sender import send_text_message
            await send_text_message(wa_id, "Please provide the details for your personal meeting (preferred date, time, and topic).")
            return {"new_state": cfg.B2B_AWAITING_CALLBACK_DETAILS}
        else:
            from services.whatsapp_sender import send_button_message
            buttons = [
                {"id": "b2b_callback_virtual", "title": "Virtual"},
                {"id": "b2b_callback_personal", "title": "Personal"},
            ]
            await send_button_message(wa_id, "Please select an option:

How would you like to meet?", buttons)
            return {"new_state": cfg.B2B_AWAITING_CALLBACK_TYPE}

    if state == cfg.B2B_AWAITING_CALLBACK_DETAILS:
        details = message
        from database import get_db_context
        import json
        import secrets
        tenant_id = None
        with get_db_context() as conn:
            row = conn.execute("SELECT tenant_id FROM customers WHERE wa_id = ?", (wa_id,)).fetchone()
            if row:
                tenant_id = row[0]
            else:
                row = conn.execute("SELECT tenant_id FROM distributors WHERE wa_id = ?", (wa_id,)).fetchone()
                if row:
                    tenant_id = row[0]
            if tenant_id:
                try:
                    cb_id = secrets.token_hex(8)
                    cb_data = json.dumps({
                        "customer_name": "Distributor",
                        "wa_id": wa_id,
                        "purpose": f"Personal meeting details: {details}",
                        "callback_type": "personal"
                    })
                    conn.execute(
                        "INSERT INTO callbacks (id, tenant_id, wa_id, data, status) VALUES (?, ?, ?, ?, ?)",
                        (cb_id, tenant_id, wa_id, cb_data, "pending")
                    )
                except Exception as e:
                    pass
        from services.whatsapp_sender import send_text_message
        await send_text_message(wa_id, "Thank you. Your request for a personal meeting has been received. Our team will contact you shortly to confirm.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if state == cfg.B2B_AWAITING_ORDER_ID:
        order = tools.get_order_status(message)
        if order:
            text = (
                f"Order {order['order_number']} is currently {order['status']} "
                f"(payment: {order['payment_status']}). Total: {order['total_amount']}."
            )
            await send_text_message(wa_id, text)
        else:
            await send_text_message(wa_id, "Sorry, I couldn't find that order. Please check the order number and try again.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Finance: make payment ----------------------------------------------
    if state == cfg.B2B_AWAITING_PAYMENT:
        balance = tools.get_outstanding_balance(wa_id)
        await send_text_message(
            wa_id,
            f"Payment of {message} recorded against your outstanding balance of {balance}. "
            "Our finance team will confirm shortly.",
        )
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Support: catalog query ---------------------------------------------
    if state == cfg.B2B_AWAITING_CATALOG_QUERY:
        products = tools.get_products()
        if products:
            lines = ["Here is our distributor catalog:"]
            for p in products[:20]:
                price = f"Rs {p['price']}" if p.get("price") else "price on request"
                lines.append(f"- {p['name']} ({price})")
            await send_text_message(wa_id, "\n".join(lines))
        else:
            await send_text_message(wa_id, "The catalog is currently empty.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Unknown / stale state: fall back to the main menu ------------------
    await send_list_menu(wa_id, **menus.get_dist_main_menu())
    return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}


async def _handle_main_selection(wa_id: str, message: str, context: dict, cfg, tier: str) -> dict:
    from services.whatsapp_sender import send_text_message, send_list_menu
    from . import tools, menus

    sel = _clean(message)

    # -- Unified KB main-menu selections -----------------------------------
    # Every persona sees the same menu; map its row ids/titles to the B2B
    # action so distributors get their business flows from a shared menu.
    if sel in ("menu_products", "view products", "products", "browse", "browse products", "catalog"):
        products = tools.get_products()
        if products:
            lines = ["Here is our distributor catalog:"]
            for p in products[:20]:
                price = f"Rs {p['price']}" if p.get("price") else "price on request"
                lines.append(f"- {p['name']} ({price})")
            lines.append("Reply 'Place Order' to start ordering.")
            await send_text_message(wa_id, "\n".join(lines))
        else:
            await send_text_message(wa_id, "The catalog is currently empty.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel == "menu_new_arrivals" or sel in ("new arrivals", "new releases"):
        from services.whatsapp_sender import send_new_arrivals_message
        sent = await send_new_arrivals_message(wa_id)
        if not sent:
            from services.whatsapp_sender import send_text_message
            await send_text_message(wa_id, "The new releases PDF could not be delivered right now. Please try again shortly.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel == "menu_complaint" or sel in ("raise complaint", "complaint"):
        from . import ticket_flow
        return await ticket_flow.handle_ticket_message(wa_id, message, cfg.DIST_TICKET_START, context, tier)

    if sel == "menu_human" or sel in ("talk to human", "human", "agent"):
        rep = tools.get_assigned_sales_rep(wa_id)
        await send_text_message(wa_id, f"Your assigned sales representative is {rep['name']} ({rep['phone']}).")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel == "menu_discounts" or sel in ("discounts & offers", "discounts", "offers"):
        from . import catalog_flow
        return await catalog_flow.handle_catalog_message(
            wa_id, message, cfg.B2B_VIEW_SCHEMES, context, tier
        )

    if sel == "menu_return_policy" or sel in ("shipping & returns", "shipping", "returns"):
        await send_text_message(
            wa_id,
            "Standard delivery takes 3-5 business days for distributors. "
            "Need anything else?",
        )
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel == "menu_about" or sel in ("company policies", "about"):
        await send_text_message(
            wa_id,
            "We are a premium chikkis, dry fruits & snacks manufacturer. "
            "You can review our company policies with your sales representative.",
        )
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel == "menu_gst" or sel == "gst info" or sel == "gst":
        await send_text_message(wa_id, "GST details are available on your invoice. Contact your sales rep for a copy.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel == "menu_view_cart" or sel in ("view cart", "cart"):
        await send_text_message(wa_id, "Your cart (bulk order) is shown during the order flow. Reply 'Place Order' to start.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Level-1 sub-menu routing (multi-level menus) -----------------------
    if sel == "dist_orders":
        await send_list_menu(wa_id, **menus.get_dist_main_menu())
        return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}
    if sel == "dist_products":
        await send_list_menu(wa_id, **menus.get_dist_main_menu())
        return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}
    if sel == "dist_finance":
        await send_list_menu(wa_id, **menus.get_dist_main_menu())
        return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}
    if sel == "dist_support":
        await send_list_menu(wa_id, **menus.get_dist_main_menu())
        return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}
    if sel == "dist_back_to_main":
        await send_list_menu(wa_id, **menus.get_dist_main_menu())
        return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Orders -------------------------------------------------------------
    if sel in ("place order", "dist_place_order", "order", "new order"):
        from . import order_flow
        # Show the product catalog and enter the order FSM.
        return await order_flow.handle_order_message(wa_id, message, cfg.DIST_ORDER_START, context, tier)

    if sel in ("track order", "dist_track_order", "track"):
        await send_text_message(wa_id, "Please share your Order ID (e.g. ORD-12345).")
        return {"new_state": cfg.B2B_AWAITING_ORDER_ID}

    if sel in ("my orders", "dist_order_history", "dist_orders_history", "orders history", "recent orders"):
        orders = tools.get_distributor_orders(wa_id)
        if orders:
            lines = ["Your recent orders:"]
            for o in orders:
                lines.append(f"- {o['order_number']} | {o['status']} | Rs {o['total_amount']}")
            await send_text_message(wa_id, "\n".join(lines))
        else:
            await send_text_message(wa_id, "You have no orders yet.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Products -----------------------------------------------------------
    if sel in ("browse products", "dist_browse_products", "products", "catalog"):
        products = tools.get_products()
        if products:
            lines = ["Here is our distributor catalog:"]
            for p in products[:20]:
                price = f"Rs {p['price']}" if p.get("price") else "price on request"
                lines.append(f"- {p['name']} ({price})")
            lines.append("Reply 'Place Order' to start ordering.")
            await send_text_message(wa_id, "\n".join(lines))
        else:
            await send_text_message(wa_id, "The catalog is currently empty.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Account ------------------------------------------------------------
    if sel in ("my profile", "dist_profile", "profile"):
        profile = tools.get_distributor_profile(wa_id)
        if profile:
            await send_text_message(
                wa_id,
                f"Name: {profile.get('name', '-')}\n"
                f"Region: {profile.get('region', '-')}\n"
                f"Tier: {profile.get('tier', 'Bronze')}\n"
                f"Outstanding: Rs {profile.get('outstanding_payments', 0)}",
            )
        else:
            await send_text_message(wa_id, "No profile found.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel in ("tier benefits", "dist_tier_benefits", "benefits"):
        benefits = tools.get_tier_benefits(tier)
        lines = [f"Your tier: {benefits['tier']} ({benefits['discount_pct']*100:.0f}% discount)"]
        lines += [f"- {b}" for b in benefits["benefits"]]
        await send_text_message(wa_id, "\n".join(lines))
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel in ("outstanding balance", "dist_outstanding", "outstanding", "balance"):
        balance = tools.get_outstanding_balance(wa_id)
        await send_text_message(wa_id, f"Your current outstanding balance is Rs {balance}.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel in ("outstanding details", "dist_outstanding_details", "outstanding_details"):
        profile = tools.get_distributor_profile(wa_id)
        if not profile:
            await send_text_message(wa_id, "No profile found.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE}
        recent = tools.get_distributor_orders(wa_id, limit=3)
        lines = [
            f"Outstanding details for {profile.get('name') or '-'}",
            f"Region: {profile.get('region') or '-'}   Tier: {profile.get('tier', 'Bronze')}",
            f"Total outstanding: Rs {profile.get('outstanding_payments', 0)}",
            "",
            "Recent orders:",
        ]
        if recent:
            for o in recent:
                lines.append(
                    f"- {o['order_number']} | {o['status']} | "
                    f"Rs {o['total_amount']} | {o.get('delivery_date') or '-'}"
                )
        else:
            lines.append("  (no recent orders)")
        await send_text_message(wa_id, "\n".join(lines))
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Support / Tickets --------------------------------------------------
    if sel in ("raise ticket", "dist_raise_ticket", "dist_ticket", "ticket", "support ticket"):
        from . import ticket_flow
        return await ticket_flow.handle_ticket_message(wa_id, message, cfg.DIST_TICKET_START, context, tier)

    if sel in ("priority support", "dist_priority_support"):
        await send_text_message(
            wa_id,
            "You are on Priority Support. Your tickets will be handled first. "
            "Reply 'Raise Ticket' to open one.",
        )
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if sel in ("contact sales rep", "dist_contact_rep", "dist_sales_rep", "sales rep", "rep"):
        rep = tools.get_assigned_sales_rep(wa_id)
        await send_text_message(wa_id, f"Your assigned sales representative is {rep['name']} ({rep['phone']}).")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Catalogue / Price list / Schemes ------------------------------------
    if sel in ("download catalogue", "dist_download_catalog", "dist_catalogue", "catalogue", "catalog pdf"):
        from . import catalog_flow
        return await catalog_flow.handle_catalog_message(
            wa_id, message, cfg.B2B_VIEW_CATALOG, context, tier
        )

    if sel in ("latest price list", "dist_price_list", "price list", "price_list"):
        from . import catalog_flow
        return await catalog_flow.handle_catalog_message(
            wa_id, message, cfg.B2B_VIEW_PRICE_LIST, context, tier
        )

    if sel in ("schemes & offers", "dist_schemes", "schemes", "offers", "current schemes"):
        from . import catalog_flow
        return await catalog_flow.handle_catalog_message(
            wa_id, message, cfg.B2B_VIEW_SCHEMES, context, tier
        )

    # -- Finance: invoice + payment confirmation -----------------------------
    if sel in ("request invoice", "dist_request_invoice", "dist_invoice", "invoice", "invoice request"):
        from . import finance_flow
        await send_text_message(
            wa_id,
            "Sure, I can request an invoice. Please reply with your Order ID (e.g. ORD-12345).",
        )
        return {"new_state": cfg.B2B_AWAITING_INVOICE_ORDER_ID, "context": context}

    if sel in ("payment confirmation", "dist_pay_confirm", "dist_payment_confirm", "confirm payment", "payment"):
        from . import finance_flow
        # Reset any prior step so a re-entry starts fresh.
        context.pop("amount", None)
        context.pop("step", None)
        await send_text_message(
            wa_id,
            "I can record your payment confirmation. Please reply with the amount in rupees.",
        )
        return {"new_state": cfg.B2B_AWAITING_PAYMENT_PROOF, "context": context}

    # -- Settings -----------------------------------------------------------
    if sel in ("account settings", "dist_settings", "settings"):
        await send_text_message(wa_id, "You can update your preferences with your sales representative.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    # -- Unrecognised input from the main menu: re-show the menu ------------
    await send_list_menu(wa_id, **menus.get_dist_main_menu())
    return {"status": "menu_sent", "new_state": cfg.B2B_MAIN_MENU_STATE}
