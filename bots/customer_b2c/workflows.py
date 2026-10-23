
import json
import logging
import re

logger = logging.getLogger("b2c_workflows")

# Relevance floors below which a document hit is treated as noise instead of an
# answer. FAQ scores are cross-encoder logits (~0.0 = neutral); KB scores are
# cosine similarity on normalized embeddings. Tune if real matches regress.
MIN_FAQ_CE_SCORE = 0.30
MIN_KB_SIMILARITY = 0.40

# WhatsApp message length limits
MAX_WHATSAPP_TEXT_LENGTH = 4000

# Common question starters for detecting user questions
QUESTION_WORDS = (
    "what", "how", "where", "when", "why", "who", "which",
    "can", "could", "would", "should", "do", "does", "did", "is", "are", "will", "may",
    "show", "tell", "price", "cost", "rates", "hi", "hello", "hey",
    "help", "support", "services", "products", "loans", "cards"
)


def _truncate_for_whatsapp(text: str, max_len: int = MAX_WHATSAPP_TEXT_LENGTH) -> str:
    """Truncate text to WhatsApp's maximum message length."""
    if not text:
        return text
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _validate_input_length(text: str, field_name: str = "input") -> tuple[bool, str]:
    """Validate input length and return (is_valid, error_message)."""
    if not text or len(text.strip()) == 0:
        return False, f"Please provide a valid {field_name}."
    if len(text) > MAX_WHATSAPP_TEXT_LENGTH:
        return False, f"Please keep your {field_name} under {MAX_WHATSAPP_TEXT_LENGTH} characters."
    return True, ""


def _sanitize_kb_query(query: str) -> str:
    """Sanitize a KB query to prevent injection or special character issues."""
    if not query:
        return query
    # Remove special SQL/NoSQL characters that could cause issues
    import re
    sanitized = re.sub(r'[;\-\'\"\\(){}<>+|=*&%$#@!~`]', ' ', query)
    # Normalize whitespace
    sanitized = ' '.join(sanitized.strip().split())
    return sanitized[:MAX_WHATSAPP_TEXT_LENGTH]


def _is_new_user(wa_id: str) -> bool:
    """Check if this is the user's first interaction."""
    try:
        from database import get_db_context
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT 1 FROM user_states WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            return row is None
    except Exception:
        return False


def _get_tenant_complaint_types(wa_id: str) -> list:
    """Get tenant-specific complaint types or return default."""
    try:
        from shared.tenancy.resolver import resolve_tenant_for_user
        from shared.tenancy.loader import get_tenant_profile
        tenant_id = resolve_tenant_for_user(wa_id)
        if tenant_id:
            profile = get_tenant_profile(tenant_id)
            if profile and hasattr(profile, 'complaint_types'):
                return profile.complaint_types
    except Exception:
        pass
    # Default complaint types for e-commerce
    return ["Damaged Product", "Wrong Item", "Delivery Issue", "Billing & Payment", "Product Quality", "Other"]


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


