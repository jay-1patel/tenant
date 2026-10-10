
import json
import logging
import re

logger = logging.getLogger("b2c_workflows")


def _clean(text: str) -> str:
    """Lowercase and strip emoji so menu titles / list replies match keywords."""
    if not text:
        return ""
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)
    text = re.sub(r"\[id:[^\]]+\]", "", text, flags=re.IGNORECASE)
    return " ".join((text or "").strip().lower().split())


def _cfg():
    from . import config
    return config


async def handle_b2c_message(wa_id: str, message: str, state: str, context: dict) -> dict:
    from services.whatsapp_sender import send_text_message, send_button_message, send_list_menu
    from . import tools, menus

    cfg = _cfg()
    message = (message or "").strip()
    context = context or {}

    # ── Global rule: human handover request wins over anything else ──────────
    if tools.should_escalate(message):
        return await _escalate(wa_id, cfg)

    # ── Main menu / start ─────────────────────────────────────────────────────
    if state == cfg.B2C_MAIN_MENU_STATE or not state:
        if message == "Main Menu" or not state or message.lower() in ("menu", "start", "hi", "hello"):
            await send_list_menu(wa_id, **menus.get_main_menu())
            return {"status": "menu_sent", "new_state": cfg.B2C_MAIN_MENU_STATE}
        # Not a menu button: fall back to the RAG pipeline for general questions.
        return await _handle_main_selection(wa_id, message, context, cfg)

    # ── Complaint: awaiting type ─────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_COMPLAINT_TYPE:
        # Send interactive buttons for complaint type selection.
        buttons = [
            {"id": "b2c_complaint_damaged", "title": "Damaged"},
            {"id": "b2c_complaint_wrong_item", "title": "Wrong Item"},
            {"id": "b2c_complaint_other", "title": "Other"},
        ]
        # A known type (button title or typed text) advances the flow.
        complaint_type = _match_complaint_type(message)
        if complaint_type:
            context["complaint_type"] = complaint_type
            await send_text_message(wa_id, "Please briefly describe the issue.")
            return {"new_state": cfg.B2C_AWAITING_COMPLAINT_DESC, "context": context}
        await send_button_message(wa_id, "Please select the type of complaint:", buttons)
        return {"new_state": cfg.B2C_AWAITING_COMPLAINT_TYPE}

    # ── Complaint: awaiting description ───────────────────────────────────────
    if state == cfg.B2C_AWAITING_COMPLAINT_DESC:
        ctype = context.get("complaint_type", "Other")
        ticket = tools.register_b2c_complaint(wa_id, ctype, message)
        await send_text_message(wa_id, f"Complaint registered! Your ticket ID is {ticket}. We'll be in touch soon.")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE, "context": context}

    # ── Nutrition lookup ──────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_PRODUCT_QUERY:
        info = tools.get_nutrition_info(message)
        if info:
            text = info["name"].title()
            if info.get("description"):
                text += f": {info['description']}"
            if info.get("price"):
                text += f" | Price: ₹{info['price']}"
            if info.get("unit"):
                text += f" per {info['unit']}"
            if info.get("ingredients"):
                text += f"\nIngredients: {info['ingredients']}"
            await send_text_message(wa_id, text)
        else:
            await send_text_message(wa_id, "Sorry, I couldn't find nutrition info for that product.")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # ── Recipe suggestions ────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_RECIPE_QUERY:
        recipes = tools.get_recipe_suggestions(message)
        if recipes:
            text = "\n".join(f"- {r['title']} ({', '.join(r['ingredients'])})" for r in recipes)
            await send_text_message(wa_id, f"Here are some recipe ideas:\n{text}")
        else:
            await send_text_message(wa_id, "I couldn't find recipes for that. Try another ingredient!")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # ── Order tracking ────────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_ORDER_ID:
        await send_text_message(wa_id, "I'm checking that order now. (Order lookup coming soon.)")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # ── Shipping help ─────────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_SHIPPING_QUERY:
        await send_text_message(wa_id, "Standard delivery takes 3-5 business days. Need anything else?")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # ── Callback ──────────────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_CALLBACK_TYPE:
        sel = _clean(message)
        if sel in ("virtual", "b2c_callback_virtual"):
            from database import get_db_context
            tenant_id = None
            with get_db_context() as conn:
                from services.whatsapp_sender import send_text_message
                await send_text_message(wa_id, "Sorry, I couldn't create a Google Meet link right now. A human agent will contact you shortly.")
            return {"new_state": cfg.B2C_MAIN_MENU_STATE}
        elif sel in ("personal", "b2c_callback_personal"):
            from services.whatsapp_sender import send_text_message
            await send_text_message(wa_id, "Please provide the details for your personal meeting (preferred date, time, and topic).")
            return {"new_state": cfg.B2C_AWAITING_CALLBACK_DETAILS}
        else:
            from services.whatsapp_sender import send_button_message
            buttons = [
                {"id": "b2c_callback_virtual", "title": "Virtual"},
                {"id": "b2c_callback_personal", "title": "Personal"},
            ]
            await send_button_message(wa_id, "Please select an option:\n\nHow would you like to meet?", buttons)
            return {"new_state": cfg.B2C_AWAITING_CALLBACK_TYPE}

    if state == cfg.B2C_AWAITING_CALLBACK_DETAILS:
        details = message
        from database import get_db_context
        import json
        try:
            with get_db_context() as conn:
                tenant_id = None
                from datetime import datetime
                import uuid
                cb_id = str(uuid.uuid4())
                cb_data = json.dumps({
                    "customer_name": "Customer",
                    "wa_id": wa_id,
                    "purpose": f"Personal meeting details: {details}",
                    "callback_type": "personal"
                })
                conn.execute(
                    "INSERT INTO callbacks (id, tenant_id, wa_id, data, status) VALUES (?, ?, ?, ?, ?)",
                    (cb_id, tenant_id, wa_id, cb_data, "pending")
                )
                from services.whatsapp_sender import send_text_message
                await send_text_message(wa_id, "Your personal meeting request has been logged. We will contact you soon to confirm.")
        except Exception as e:
            logger.error(f"Failed to log callback: {e}")
            from services.whatsapp_sender import send_text_message
            await send_text_message(wa_id, "Sorry, there was an error processing your request. We'll be in touch soon.")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # ── Unknown / stale state: fall back to RAG ───────────────────────────────
    return await _fallback_to_rag(wa_id, message, cfg)


