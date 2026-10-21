
import json
import logging
import re

logger = logging.getLogger("b2c_workflows")

# Relevance floors below which a document hit is treated as noise instead of an
# answer. FAQ scores are cross-encoder logits (~0.0 = neutral); KB scores are
# cosine similarity on normalized embeddings. Tune if real matches regress.
MIN_FAQ_CE_SCORE = 0.30
MIN_KB_SIMILARITY = 0.40


def _clean(text: str) -> str:
    """Lowercase and strip emoji so menu titles / list replies match keywords."""
    if not text:
        return ""
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)
    return " ".join((text or "").strip().lower().split())


def _cfg():
    from . import config
    return config


def _is_meaningless(message: str) -> bool:
    """True for keyboard-mash / no-query noise (jsdbkop, hyyyy, emoji-only...)."""
    try:
        from routing.classifier import is_meaningless_or_greeting
        return bool(is_meaningless_or_greeting(message))
    except Exception:
        return False


def _is_greeting(message: str) -> bool:
    """True for greeting-ish input, including typos/letter-spam (Helooyyy)."""
    try:
        from routing.classifier import is_greeting
        return bool(is_greeting(message))
    except Exception:
        return False


async def _llm_synthesize(raw: str, label: str, query: str, tenant_id: str | None = None) -> str:
    """Run a raw stored answer through the LLM (Ollama) before sending.

    Every informational reply must be model-generated, not echoed verbatim from
    the tenant profile / offerings rows. Falls back to the raw text if the LLM
    call fails so a provider outage never drops the reply.
    """
    if not raw:
        return raw
    try:
        try:
            from faq.service import synthesize_intent_answer
        except ImportError:
            from backend.faq.service import synthesize_intent_answer
        return await synthesize_intent_answer(
            raw_content=raw,
            intent_name=label or query,
            user_query=query,
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.warning(f"LLM synthesis failed for '{label}': {e}")
        return raw


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
        clean_msg = _clean(message)
        if clean_msg in ("main menu", "menu", "start", "hi", "hello", "hey", "show options", "options") or message in ("Main Menu", "main_menu", "menu_main"):
            menu_data = menus.get_main_menu(wa_id)
            if menu_data.get("type") == "buttons":
                await send_button_message(
                    wa_id,
                    body=menu_data.get("text", "Options"),
                    buttons=menu_data.get("buttons", []),
                )
            else:
                await send_list_menu(
                    wa_id,
                    header=menu_data.get("header", ""),
                    body=menu_data.get("body", "What would you like to explore today?"),
                    button_text=menu_data.get("button_text", "Show Options"),
                    sections=menu_data.get("sections", []),
                )
            return {"status": "menu_sent", "new_state": cfg.B2C_MAIN_MENU_STATE}
        # Greeting-ish input (typos / letter-spam like "Helooyyy"): show the menu.
        if _is_greeting(message):
            menu_data = menus.get_main_menu(wa_id)
            if menu_data.get("type") == "buttons":
                await send_button_message(
                    wa_id,
                    body=menu_data.get("text", "Options"),
                    buttons=menu_data.get("buttons", []),
                )
            else:
                await send_list_menu(
                    wa_id,
                    header=menu_data.get("header", ""),
                    body=menu_data.get("body", "What would you like to explore today?"),
                    button_text=menu_data.get("button_text", "Show Options"),
                    sections=menu_data.get("sections", []),
                )
            return {"status": "menu_sent", "new_state": cfg.B2C_MAIN_MENU_STATE}
        # Meaningless / keyboard-mash input: nudge to the menu instead of
        # throwing the noise at the RAG index (which returns unrelated answers).
        if _is_meaningless(message):
            await send_text_message(wa_id, "Sorry, I didn't catch that. Type *hi* for the menu.")
            return {"status": "meaningless", "new_state": cfg.B2C_MAIN_MENU_STATE}
        # Not a menu button: fall back to the RAG pipeline for general questions.
        return await _handle_main_selection(wa_id, message, context, cfg)

    # ── Complaint: awaiting type ─────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_COMPLAINT_TYPE:
        clean = (message or "").strip().lower()
        if clean in ("cancel", "stop", "exit", "quit", "menu", "main menu", "back", "restart", "start over"):
            await send_text_message(wa_id, "Complaint registration cancelled. Type *menu* or ask me anything anytime! 🙏")
            return {"new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

        # If user asked a new question, break out of complaint flow and answer it via RAG
        question_words = (
            "what", "how", "where", "when", "why", "who", "which",
            "can", "could", "would", "should", "do", "does", "did", "is", "are", "will", "may",
            "show", "tell", "price", "cost", "rates", "hi", "hello", "hey",
            "help", "support", "services", "products", "loans", "cards"
        )
        if "?" in clean or any(clean.startswith(w + " ") or clean == w for w in question_words):
            return await _fallback_to_rag(wa_id, message, cfg)

        buttons = [
            {"id": "b2c_complaint_damaged", "title": "Damaged"},
            {"id": "b2c_complaint_wrong_item", "title": "Wrong Item"},
            {"id": "b2c_complaint_other", "title": "Other"},
        ]
        complaint_type = _match_complaint_type(message)
        if complaint_type:
            context["complaint_type"] = complaint_type
            await send_text_message(wa_id, "Please briefly describe the issue (or type *cancel* to exit).")
            return {"new_state": cfg.B2C_AWAITING_COMPLAINT_DESC, "context": context}
        await send_button_message(wa_id, "Please select the type of complaint (or type *cancel*):", buttons)
        return {"new_state": cfg.B2C_AWAITING_COMPLAINT_TYPE}

    # ── Complaint: awaiting description ───────────────────────────────────────
    if state == cfg.B2C_AWAITING_COMPLAINT_DESC:
        clean = (message or "").strip().lower()
        if clean in ("cancel", "stop", "exit", "quit", "menu", "main menu", "back"):
            context.pop("complaint_type", None)
            await send_text_message(wa_id, "Complaint registration cancelled. Type *menu* or ask me anything anytime! 🙏")
            return {"new_state": cfg.B2C_MAIN_MENU_STATE, "context": context}

        question_words = (
            "what", "how", "where", "when", "why", "who", "which",
            "can", "could", "would", "should", "do", "does", "did", "is", "are", "will", "may",
            "show", "tell", "price", "cost", "rates", "hi", "hello", "hey",
            "help", "support", "services", "products", "loans", "cards"
        )
        if "?" in clean or any(clean.startswith(w + " ") or clean == w for w in question_words):
            context.pop("complaint_type", None)
            return await _fallback_to_rag(wa_id, message, cfg)

        ctype = context.get("complaint_type", "Other")
        ticket = tools.register_b2c_complaint(wa_id, ctype, message)
        context.pop("complaint_type", None)
        await send_text_message(
            wa_id,
            f"✅ Complaint registered! Your ticket ID is {ticket}. We'll be in touch soon.\n\nType *menu* anytime or feel free to ask another question."
        )
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
        try:
            from backend.services.order_service import lookup_order_status
            query_ref = "" if message.strip().lower() in ("recent", "latest", "all", "orders") else message
            status_text = lookup_order_status(wa_id, query_ref)
        except Exception as exc:
            logger = __import__("logging").getLogger("b2c_workflows")
            logger.error("Order lookup failed for %s: %s", wa_id, exc)
            status_text = (
                "Sorry, I couldn't look that order up right now. "
                "Please try again with your Order ID."
            )
        await send_text_message(wa_id, status_text)
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # ── Shipping help ─────────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_SHIPPING_QUERY:
        await send_text_message(wa_id, "Standard delivery takes 3-5 business days. Need anything else?")
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
    if sel in ("track order", "b2c_track_order", "track", "track_order", "menu_track_order", "orders", "my orders", "order status"):
        await send_text_message(
            wa_id,
            "Please share your *Order ID* (e.g. ORD-1234), or reply *recent* to view your latest orders."
        )
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

    # Anything else while in the main menu: answer via the RAG pipeline.
    return await _fallback_to_rag(wa_id, message, cfg)


async def _fallback_to_rag(wa_id: str, message: str, cfg) -> dict:
    """Answer a general question from the uploaded documents.

    Resolution order:
      1. Tenant profile menu rows (list-row taps arrive as plain title text on
         the send2 poll: "💼  Career", "🚀  Services", "💻  Technologies"). These
         are answered from the tenant's own content — the title must never be
         thrown at the RAG index, which returns an unrelated chunk.
      2. Rules-based intent match for typed panel words (careers, services, ...).
      3. The FAQ hybrid index and the KB FAISS index, gated by a relevance
         floor so an off-topic tap does not get a confident-looking answer.
      4. A generic "not certain" reply as the final fallback.
    """
    from services.whatsapp_sender import send_text_message, send_button_message

    # 0. Tenant menu row (tapped title) / rules intent: authoritative, no RAG.
    try:
        try:
            from services.intent_answers import answer_for_menu_title, answer_for_text
        except ImportError:
            from backend.services.intent_answers import answer_for_menu_title, answer_for_text
        tenant_answer = answer_for_menu_title(wa_id, message)
        if not tenant_answer:
            tenant_answer = answer_for_text(wa_id, message)
            try:
                from services import service_answers as _svc_ans
            except Exception:
                try:
                    from backend.services import service_answers as _svc_ans
                except Exception:
                    _svc_ans = None
            if _svc_ans and _svc_ans.is_service_query(message):
                svc_full = _svc_ans.answer_for_text(wa_id, message)
                if svc_full:
                    tenant_answer = svc_full
        if tenant_answer:
            tid = None
            try:
                from shared.tenancy.resolver import resolve_tenant_for_user
                tid = resolve_tenant_for_user(wa_id)
            except Exception:
                pass
            synthesized = await _llm_synthesize(tenant_answer, message, message, tenant_id=tid)
            from routing.button_actions import get_contextual_buttons
            from services.whatsapp_sender import send_button_message, send_text_message
            buttons = get_contextual_buttons(message, tenant_id=tid, wa_id=wa_id, limit=3)
            if buttons:
                await send_button_message(wa_id, synthesized, buttons)
            else:
                await send_text_message(wa_id, synthesized)
            return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE}
    except Exception as e:
        logger.debug(f"Tenant intent resolution failed: {e}")

    # 0b. Services row ("Our Services") / typed service enquiry: return the
    # tenant's configured offerings. send2 delivers a list-row tap as plain
    # title text, so the interactive-id shortcut in routing/message.py
    # (menu_services) never fires on the poller path — resolve it by title here.
    try:
        if _is_services_title(wa_id, message):
            try:
                from services import service_answers
            except ImportError:
                from backend.services import service_answers
            svc = service_answers.answer_for_text(wa_id, message)
            if svc:
                tid = None
                try:
                    from shared.tenancy.resolver import resolve_tenant_for_user
                    tid = resolve_tenant_for_user(wa_id)
                except Exception:
                    pass
                synthesized = await _llm_synthesize(svc, "Our Services", message, tenant_id=tid)
                from routing.button_actions import get_contextual_buttons
                from services.whatsapp_sender import send_button_message, send_text_message
                buttons = get_contextual_buttons("services", wa_id=wa_id, limit=3)
                if buttons:
                    await send_button_message(wa_id, synthesized, buttons)
                else:
                    await send_text_message(wa_id, synthesized)
                return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE}
    except Exception as e:
        logger.debug(f"Service listing resolution failed: {e}")

    # A tapped menu row with no configured answer/description (and no intent)
    # must not dead-end: search the uploaded documents (FAQ + KB) below and let
    # the relevance floor decide. The generic "not certain" reply stays the
    # final fallback if the database has nothing relevant either.

    answer = None

    # 0. Check Tenant Intent Answers first (safety net for tenant menu options/queries)
    tid = None
    try:
        from shared.tenancy.resolver import resolve_tenant_for_user
        try:
            from services import intent_answers
        except ImportError:
            from backend.services import intent_answers
        tid = resolve_tenant_for_user(wa_id)
        intent_rep = (
            intent_answers.answer_for_button(wa_id, message, tenant_id=tid)
            or intent_answers.answer_for_intent(wa_id, message, tenant_id=tid)
            or intent_answers.answer_for_text(wa_id, message, tenant_id=tid)
        )
        if intent_rep:
            synthesized = await _llm_synthesize(intent_rep, message, message, tenant_id=tid)
            from routing.button_actions import get_contextual_buttons
            from services.whatsapp_sender import send_button_message
            buttons = get_contextual_buttons(message, tenant_id=tid, wa_id=wa_id, limit=3)
            if buttons:
                await send_button_message(wa_id, synthesized, buttons)
            else:
                await send_text_message(wa_id, synthesized)
            return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE}
    except Exception as exc:
        logger.debug(f"B2C tenant intent fallback check: {exc}")

    # 1. Query FAQ service (which performs hybrid retrieval + LLM answer synthesis)
    interactive = None
    try:
        from faq.service import handle_faq_query
        faq_res = await handle_faq_query({"message": message, "wa_id": wa_id, "tenant_id": tid})
        if faq_res and faq_res.get("answer") and faq_res.get("answer").strip():
            answer = faq_res["answer"]
            interactive = faq_res.get("interactive")
    except Exception as e:
        logger.warning(f"FAQ index lookup failed: {e}")

    # 2. KB FAISS index: covers the remaining KB PDFs (company, nutrition, full site)
    if not answer:
        try:
            import json as _json
            from kb.services.rag import search_kb_faiss
            from database import get_db_context
            hits = search_kb_faiss(message, limit=5)
            kb_chunks = []
            if hits:
                with get_db_context() as conn:
                    for top in hits:
                        row = conn.execute(
                            "SELECT chunks_json FROM knowledge_base WHERE id=?",
                            (top["doc_id"],),
                        ).fetchone()
                        if row and row[0]:
                            chunks = _json.loads(row[0])
                            ci = top.get("chunk_index")
                            if isinstance(ci, int) and 0 <= ci < len(chunks):
                                ctext = chunks[ci]
                                if ". . . ." not in ctext and "...." not in ctext:
                                    kb_chunks.append(ctext)

            if kb_chunks:
                from faq.service import _generate_ollama_dynamic_response, _brand_context, _render_prompt, SYSTEM_PROMPT_TEMPLATE, _append_signature
                brand = _brand_context(tid)
                sys_prompt = _render_prompt(SYSTEM_PROMPT_TEMPLATE, brand)
                combined_context = "\n\n---\n\n".join(kb_chunks)
                llm_res = await _generate_ollama_dynamic_response(sys_prompt, message, combined_context, tenant_id=tid)
                if llm_res and llm_res.get("answer"):
                    answer = _append_signature(llm_res["answer"], tid)
                    interactive = llm_res.get("interactive")
        except Exception as e:
            logger.warning(f"KB index lookup failed: {e}")

    if not answer:
        answer = (
            "I'm not certain about that. Would you like to check our services, "
            "book a callback, or talk to an agent?"
        )

    # If no interactive buttons were returned, attach tenant-aware contextual follow-up buttons
    if not (interactive and interactive.get("buttons")):
        from routing.button_actions import get_contextual_buttons
        ctx_btns = get_contextual_buttons(message, tenant_id=tid, wa_id=wa_id, limit=3)
        if ctx_btns:
            interactive = {"type": "button", "buttons": ctx_btns}

    if interactive and interactive.get("buttons"):
        await send_button_message(wa_id, answer, interactive["buttons"])
    else:
        await send_text_message(wa_id, answer)
    return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE}