async def handle_b2c_message(wa_id: str, message: str, state: str, context: dict, tenant_id: str = None) -> dict:
    from services.whatsapp_sender import send_text_message, send_button_message, send_list_menu
    from . import tools, menus

    cfg = _cfg()
    message = (message or "").strip()
    context = context or {}
    
    # Resolve tenant_id for this user
    if not tenant_id:
        try:
            from database import get_request_tenant
            tenant_id = get_request_tenant()
        except Exception:
            pass
    if not tenant_id:
        try:
            from shared.tenancy.resolver import resolve_tenant_for_user
            tenant_id = resolve_tenant_for_user(wa_id)
        except Exception:
            pass

    # ── Global rule: human handover request wins over anything else ──────────
    if tools.should_escalate(message):
        return await _escalate(wa_id, cfg)

    # ── Main menu / start ─────────────────────────────────────────────────────
    if state == cfg.B2C_MAIN_MENU_STATE or not state:
        clean_msg = _clean(message)
        if clean_msg in ("main menu", "menu", "start", "hi", "hello", "hey", "show options", "options") or message in ("Main Menu", "main_menu", "menu_main"):
            menu_data = menus.get_main_menu(wa_id, tenant_id=tenant_id)
            
            # Add welcome message for first-time users
            if _is_new_user(wa_id):
                try:
                    from shared.tenancy.resolver import resolve_tenant_for_user
                    from shared.tenancy.loader import get_tenant_profile
                    tenant_id = resolve_tenant_for_user(wa_id)
                    if tenant_id:
                        profile = get_tenant_profile(tenant_id)
                        tenant_name = getattr(getattr(profile, 'brand', None), 'name', 'our service')
                    else:
                        tenant_name = "our service"
                    welcome_msg = f"👋 Welcome to *{tenant_name}*! I'm your virtual assistant.\n"
                except Exception:
                    welcome_msg = "👋 Welcome! I'm your virtual assistant.\n"
                
                if menu_data.get("type") == "buttons":
                    body = f"{welcome_msg}{menu_data.get('text', 'Here are your options:')}"
                    await send_button_message(
                        wa_id,
                        body=body,
                        buttons=menu_data.get("buttons", []),
                    )
                else:
                    body = f"{welcome_msg}{menu_data.get('body', 'What would you like to explore today?')}"
                    await send_list_menu(
                        wa_id,
                        header=menu_data.get("header", ""),
                        body=body,
                        button_text=menu_data.get("button_text", "Show Options"),
                        sections=menu_data.get("sections", []),
                    )
            else:
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
            menu_data = menus.get_main_menu(wa_id, tenant_id=tenant_id)
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
        # Meaningless / keyboard-mash input: show the menu instead of
        # throwing the noise at the RAG index (which returns unrelated answers).
        if _is_meaningless(message):
            menu_data = menus.get_main_menu(wa_id, tenant_id=tenant_id)
            if menu_data.get("type") == "buttons":
                await send_button_message(
                    wa_id,
                    body="Here are your options:",
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
            return {"status": "meaningless", "new_state": cfg.B2C_MAIN_MENU_STATE}
        # Not a menu button: fall back to the RAG pipeline for general questions.
        return await _handle_main_selection(wa_id, message, context, cfg, tenant_id=tenant_id)

    # ── Complaint: awaiting type ─────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_COMPLAINT_TYPE:
        clean = (message or "").strip().lower()
        if clean in ("cancel", "stop", "exit", "quit", "menu", "main menu", "back", "restart", "start over"):
            # Show menu automatically
            menu_data = menus.get_main_menu(wa_id, tenant_id=tenant_id)
            if menu_data.get("type") == "buttons":
                await send_button_message(
                    wa_id,
                    body="Complaint registration cancelled. What would you like to do?",
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
            return {"status": "cancelled", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

        # If user asked a new question, break out of complaint flow and answer it via RAG
        if "?" in clean or any(clean.startswith(w + " ") or clean == w for w in QUESTION_WORDS):
            context.pop("complaint_type", None)
            return await _fallback_to_rag(wa_id, message, cfg)

        # Get tenant-specific complaint types
        complaint_types = _get_tenant_complaint_types(wa_id)
        buttons = [
            {"id": f"b2c_complaint_{i}", "title": ctype}
            for i, ctype in enumerate(complaint_types)
        ]
        # Try to match the user's message to a complaint type
        complaint_type = _match_complaint_type(message, complaint_types)
        if complaint_type:
            context["complaint_type"] = complaint_type
            await send_text_message(wa_id, "Please briefly describe the issue (or type *cancel* to exit).")
            return {"status": "awaiting_description", "new_state": cfg.B2C_AWAITING_COMPLAINT_DESC, "context": context}
        await send_button_message(wa_id, "Please select the type of complaint (or type *cancel*):", buttons)
        return {"status": "awaiting_type", "new_state": cfg.B2C_AWAITING_COMPLAINT_TYPE, "context": context}

    # ── Complaint: awaiting description ───────────────────────────────────────
    if state == cfg.B2C_AWAITING_COMPLAINT_DESC:
        clean = (message or "").strip().lower()
        if clean in ("cancel", "stop", "exit", "quit", "menu", "main menu", "back"):
            context.pop("complaint_type", None)
            # Show menu automatically
            menu_data = menus.get_main_menu(wa_id, tenant_id=tenant_id)
            if menu_data.get("type") == "buttons":
                await send_button_message(
                    wa_id,
                    body="Complaint registration cancelled. What would you like to do?",
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
            return {"status": "cancelled", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": context}

        # Validate input length for complaint description
        is_valid, error_msg = _validate_input_length(message, "complaint description")
        if not is_valid:
            await send_text_message(wa_id, error_msg)
            return {"status": "invalid_input", "new_state": cfg.B2C_AWAITING_COMPLAINT_DESC, "context": context}

        if "?" in clean or any(clean.startswith(w + " ") or clean == w for w in QUESTION_WORDS):
            context.pop("complaint_type", None)
            return await _fallback_to_rag(wa_id, message, cfg)

        ctype = context.get("complaint_type", "Other")
        ticket = tools.register_b2c_complaint(wa_id, ctype, message)
        context.pop("complaint_type", None)
        
        # Validate complaint was successfully registered
        if not ticket or not str(ticket).strip():
            await send_text_message(
                wa_id,
                "❌ Sorry, I couldn't register your complaint. Please try again or contact support directly."
            )
            return {"status": "error", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": context}
        
        # Send confirmation
        await send_text_message(
            wa_id,
            f"✅ Complaint registered! Your ticket ID is {ticket}. We'll be in touch soon."
        )
        
        # Show menu for re-engagement
        menu_data = menus.get_main_menu(wa_id, tenant_id=tenant_id)
        if menu_data.get("type") == "buttons":
            await send_button_message(
                wa_id,
                body="What would you like to do next?",
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
        
        return {"status": "complaint_registered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": context}

    # ── Nutrition lookup ──────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_PRODUCT_QUERY:
        # Validate input length
        is_valid, error_msg = _validate_input_length(message, "product name")
        if not is_valid:
            await send_text_message(wa_id, error_msg)
            return {"status": "invalid_input", "new_state": cfg.B2C_AWAITING_PRODUCT_QUERY, "context": {}}
        
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
            await send_text_message(wa_id, _truncate_for_whatsapp(text))
        else:
            await send_text_message(wa_id, "Sorry, I couldn't find nutrition info for that product.")
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    # ── Recipe suggestions ────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_RECIPE_QUERY:
        # Validate input length
        is_valid, error_msg = _validate_input_length(message, "ingredient name")
        if not is_valid:
            await send_text_message(wa_id, error_msg)
            return {"status": "invalid_input", "new_state": cfg.B2C_AWAITING_RECIPE_QUERY, "context": {}}
        
        recipes = tools.get_recipe_suggestions(message)
        if recipes:
            text = "\n".join(f"- {r['title']} ({', '.join(r['ingredients'])})" for r in recipes)
            full_text = f"Here are some recipe ideas:\n{text}"
            await send_text_message(wa_id, _truncate_for_whatsapp(full_text))
        else:
            await send_text_message(wa_id, "I couldn't find recipes for that. Try another ingredient!")
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    # ── Order tracking ────────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_ORDER_ID:
        # Validate order ID format
        clean_msg = (message or "").strip()
        if clean_msg.lower() in ("recent", "latest", "all", "orders"):
            query_ref = ""
        elif not re.match(r'^ORD-\d{4,}$', clean_msg.upper()):
            await send_text_message(wa_id, "Please enter a valid Order ID (e.g., ORD-1234), or reply *recent* to view your latest orders.")
            return {"status": "invalid_input", "new_state": cfg.B2C_AWAITING_ORDER_ID, "context": {}}
        else:
            query_ref = clean_msg
        
        try:
            from backend.services.order_service import lookup_order_status
            status_text = lookup_order_status(wa_id, query_ref)
        except Exception as exc:
            logger = __import__("logging").getLogger("b2c_workflows")
            logger.error("Order lookup failed for %s: %s", wa_id, exc)
            status_text = (
                "Sorry, I couldn't look that order up right now. "
                "Please try again with your Order ID."
            )
        await send_text_message(wa_id, status_text)
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    # ── Shipping help ─────────────────────────────────────────────────────────
    if state == cfg.B2C_AWAITING_SHIPPING_QUERY:
        answer = await _kb_answer(wa_id, "What is your shipping policy?", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    # ── Unknown / stale state: fall back to RAG ───────────────────────────────
    return await _fallback_to_rag(wa_id, message, cfg)


async def _handle_main_selection(wa_id: str, message: str, context: dict, cfg, tenant_id: str = None) -> dict:
    """Handle a selection made from the B2C main menu.

    Returns a fallback to the RAG pipeline when the message is not a menu
    button (so general product/nutrition questions still get answered).
    """
    from services.whatsapp_sender import send_text_message, send_button_message, send_list_menu, send_image_message
    from . import tools, menus
    
    # Resolve tenant_id for this user
    if not tenant_id:
        try:
            from database import get_request_tenant
            tenant_id = get_request_tenant()
        except Exception:
            pass
    if not tenant_id:
        try:
            from shared.tenancy.resolver import resolve_tenant_for_user
            tenant_id = resolve_tenant_for_user(wa_id)
        except Exception:
            pass

    sel = _clean(message)

    if sel in ("new arrivals", "new releases", "menu_new_arrivals"):
        from services.whatsapp_sender import send_new_arrivals_message
        sent = await send_new_arrivals_message(wa_id)
        if not sent:
            await send_text_message(wa_id, "The new releases PDF could not be delivered right now. Please try again shortly.")
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    if sel in ("products", "b2c_products", "browse", "product", "view products", "menu_products",
               "properties", "menu_properties", "flats", "villas", "apartments", "menu_packages", "packages"):
        try:
            from services import offerings_flow
            handled = await offerings_flow.handle_offerings_action(wa_id, message, tenant_id=tenant_id)
            if handled and handled.get("handled"):
                return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}
        except Exception as e:
            logger.debug("offerings_flow fallback error: %s", e)
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
        return {"status": "answered", "new_state": cfg.B2C_AWAITING_PRODUCT_QUERY, "context": {}}

    if sel in ("nutrition", "b2c_nutrition"):
        await send_text_message(wa_id, "Which product would you like nutrition info for?")
        return {"status": "awaiting_query", "new_state": cfg.B2C_AWAITING_PRODUCT_QUERY, "context": {}}

    if sel in ("health benefits", "b2c_health_benefits", "health"):
        answer = await _kb_answer(wa_id, "What are the health benefits of your products?", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    if sel in ("product usage", "b2c_product_usage", "usage"):
        answer = await _kb_answer(wa_id, "How should I use your products? What is the recommended usage and best way to consume them?", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    # My Order: Track / Complaint
    if sel in ("track order", "b2c_track_order", "track", "track_order", "menu_track_order", "orders", "my orders", "order status"):
        await send_text_message(
            wa_id,
            "Please share your *Order ID* (e.g. ORD-1234), or reply *recent* to view your latest orders."
        )
        return {"status": "awaiting_order_id", "new_state": cfg.B2C_AWAITING_ORDER_ID, "context": {}}

    if sel in ("raise complaint", "b2c_complaint", "complaint", "menu_complaint"):
        await send_text_message(wa_id, "Please select the type of complaint.")
        return {"status": "awaiting_complaint_type", "new_state": cfg.B2C_AWAITING_COMPLAINT_TYPE, "context": {}}

    # Help: Shipping / Recipes / Human handover
    if sel in ("shipping", "b2c_shipping", "shipping & returns", "return & refund policy",
               "return policy", "returns", "menu_return_policy"):
        answer = await _kb_answer(wa_id, "What is your shipping policy, return policy, and refund policy?", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    if sel in ("company policies", "menu_about"):
        answer = await _kb_answer(wa_id, "Tell me about your company and company policies.", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    if sel in ("discounts & offers", "menu_discounts", "offers", "discounts"):
        answer = await _kb_answer(wa_id, "What discounts and offers do you currently have?", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    if sel in ("gst info", "menu_gst", "gst"):
        answer = await _kb_answer(wa_id, "What is your GST number and tax/invoice details?", tenant_id)
        await send_text_message(wa_id, _truncate_for_whatsapp(answer))
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}

    if sel in ("recipes", "b2c_recipes"):
        await send_text_message(wa_id, "Which ingredient or product would you like recipe ideas for?")
        return {"status": "awaiting_query", "new_state": cfg.B2C_AWAITING_RECIPE_QUERY, "context": {}}

    if sel in ("talk to human", "b2c_human", "human", "menu_human"):
        return await _escalate(wa_id, cfg)

    if sel in ("view cart", "menu_view_cart"):
        answer = await _kb_answer(wa_id, "Show me the items in my cart.", tenant_id)
        await send_text_message(wa_id, answer)
        return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE}

    # Check if message is an interactive offering action (e.g. prod_*, cat_*, book_prod_*)
    try:
        from services import offerings_flow
        handled = await offerings_flow.handle_offerings_action(wa_id, message, tenant_id=tenant_id)
        if handled and handled.get("handled"):
            return {"status": "answered", "new_state": cfg.B2C_MAIN_MENU_STATE, "context": {}}
    except Exception as e:
        logger.debug("offerings_flow pre-rag error: %s", e)

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
    # Sanitize the message
    message = _sanitize_kb_query(message)
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
        kb_chunks = []  # Store chunks for fallback
        try:
            import json as _json
            from kb.services.rag import search_kb_faiss
            from database import get_db_context
            hits = search_kb_faiss(message, limit=5, tenant_id=tid)
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
                history_turns = []
                try:
                    from database import get_recent_history
                    history_turns = get_recent_history(wa_id, limit=3, ttl_minutes=30)
                except Exception:
                    pass
                try:
                    llm_res = await _generate_ollama_dynamic_response(
                        sys_prompt, message, combined_context, tenant_id=tid, conversation_history=history_turns
                    )
                    if llm_res and llm_res.get("answer"):
                        answer = _append_signature(llm_res["answer"], tid)
                        interactive = llm_res.get("interactive")
                except Exception as e:
                    logger.warning(f"LLM synthesis failed for KB chunks: {e}")
                    # Fallback: use raw KB chunks if LLM fails but we have relevant content
                    if kb_chunks:
                        answer = "\n\n".join(kb_chunks)
                        logger.info(f"Using raw KB chunks as fallback for {wa_id}")
        except Exception as e:
            logger.warning(f"KB index lookup failed: {e}")

    if not answer:
        try:
            from database import record_unanswered_query
            record_unanswered_query(
                tenant_id=tid or "default",
                query=message,
                wa_id=wa_id,
                reason="uncertain_fallback",
                confidence_score=0.0,
            )
        except Exception as e:
            logger.debug(f"Knowledge gap recording failed: {e}")
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


async def _kb_answer(wa_id: str, query: str, tenant_id: str | None = None) -> str:
    """Answer an informational query via document indexes with LLM synthesis."""
    # Sanitize the query
    query = _sanitize_kb_query(query)
    
    # Resolve tenant_id if not provided
    if tenant_id is None:
        try:
            from shared.tenancy.resolver import resolve_tenant_for_user
            tenant_id = resolve_tenant_for_user(wa_id)
        except Exception:
            tenant_id = None
    
    try:
        from faq.service import handle_faq_query
        res = await handle_faq_query({"message": query, "wa_id": wa_id, "tenant_id": tenant_id})
        if res and res.get("answer") and res.get("answer").strip():
            return res["answer"]
    except Exception as e:
        logger.warning(f"FAQ index lookup for '{query}' failed: {e}")

    try:
        import json as _json
        from kb.services.rag import search_kb_faiss
        from database import get_db_context
        hits = search_kb_faiss(query, limit=3, tenant_id=tenant_id)
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
            brand = _brand_context(tenant_id)
            sys_prompt = _render_prompt(SYSTEM_PROMPT_TEMPLATE, brand)
            combined_context = "\n\n---\n\n".join(kb_chunks)
            history_turns = []
            try:
                from database import get_recent_history
                history_turns = get_recent_history(wa_id, limit=3, ttl_minutes=30)
            except Exception:
                pass
            llm_res = await _generate_ollama_dynamic_response(
                sys_prompt, query, combined_context, tenant_id=tenant_id, conversation_history=history_turns
            )
            if llm_res and llm_res.get("answer"):
                return _append_signature(llm_res["answer"], tenant_id)
    except Exception as e:
        logger.warning(f"KB index lookup for '{query}' failed: {e}")

    return (
        "I'm not certain about that. Would you like to browse our products, "
        "check nutrition info, or talk to a human agent?"
    )


def _match_complaint_type(message: str, complaint_types: list | None = None) -> str | None:
    """Return a normalized complaint type if the message selects one.
    
    Uses fuzzy matching against the provided complaint_types list.
    If no list provided, uses default e-commerce types.
    """
    if not message:
        return None
    
    complaint_types = complaint_types or ["Damaged Product", "Wrong Item", "Delivery Issue", "Billing & Payment", "Product Quality", "Other"]
    lowered = message.strip().lower()
    
    # Direct match
    for ctype in complaint_types:
        if lowered == ctype.lower():
            return ctype
    
    # Keyword-based matching
    for ctype in complaint_types:
        ctype_lower = ctype.lower()
        # Check if message contains keywords from the complaint type
        ctype_keywords = [w for w in ctype_lower.split() if len(w) > 2]  # Skip short words
        if any(kw in lowered for kw in ctype_keywords):
            return ctype
    
    # For "Other" - match various forms
    if any(word in lowered for word in ["other", "miscellaneous", "general"]):
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