async def _handle_main_selection(wa_id: str, message: str, context: dict, cfg) -> dict:
    """Handle a selection made from the B2C main menu.

    Returns a fallback to the RAG pipeline when the message is not a menu
    button (so general product/nutrition questions still get answered).
    """
    from services.whatsapp_sender import send_text_message, send_button_message, send_list_menu, send_image_message
    from . import tools, menus

    sel = _clean(message)

    if sel in ("new arrivals", "new releases", "menu_new_arrivals"):
        from services.whatsapp_sender import send_new_arrivals_message
        sent = await send_new_arrivals_message(wa_id)
        if not sent:
            await send_text_message(wa_id, "The new releases PDF could not be delivered right now. Please try again shortly.")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("products", "b2c_products", "browse", "product", "view products", "menu_products"):
        products = tools.list_products()
        if products:
            with_images = [p for p in products if p.get("media_url")]
            # Send an image message per product that has one (WhatsApp-style).
            for p in with_images:
                price = f"₹{p['price']}" if p.get("price") else "price on request"
                unit = f" per {p['unit']}" if p.get("unit") else ""
                caption = f"{p['name'].title()} — {price}{unit}"
                await send_image_message(wa_id, p["media_url"], caption)
            # Text summary of the full catalog (name + price).
            lines = ["🛍️ *Our Products:*"]
            for p in products:
                price = f"₹{p['price']}" if p.get("price") else "price on request"
                unit = f" / {p['unit']}" if p.get("unit") else ""
                lines.append(f"📦 *{p['name'].title()}* — 💰 {price}{unit}")
            lines.append("\n Reply with a product name for more details.")
            await send_text_message(wa_id, "\n".join(lines))
        else:
            await send_text_message(wa_id, "Sorry, our product catalog is currently empty. Check back soon!")
        return {"new_state": cfg.B2C_AWAITING_PRODUCT_QUERY}

    if sel in ("nutrition", "b2c_nutrition"):
        await send_text_message(wa_id, "Which product would you like nutrition info for?")
        return {"new_state": cfg.B2C_AWAITING_PRODUCT_QUERY}

    if sel in ("health benefits", "b2c_health_benefits", "health"):
        answer = await _kb_answer(wa_id, "What are the health benefits of your products?")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("product usage", "b2c_product_usage", "usage"):
        answer = await _kb_answer(wa_id, "How should I use your products? What is the recommended usage and best way to consume them?")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # My Order: Track / Complaint
    if sel in ("track order", "b2c_track_order", "track"):
        await send_text_message(wa_id, "Please share your Order ID.")
        return {"new_state": cfg.B2C_AWAITING_ORDER_ID}

    if sel in ("raise complaint", "b2c_complaint", "complaint", "menu_complaint"):
        await send_text_message(wa_id, "Please select the type of complaint.")
        return {"new_state": cfg.B2C_AWAITING_COMPLAINT_TYPE}

    # Help: Shipping / Recipes / Human handover
    if sel in ("shipping", "b2c_shipping", "shipping & returns", "return & refund policy",
               "return policy", "returns", "menu_return_policy"):
        answer = await _kb_answer(wa_id, "What is your shipping policy, return policy, and refund policy?")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("company policies", "menu_about"):
        answer = await _kb_answer(wa_id, "Tell me about your company and company policies.")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("discounts & offers", "menu_discounts", "offers", "discounts"):
        answer = await _kb_answer(wa_id, "What discounts and offers do you currently have?")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("gst info", "menu_gst", "gst"):
        answer = await _kb_answer(wa_id, "What is your GST number and tax/invoice details?")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("recipes", "b2c_recipes"):
        await send_text_message(wa_id, "Which ingredient or product would you like recipe ideas for?")
        return {"new_state": cfg.B2C_AWAITING_RECIPE_QUERY}

    if sel in ("talk to human", "b2c_human", "human", "menu_human"):
        return await _escalate(wa_id, cfg)

    if sel in ("view cart", "menu_view_cart"):
        answer = await _kb_answer(wa_id, "Show me the items in my cart.")
        await send_text_message(wa_id, answer)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    if sel in ("book a callback", "menu_callback", "callback", "request a callback", "book appointment"):
        buttons = [
            {"id": "b2c_callback_virtual", "title": "Virtual"},
            {"id": "b2c_callback_personal", "title": "Personal"},
        ]
        await send_button_message(wa_id, "How would you like to meet?", buttons)
        return {"new_state": cfg.B2C_AWAITING_CALLBACK_TYPE}

    # Anything else while in the main menu: answer via the RAG pipeline.
    return await _fallback_to_rag(wa_id, message, cfg)