def _is_services_title(wa_id: str, message: str) -> bool:
    """True if the message is the tenant's services/offerings menu row.

    Matches the tapped (or typed) row title against the visible profile menu
    and returns True only for the rows that list offerings (menu_services /
    menu_offerings), so the caller knows to render the offerings list.
    """
    if not (message or "").strip():
        return False
    try:
        from services.menu_catalog import get_kb_main_menu
        from services.intent_answers import _clean_title as _tc
        target = _clean(message)
        if not target:
            return False
        for item in get_kb_main_menu(wa_id):
            if getattr(item, "id", "") in ("menu_services", "menu_offerings") \
                    and _tc(item.title) == target:
                return True
    except Exception as e:
        logger.debug(f"Services title check failed: {e}")
    return False


async def _kb_answer(wa_id: str, query: str) -> str:
    """Answer an informational query via document indexes with LLM synthesis."""
    try:
        from faq.service import handle_faq_query
        res = await handle_faq_query({"message": query, "wa_id": wa_id})
        if res and res.get("answer") and res.get("answer").strip():
            return res["answer"]
    except Exception as e:
        logger.warning(f"FAQ index lookup for '{query}' failed: {e}")

    try:
        import json as _json
        from kb.services.rag import search_kb_faiss
        from database import get_db_context
        hits = search_kb_faiss(query, limit=3)
        kb_chunks = []
        if hits:
            with get_db_context() as conn:
                for top in hits:
                    row = conn.execute(
                        "SELECT chunks_json FROM knowledge_base WHERE id=?",
                        (top["doc_id"],),
                    ).fetchone()
                    if row and row[0]:
                        chunks = _json.loads(row[0])
                        ci = top.get("chunk_index")
                        if isinstance(ci, int) and 0 <= ci < len(chunks):
                            kb_chunks.append(chunks[ci])

        if kb_chunks:
            from faq.service import _generate_ollama_dynamic_response, _brand_context, _render_prompt, SYSTEM_PROMPT_TEMPLATE, _append_signature
            brand = _brand_context()
            sys_prompt = _render_prompt(SYSTEM_PROMPT_TEMPLATE, brand)
            combined_context = "\n\n---\n\n".join(kb_chunks)
            llm_res = await _generate_ollama_dynamic_response(sys_prompt, query, combined_context)
            if llm_res and llm_res.get("answer"):
                return _append_signature(llm_res["answer"])
    except Exception as e:
        logger.warning(f"KB index lookup for '{query}' failed: {e}")

    return (
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