async def _fallback_to_rag(wa_id: str, message: str, cfg) -> dict:
    """Answer a general question from the uploaded documents.

    Queries two document sources in order:
      1. The FAQ hybrid index (FAQ text docs + catalogue / new-arrivals PDFs).
      2. The KB FAISS index (company details / nutrition facts / full-site PDFs).

    Falls back to a generic response only when neither source has a match, so
    the bot always returns a message.
    """
    from services.whatsapp_sender import send_text_message

    answer = None

    # 1. FAQ index: covers the uploaded FAQ text docs and catalogue/new-arrival PDFs.
    try:
        from faq.service import faq_index
        if faq_index.is_built:
            hits = faq_index.search(message, k=1)
            if hits:
                # faq_index.search returns (text, metadata, score) tuples.
                answer = hits[0][0]
    except Exception as e:
        logger.warning(f"FAQ index lookup failed: {e}")

    # 2. KB FAISS index: covers the remaining KB PDFs (company, nutrition, full site).
    if not answer:
        try:
            import json as _json
            from kb.services.rag import search_kb_faiss
            from database import get_db_context
            hits = search_kb_faiss(message, limit=3)
            if hits:
                top = hits[0]
                with get_db_context() as conn:
                    row = conn.execute(
                        "SELECT chunks_json FROM knowledge_base WHERE id=?",
                        (top["doc_id"],),
                    ).fetchone()
                if row and row[0]:
                    chunks = _json.loads(row[0])
                    ci = top.get("chunk_index")
                    if isinstance(ci, int) and 0 <= ci < len(chunks):
                        answer = chunks[ci]
        except Exception as e:
            logger.warning(f"KB index lookup failed: {e}")

    if not answer:
        answer = (
            "I'm not certain about that. Would you like to browse our products, "
            "check nutrition info, or talk to a human agent?"
        )

    await send_text_message(wa_id, answer)
    return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE}


async def _kb_answer(wa_id: str, query: str) -> str:
    """Answer an informational query via the document indexes.

    Reuses _fallback_to_rag's lookup by temporarily capturing the answer
    instead of sending it directly.
    """
    import services.whatsapp_sender as sender

    answer = None

    # 1. FAQ hybrid index
    try:
        from faq.service import faq_index
        if faq_index.is_built:
            hits = faq_index.search(query, k=1)
            if hits:
                answer = hits[0][0]
    except Exception as e:
        logger.warning(f"FAQ index lookup failed: {e}")

    # 2. KB FAISS index
    if not answer:
        try:
            import json as _json
            from kb.services.rag import search_kb_faiss
            from database import get_db_context
            hits = search_kb_faiss(query, limit=3)
            if hits:
                top = hits[0]
                with get_db_context() as conn:
                    row = conn.execute(
                        "SELECT chunks_json FROM knowledge_base WHERE id=?",
                        (top["doc_id"],),
                    ).fetchone()
                if row and row[0]:
                    chunks = _json.loads(row[0])
                    ci = top.get("chunk_index")
                    if isinstance(ci, int) and 0 <= ci < len(chunks):
                        answer = chunks[ci]
        except Exception as e:
            logger.warning(f"KB index lookup failed: {e}")

    return answer or (
        "I'm not certain about that. Would you like to browse our products, "
        "check nutrition info, or talk to a human agent?"
    )


def _match_complaint_type(message: str) -> str | None:
    """Return a normalized complaint type if the message selects one."""
    if not message:
        return None
    lowered = message.strip().lower()
    if lowered in ("damaged", "damaged item"):
        return "Damaged"
    if lowered in ("wrong item", "wrong"):
        return "Wrong Item"
    if lowered in ("other",):
        return "Other"
    return None


async def _escalate(wa_id: str, cfg) -> dict:
    """Set human_handover=True in the DB and send the connecting message."""
    from services.whatsapp_sender import send_text_message

    try:
        from database import set_human_handover
        set_human_handover(wa_id, True)
    except Exception as e:
        logger.error(f"human_handover update failed for {wa_id}: {e}")

    await send_text_message(wa_id, "Connecting you to a human agent...")
    return {"status": "human_handover", "new_state": cfg.B2C_MAIN_MENU_STATE}
