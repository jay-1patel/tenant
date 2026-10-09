import re
import uuid

from ..database import (
    get_recent_history, save_chat, update_session_inbound,
    search_products, get_products_by_category,
)
from .brain import process_with_brain_async, generate_ollama_dynamic_response, _build_system_prompt, _retrieve_context, get_brand_name
from .orchestrator import (
    get_conversation_context, update_conversation_context,
    enhance_query_with_context, should_trigger_fallback_menu,
    get_context_aware_buttons, extract_product_context_from_response
)
from .fuzzy_matcher import handle_fuzzy_correction
from . import cart as cart_service
from .whatsapp import (
    send_product_with_image, send_image,
    send_whatsapp_message, send_menu, _handle_menu_selection,
    send_with_main_menu_fallback, send_main_menu, send_interactive_buttons,
)
from .bot_config import get_response_settings
from .menu_router import (
    parse_interactive_message, should_show_main_menu, should_enter_ai_mode,
    get_route_action, is_menu_keyword, is_catalog_keyword, get_current_state,
    set_state, reset_to_main_menu, get_user_lang, UserState,
    build_main_menu_list, build_product_catalog_list, build_language_buttons,
    build_product_buttons, build_main_menu_buttons,
)
from routing.config import logger

# ── DYNAMIC DISCOUNTS ────────────────────────────────────────────────────────
# Builds the DISCOUNTS reply from the actual KB/FAQ database instead of a fixed
# hardcoded string. Each discount fact lives in faq_dataset:
#   general_qa.txt (TROOFIRST, free shipping), shipping_policy.txt (festival
#   free-shipping codes), moq_creditperiod.txt (bulk/volume terms) and
#   troogood_discount_flyer.pdf (current product offers table).
# The reply is composed deterministically from DB rows - no LLM - so it can
# never hallucinate offers, and any KB update automatically reflects live.


def _qa_answer(text: str) -> str:
    """Return the last 'A:' answer block of a Q&A FAQ chunk (or raw text)."""
    matches = re.findall(r"(?ms)^\s*A\s*:\s*(.+?)(?=\nQ\s*:|\Z)", text or "")
    if matches:
        return matches[-1].strip()
    return (text or "").strip()


def _parse_flyer_offers(content: str) -> list:
    """Parse current product offers from the flyer table chunk.

    Each product block looks like:
        <Name> MRP Rs.<mrp>
        <description with sale price> Rs.<sale>
        <Z>% OFF
    """
    offers = []
    lines = [l.strip() for l in (content or "").splitlines() if l.strip()]
    for i, line in enumerate(lines):
        m = re.match(r"^(.+?)\s*MRP Rs\.(\d+)$", line)
        if not m:
            continue
        name, mrp = m.group(1), int(m.group(2))
        sale = off = None
        for j in range(i + 1, min(i + 4, len(lines))):
            sm = re.search(r"Rs\.(\d+)$", lines[j])
            om = re.match(r"^(\d+)% OFF", lines[j])
            if sm and sale is None:
                sale = int(sm.group(1))
            if om:
                off = int(om.group(1))
                break
        offers.append({"name": name, "mrp": mrp, "sale": sale, "off": off})
    return offers


def _build_dynamic_discounts() -> str | None:
    """Compose the discounts reply from faq_dataset. None if DB unavailable."""
    try:
        from ..database import get_db_context
        with get_db_context() as conn:
            first_order = fs_answer = festival_answer = bulk_answer = None
            flyer_table = ""
            flyer_table_content = ""
            rows = conn.execute(
                """
                SELECT source_file, content_type, content FROM faq_dataset
                WHERE module='faq' AND (
                    content LIKE '%TROOFIRST%'
                    OR (content LIKE '%free shipping%' AND content LIKE '%499%')
                    OR content LIKE '%UTRAYANFREE%'
                    OR (content LIKE '%10,000%' AND content LIKE '%volume-based pricing%')
                    OR source_file='troogood_discount_flyer.pdf'
                )
                ORDER BY id
                """
            ).fetchall()
            for src, content_type, content in rows:
                if src == "troogood_discount_flyer.pdf":
                    if content_type == "table" or (not flyer_table and content_type != "table"):
                        flyer_table_content = content
                        flyer_table = content_type or "table"
                    continue
                content_lc = content.lower()
                if not first_order and "troofirst" in content_lc:
                    first_order = _qa_answer(content)
                if not fs_answer and "free shipping" in content_lc and "499" in content_lc:
                    fs_answer = _qa_answer(content)
                if not festival_answer and "utrayanfree" in content_lc:
                    festival_answer = _qa_answer(content)
                if not bulk_answer and "volume-based pricing" in content_lc and "10,000" in content_lc:
                    bulk_answer = _qa_answer(content)
    except Exception as e:
        logger.error(f"build_dynamic_discounts failed: {e}")
        return None

    if not any([first_order, fs_answer, festival_answer, bulk_answer]):
        return "🎁 *Discounts & Offers*\n\nCurrently, there is no discount or offer available. Please check back later!"

    lines = ["🎁 *Discounts & Offers*"]
    if first_order:
        lines.append(f"• *First order:* {first_order}")
    if fs_answer:
        lines.append(f"• *Free shipping:* {fs_answer}")
    if festival_answer:
        lines.append("*Festival free-shipping codes:*")
        for code_line in festival_answer.replace("Yes—free Standard Shipping on ", "").splitlines():
            if code_line.strip().startswith("Note:"):
                lines.append(f"• {code_line.strip()}")
            else:
                lines.append(f"  {code_line.strip()}")
    offers = _parse_flyer_offers(flyer_table_content) if flyer_table_content else []
    offer_count = sum(1 for o in offers if o.get("sale") and o.get("off") is not None)
    if offer_count >= 5:
        lines.append("*Current offers:*")
        for o in offers:
            if o["mrp"] and o["sale"] and o["off"] is not None:
                lines.append(f"• {o['name']}: MRP ₹{o['mrp']} → ₹{o['sale']} ({o['off']}% OFF)")
    if bulk_answer:
        lines.append(f"*Bulk orders* (above ₹10,000): {bulk_answer}")
    return "\n".join(lines)


def _is_informational_query(text: str) -> bool:
    """Detect if user is asking for specific information (not browsing products).
    Returns True for queries like 'nutrition facts', 'ingredients', 'price', etc.
    Returns False for browsing intent like 'show me products', 'view catalogue'.
    """
    if not text:
        return False

    informational_keywords = [
        "nutrition", "nutritional", "ingredients", "composition", "details",
        "specifications", "specs", "facts", "information", "benefits",
        "price", "cost", "rate", "mrp", "amount", "how much",
        "calories", "protein", "carbs", "fat", "fiber", "sugar",
        "contains", "made of", "formula", "description",
        "expiry", "expire", "shelf life", "storage",
        "allerg", "warning", "caution", "side effect"
    ]

    browsing_keywords = [
        "show", "show me", "view", "see", "display", "browse",
        "catalog", "catalogue", "collection", "list", "range",
        "products", "items", "what do you have", "what are",
        "available", "stock", "in store"
    ]

    text_lower = text.lower().strip()

    # Check for browsing keywords first (they take precedence)
    for kw in browsing_keywords:
        if kw in text_lower:
            return False

    # Check for informational keywords
    for kw in informational_keywords:
        if kw in text_lower:
            return True

    return False


def _match_support_intent(text: str) -> bool:
    """Detect B2C support trigger intents in free text.

    Recognises the order-tracking and complaint-registration triggers so the
    transactional workflows can start from a typed message as well as from a
    button click.
    """
    if not text:
        return False
    t = text.lower().strip()

    track_keywords = [
        "track order", "track my order", "order status", "order tracking",
        "where is my order", "where's my order", "track order status",
    ]
    complaint_keywords = [
        "complaint", "raise a complaint", "file a complaint",
        "register a complaint", "report a problem", "i have a complaint",
        "i want to complain", "complaint about",
    ]

    return any(k in t for k in track_keywords) or any(k in t for k in complaint_keywords)


def _is_image_request(text: str) -> bool:
    """Detect if the user is asking to SEE a product image/photo.
    Matches 'give me a photo of chikki', 'chikki photo', 'show the image', etc.
    Generic — based only on image-related words, not on any product domain.
    """
    if not text:
        return False
    t = text.lower().strip()
    if not any(kw in t for kw in
               ["image", "images", "photo", "photos", "picture", "pictures",
                "pic", "snapshot", "visual"]):
        return False
    # Exclude questions about the meaning/description of an image
    if any(p in t for p in ["what does", "what is", "meaning", "describe",
                            "explain", "definition", "how to"]):
        return False
    return True


# Generic stopwords only — NO product/variant-specific words here, so the same
# matching works for any catalogue (chikki today, something else tomorrow).
_IMAGE_QUERY_STOPWORDS = {
    "give", "gimme", "me", "the", "of", "send", "show", "please", "kindly",
    "photo", "image", "picture", "pic", "pics", "snapshot", "visual",
    "want", "need", "see", "can", "could", "you", "your", "a", "an", "is",
    "for", "and", "with", "sample", "one", "any", "have", "get", "share",
    "attach", "its", "it", "would", "should", "do", "did", "does", "some",
    "more", "about", "what", "which", "them", "their", "there", "let",
}


def _all_products_with_images() -> list:
    """Active products (by sort order) that have a usable media URL."""
    from ..database import get_db_context
    try:
        with get_db_context() as conn:
            rows = conn.execute(
                "SELECT * FROM products "
                "WHERE is_active = 1 AND media_url IS NOT NULL "
                "ORDER BY sort_order ASC, id ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to list products with images: {e}")
        return []


def _find_product_image(text: str) -> dict | None:
    """Find an active product with an image matching the query.

    Fully data-driven — no hardcoded product/variant keywords. It scores the
    query's content words against each product's name/description/ingredients, so it
    works for any catalogue. A generic request with no product words returns
    the featured product (first in sort order) that has an image.
    """
    t = (text or "").lower().strip()
    words = [w for w in re.findall(r"[a-z]{3,}", t) if w not in _IMAGE_QUERY_STOPWORDS]

    products = _all_products_with_images()
    if not products:
        return None

    def _blob(p: dict) -> str:
        return " ".join(str(p.get(k) or "") for k in
                        ("name", "short_description", "description", "ingredients", "category")).lower()

    def _word_in_blob(w: str, blob: str) -> bool:
        # 1) Direct match, or prefix match for plurals/typos ("chikkis" -> "chikki")
        if w in blob:
            return True
        blob_words = blob.split()
        if len(w) >= 4:
            for pw in blob_words:
                if len(pw) >= 4 and (pw.startswith(w) or w.startswith(pw)):
                    return True
        # 2) Fuzzy match for misspellings ("chickis" -> "chikki")
        if len(w) >= 5:
            from difflib import SequenceMatcher
            for pw in blob_words:
                if len(pw) >= 5 and SequenceMatcher(None, w, pw).ratio() >= 0.75:
                    return True
        return False

    def _score(p: dict) -> int:
        name_l = (p.get("name") or "").lower()
        blob = _blob(p)
        return sum(3 if w in name_l else (1 if _word_in_blob(w, blob) else 0) for w in words)

    if not words:
        return products[0]  # generic request → featured product

    best = max(products, key=_score)
    return best if _score(best) > 0 else None


def _strip_disclaimers(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"(?i)I(?:'m| am) not a medical professional[^.\n!?—]*[.\n!?—]*",
        r"(?i)consult(?:ing)? (?:your|a) doctor[^.\n!?—]*[.\n!?—]*",
        r"(?i)(?:please )?(?:consult|check with) (?:your|a) (?:doctor|healthcare professional)[^.\n!?—]*[.\n!?—]*",
        r"(?i)I(?:'ll| will) check with our team[^.\n!?—]*[.\n!?—]*",
        r"(?i)(?:I|We) can only share business-related information[^.\n!?—]*[.\n!?—]*",
        r"(?i)I(?:’|')d recommend[^.\n!?—]*[.\n!?—]*",
        r"(?i)Would you like me to check for other[^.\n!?—]*[.\n!?—]*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _strip_source_filename_references(text: str) -> str:
    if not text:
        return text
    text = re.sub(
        r"(?i)^\s*\*[^*\n]*?\.(?:pdf|docx?|txt|csv|xlsx?)\*\s*(?:\n|$)",
        "",
        text,
        count=1,
    )
    text = re.sub(
        r"(?i)^\s*\[[^\]\n]*?\.(?:pdf|docx?|txt|csv|xlsx?)\]\s*",
        "",
        text,
        count=1,
    )
    return text


def _clean_response(text: str) -> str:
    """
    Clean and smart-truncate response text.

    FIX: Changed from 400 to 3500 character limit and implemented smart truncation.
    WhatsApp allows up to 4096 characters per message, so 3500 provides a safe buffer.

    Smart truncation finds natural sentence boundaries (., ?, !, \n) instead of
    cutting mid-word, ensuring responses end at complete sentences.

    Args:
        text: Raw response text to clean and truncate

    Returns:
        Cleaned and truncated text
    """
    if not text:
        return ""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = _strip_source_filename_references(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _strip_disclaimers(text)
    text = text.strip()

    # FIX: Increased from 400 to 3500 characters (WhatsApp allows up to 4096)
    max_chars = get_response_settings().get("max_reply_chars", 3500)

    if len(text) > max_chars:
        # Smart truncation: find natural sentence boundaries
        # Look for sentence ending characters in the last 200 characters
        boundary_chars = ['.', '?', '!', '\n']
        text_to_check = text[max_chars - 200:max_chars]

        # Find the last occurrence of any boundary character
        last_boundary = -1
        for char in boundary_chars:
            pos = text_to_check.rfind(char)
            if pos > last_boundary:
                last_boundary = pos

        if last_boundary != -1:
            # Truncate at the boundary (position is relative to text_to_check)
            truncate_at = (max_chars - 200) + last_boundary + 1
            text = text[:truncate_at].strip()
        else:
            # No natural boundary found, fall back to hard truncation with ellipse
            text = text[:max_chars - 3].strip() + "..."

    return text


def _product_text_for_filter(products: list) -> str:
    """Aggregate searchable product text (description, short desc, ingredients) to judge
    whether a given piece of info (allergen/package/nutrition) is actually present."""
    import json as _json
    chunks = []
    for p in products or []:
        chunks.append(str(p.get("description") or ""))
        chunks.append(str(p.get("short_description") or ""))
        chunks.append(str(p.get("category") or ""))
        try:
            ingredients = _json.loads(p.get("ingredients") or "[]")
            if isinstance(ingredients, list):
                chunks.append(" ".join(str(t) for t in ingredients))
        except Exception:
            pass
    return " ".join(chunks).lower()


_CONTENT_GATED_ACTIONS = {
    "allergen": (
        re.compile(r"\b(allerg(en|ens?|ic|y)|gluten|peanut|milk|soy|lactose|tree ?nuts?|nuts?|dairy|egg)\b"),
        re.compile(r"\b(allerg(en|ens?|ic|y)|gluten|peanut|milk|soy|lactose|dairy|egg)\b"),
    ),
    "package": (
        re.compile(r"\b(pack(?:age|aging| size)?|weight|quantity|piece|box|jar|bottle|pouch|net\s*(?:wt|weight))\b|\b\d+\s*(g|gm|grams?|kg|kgs|ml|l|litre)\b"),
        re.compile(r"\b(pack(?:age|aging| size)?|weight|quantity|piece|box|jar|bottle|pouch|net\s*(?:wt|weight))\b|\b\d+\s*(g|gm|grams?|kg|kgs|ml|l|litre)\b"),
    ),
    "nutrition": (
        re.compile(r"\b(nutrition|calorie|calories|protein|carb(?:ohydrate)?s?|fat|fibre|fiber|sugar|per\s*100|serving|ingredient)\b"),
        re.compile(r"\b(nutrition|calorie|calories|protein|carb(?:ohydrate)?|fat|fibre|fiber|sugar|per\s*100|serving|ingredient)\b"),
    ),
}


def _filter_actions_present(dynamic_actions: list, products: list) -> list:
    """Drop predicted next-action buttons whose content is not present in the
    matched product data (e.g. 'View Package' or 'Check Allergens' when the
    product description has no such information). Unknown/generic actions are kept.

    Each category maps to a tuple: (action_match_regex, content_match_regex).
    The action regex decides whether a predicted button relates to that category;
    the content regex checks whether the matched product actually carries such info.
    """
    if not dynamic_actions:
        return dynamic_actions
    product_text = _product_text_for_filter(products)
    # Extract matched product name too, since package/description often mirrors it
    product_names = " ".join(str(p.get("name") or "") for p in (products or [])).lower()

    det = product_text + " " + product_names

    filtered = []
    for action in dynamic_actions:
        if not isinstance(action, dict):
            continue
        combined = (f"{action.get('id') or ''} {action.get('title') or ''}"
                    .replace("_", " ").replace("-", " ").lower())

        present = True
        for category, (action_re, content_re) in _CONTENT_GATED_ACTIONS.items():
            if action_re.search(combined):
                present = bool(content_re.search(det))
                break
        if present:
            filtered.append(action)
        else:
            logger.info(f"ACTION_FILTERED | dropped '{action.get('id')}' ({action.get('title')}) - content not present")
    return filtered


def _is_valid_phone_number(wa_id: str) -> bool:
    if not wa_id:
        return False
    import re
    digits = re.sub(r"\D", "", wa_id.strip())
    return len(digits) >= 10 and len(digits) <= 15


def _result(
    answer: str,
    route: str = "kb",
    interactive: dict = None,
    media_url: str = None,
    media_type: str = None,
    whatsapp_sent: bool = False,
) -> dict:
    return {
        "answer": answer or "",
        "route": route,
        "interactive": interactive,
        "success": bool(answer),
        "media_url": media_url,
        "media_type": media_type,
        "whatsapp_sent": whatsapp_sent,
    }


def _public_image(url: str) -> str | None:
    if not url:
        return None
    try:
        from .whatsapp import resolve_public_media_url
        return resolve_public_media_url(url)
    except Exception as e:
        logger.debug(f"_public_image failed: {e}")
        return url if str(url).startswith("http") else None


async def handle_kb_query(
    wa_id: str,
    message: str,
    sender_name: str = "",
    update_session: bool = True,
    raw_message: dict = None,
) -> dict:
    """
    Central message handler with menu state machine.
    
    Flow:
    1. Parse incoming message (text or interactive)
    2. Check menu keywords → show main menu
    3. Route by interactive ID or state
    4. Fall back to brain/RAG pipeline
    5. Always attach Main Menu button to responses
    """
    can_send_whatsapp = _is_valid_phone_number(wa_id)
    
    # Parse the incoming message (handles text, button_reply, list_reply)
    parsed_msg = parse_interactive_message(raw_message or {"type": "text", "text": {"body": message}})
    text = parsed_msg.get("text", message)
    msg_id = parsed_msg.get("id") or ""
    
    logger.info(f"PROCESSING | from={wa_id} | can_send={can_send_whatsapp} | state={get_current_state(wa_id)} | msg={text[:200]} | id={msg_id}")

    if update_session:
        update_session_inbound(wa_id)

    # ── Priority 0: Fuzzy Match Typo Recovery (NEW FEATURE) ─────────────────
    # Check if query needs fuzzy correction before other processing
    fuzzy_correction = handle_fuzzy_correction(text, wa_id)
    if fuzzy_correction and fuzzy_correction.get("needs_correction"):
        correction_message = fuzzy_correction.get("message", "")
        correction_buttons = fuzzy_correction.get("buttons", [])

        # Build interactive response with correction suggestions
        interactive = {
            "type": "buttons",
            "header": "Did you mean?",
            "body": correction_message,
            "footer": "Tap a product or search as typed",
            "buttons": [{"id": btn.get("id"), "title": btn.get("title")} for btn in correction_buttons]
        }

        sent = False
        if can_send_whatsapp:
            logger.info(f"FUZZY_CORRECTION | to={wa_id} | confidence={fuzzy_correction.get('confidence', 0):.2f}")
            try:
                sent = bool(send_interactive_buttons(
                    to=wa_id,
                    body_text=correction_message,
                    buttons=interactive["buttons"],
                ))
            except Exception as e:
                logger.error(f"Failed to send fuzzy correction to {wa_id}: {e}")

        response_text = correction_message
        return _result(response_text, route="fuzzy_correction", interactive=interactive, whatsapp_sent=sent)

    # ── Priority 1: Menu Keywords → Always show Main Menu ─────────────────────
    if should_show_main_menu(text, parsed_msg, wa_id):
        reset_to_main_menu(wa_id)
        interactive = build_main_menu_list(wa_id)
        sent = False
        if can_send_whatsapp:
            logger.info(f"SENDING_INTERACTIVE | to={wa_id} | action=MAIN_MENU | type=list")
            try:
                sent = bool(send_main_menu(wa_id))
            except Exception as e:
                logger.error(f"Failed to send main menu to {wa_id}: {e}")
        response_text = interactive.get("body") or "Main Menu"
        return _result(response_text, route="menu", interactive=interactive, whatsapp_sent=sent)

    # ── Priority 1b: B2C Customer Support Workflows ─────────────────────────
    # Transactional flows (Order Tracking, Complaint Registration) are handled by
    # the customer_chatbot package. Route to it when:
    #   - the user is mid-workflow (support FSM state), OR
    #   - the incoming button id is a support action (action_track_order /
    #     action_complaint / complaint_*), OR
    #   - the message matches a support intent (track_order / raise_complaint).
    #
    # The customer_chatbot package is optional. If it is not installed/importable,
    # fall through to the standard KB routing below instead of erroring out.
    try:
        from customer_chatbot.workflows import (  # type: ignore
            handle_order_tracking,
            handle_complaint_registration,
        )
        from customer_chatbot.config import SUPPORT_STATES  # type: ignore
        _CUSTOMER_CHATBOT_AVAILABLE = True
    except Exception:
        _CUSTOMER_CHATBOT_AVAILABLE = False

    if _CUSTOMER_CHATBOT_AVAILABLE:
        try:
            _support_state = get_current_state(wa_id)
            _is_support_state = _support_state in SUPPORT_STATES.values()
            _is_support_trigger = (
                msg_id in ("action_track_order", "action_complaint")
                or msg_id.startswith("complaint_")
                or _match_support_intent(text)
            )

            if _is_support_state or _is_support_trigger:
                logger.info(f"SUPPORT_ROUTE | wa_id={wa_id} | state={_support_state} | id={msg_id} | msg={text[:80]}")

                # Order tracking flow.
                order_result = handle_order_tracking(
                    wa_id=wa_id,
                    text=text,
                    msg_id=msg_id,
                    parsed_msg=parsed_msg,
                    can_send_whatsapp=can_send_whatsapp,
                )
                if order_result is not None:
                    return _result(
                        order_result.get("answer", ""),
                        route=order_result.get("route", "order_tracking"),
                        interactive=order_result.get("interactive"),
                        media_url=order_result.get("media_url"),
                        media_type=order_result.get("media_type"),
                        whatsapp_sent=order_result.get("whatsapp_sent", False),
                    )

                # Complaint registration flow.
                complaint_result = handle_complaint_registration(
                    wa_id=wa_id,
                    text=text,
                    msg_id=msg_id,
                    parsed_msg=parsed_msg,
                    can_send_whatsapp=can_send_whatsapp,
                )
                if complaint_result is not None:
                    return _result(
                        complaint_result.get("answer", ""),
                        route=complaint_result.get("route", "complaint"),
                        interactive=complaint_result.get("interactive"),
                        media_url=complaint_result.get("media_url"),
                        media_type=complaint_result.get("media_type"),
                        whatsapp_sent=complaint_result.get("whatsapp_sent", False),
                    )
        except Exception as e:
            logger.error(f"customer_chatbot workflow routing failed for {wa_id}: {e}")

    # ── Priority 2: Route by Action ───────────────────────────────────────────
    action = get_route_action(text, parsed_msg, wa_id)
    # get_route_action may inject id from numbered text-menu replies
    msg_id = parsed_msg.get("id") or msg_id or ""
    if parsed_msg.get("title") and msg_id and not text:
        text = parsed_msg.get("title")
    logger.info(f"ROUTE_ACTION | wa_id={wa_id} | action={action} | id={msg_id}")

    # ── PRODUCTS: Send the product list (by category) ──────────────────────
    if action == "PRODUCTS":
        set_state(wa_id, UserState.BROWSING_CATEGORIES)
        sent = False
        if can_send_whatsapp:
            logger.info(f"SENDING_PRODUCTS | to={wa_id} | action=PRODUCTS")
            try:
                from .whatsapp import send_products_by_category
                sent = bool(send_products_by_category(wa_id))
            except Exception as e:
                logger.error(f"Failed to send products list to {wa_id}: {e}")
        response_text = "📋 Here are our products."
        return _result(response_text, route="products", interactive=None, whatsapp_sent=sent)

    # ── CATALOG: Send the product catalogue PDF ─────────────────────────────
    if action == "CATALOG":
        set_state(wa_id, UserState.BROWSING_CATEGORIES)
        sent = False
        if can_send_whatsapp:
            logger.info(f"SENDING_CATALOGUE | to={wa_id} | action=CATALOG")
            try:
                from .whatsapp import send_catalogue_pdf
                from shared.tenancy.resolver import resolve_tenant_for_user
                sent = bool(send_catalogue_pdf(wa_id, tenant_id=resolve_tenant_for_user(wa_id)))
            except Exception as e:
                logger.error(f"Failed to send catalogue PDF to {wa_id}: {e}")
        response_text = "📄 Sent you the brochure."
        return _result(response_text, route="catalog", interactive=None, whatsapp_sent=sent)

    if action == "NEW_ARRIVALS":
        set_state(wa_id, UserState.MAIN_MENU)
        if can_send_whatsapp:
            try:
                from .whatsapp import send_new_arrivals_pdf
                sent = bool(send_new_arrivals_pdf(wa_id))
            except Exception as e:
                logger.error(f"Failed to send new arrivals PDF: {e}")
                sent = False
            if sent:
                return _result(
                    "📄 Sent you the new releases PDF.",
                    route="new_arrivals_pdf",
                    interactive=None,
                    whatsapp_sent=True,
                )
        try:
            from ..database import list_products
            arrivals = list_products(category="new_arrival", limit=20)
            if arrivals:
                lines = [f"*New Releases*"]
                for a in arrivals:
                    price = f" - {a['price']}" if a.get("price") else ""
                    lines.append(f"• {a['name']}{price}")
                    if a.get("description"):
                        lines.append(f"  {a['description'][:100]}")
                response_text = "\n".join(lines)
            else:
                response_text = "No new releases yet. Check back soon!"
        except Exception as e:
            logger.error(f"Failed to fetch new arrivals: {e}")
            response_text = "No new releases yet. Check back soon!"
        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="new_arrivals", interactive=build_main_menu_buttons(), whatsapp_sent=bool(can_send_whatsapp))

    if action == "SERVICE_ENQUIRY":
        set_state(wa_id, UserState.MAIN_MENU)
        try:
            from backend.services.service_answers import answer_for_text
            from shared.tenancy.resolver import resolve_tenant_for_user
            response_text = answer_for_text(wa_id, "our services", tenant_id=resolve_tenant_for_user(wa_id))
        except Exception as e:
            logger.error(f"Failed to list tenant services for {wa_id}: {e}")
            response_text = None
        response_text = response_text or "We don't have any services listed right now. Please contact our team for details."
        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="service_enquiry", interactive=None, whatsapp_sent=bool(can_send_whatsapp))

    # ── CATALOG_FAQ: Show catalogue from FAQ ──────────────────────────────────
    if action == "CATALOG_FAQ":
        set_state(wa_id, UserState.MAIN_MENU)
        try:
            from ..database import get_db_context
            with get_db_context() as conn:
                rows = conn.execute(
                    "SELECT content, source_file FROM faq_dataset WHERE content LIKE '%catalog%' OR content LIKE '%product%' OR source_file LIKE '%catalog%' LIMIT 5"
                ).fetchall()
            if rows:
                parts = [f"*Product Brochure*"]
                for r in rows:
                    parts.append(f"\n{r['content'][:200]}")
                response_text = "\n".join(parts)
            else:
                response_text = "Browse our products using 'View Products' from the menu!"
        except Exception as e:
            logger.error(f"Failed to fetch catalogue FAQ: {e}")
            response_text = "Browse our products using 'View Products' from the menu!"
        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="catalogue_faq", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── RETURN_POLICY: Use brain pipeline for natural answers ───────────────
    if action == "RETURN_POLICY":
        set_state(wa_id, UserState.MAIN_MENU)
        # Use brain pipeline to generate natural answer about return policy
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        return_query = "What is your return policy, refund policy, and exchange policy?"
        brain_result = await process_with_brain_async(return_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="return_policy", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── SHIPPING_POLICY: Use brain pipeline for shipping answers ─────
    if action == "SHIPPING_POLICY":
        set_state(wa_id, UserState.MAIN_MENU)
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        shipping_query = "What are your shipping options, delivery timelines, and shipping charges?"
        brain_result = await process_with_brain_async(shipping_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="shipping_policy", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── PRIVACY_POLICY / TERMS_CONDITIONS / CONTACT_SUPPORT: policy pipeline ──
    if action in ("PRIVACY_POLICY", "TERMS_CONDITIONS", "CONTACT_SUPPORT"):
        set_state(wa_id, UserState.MAIN_MENU)
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        policy_queries = {
            "PRIVACY_POLICY": "What is your privacy policy — how do you handle personal data?",
            "TERMS_CONDITIONS": "What are your terms and conditions of use?",
            "CONTACT_SUPPORT": "How can I contact your support team — WhatsApp number, email, and hours?",
        }
        policy_query = policy_queries[action]
        brain_result = await process_with_brain_async(policy_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route=action.lower(), interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── ABOUT_COMPANY: Use brain pipeline for natural answers ─────
    if action == "ABOUT_COMPANY":
        set_state(wa_id, UserState.MAIN_MENU)
        # Let the brain pipeline handle this with retrieved context
        # This will generate natural, conversational answers using KB as source
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        # Override the user message to focus on company info
        company_query = f"Tell me about {get_brand_name(wa_id)} company - who founded it, when was it founded, what's their mission, and what makes them special?"
        brain_result = await process_with_brain_async(company_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="about_company", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── PAYMENT_TERMS: Use brain pipeline for natural answers ─────
    if action == "PAYMENT_TERMS":
        set_state(wa_id, UserState.MAIN_MENU)
        # Use brain pipeline to generate natural answer about payment terms
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        payment_query = "What are your payment terms, payment methods, and conditions?"
        brain_result = await process_with_brain_async(payment_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="payment_terms", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── PRODUCT_INFO: Use brain pipeline for natural answers ─────
    if action == "PRODUCT_INFO":
        set_state(wa_id, UserState.MAIN_MENU)
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        info_query = "Tell me about your products - ingredients, nutrition information, flavours, and specifications."
        brain_result = await process_with_brain_async(info_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="product_info", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── DISCOUNTS: Dynamic, composed from the actual KB/FAQ database ──────────
    # Built deterministically from faq_dataset rows (general_qa.txt TROOFIRST,
    # free shipping, shipping_policy.txt festival codes, flyer product offers,
    # bulk/volume terms) so offers always mirror the stored KB and never get
    # hallucinated by the LLM.
    if action == "DISCOUNTS":
        set_state(wa_id, UserState.MAIN_MENU)
        response_text = _build_dynamic_discounts()
        if not response_text:
            response_text = "🎁 *Discounts & Offers*\n\nCurrently, there is no discount or offer available. Please check back later!"

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="discounts", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── GST_INFO: Use brain pipeline for natural answers ─────
    if action == "GST_INFO":
        set_state(wa_id, UserState.MAIN_MENU)
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        gst_query = "What is your GST number, GST registration details, and tax invoice information?"
        brain_result = await process_with_brain_async(gst_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="gst_info", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── CREDIT_POLICY: Use brain pipeline for natural answers ─────
    if action == "CREDIT_POLICY":
        set_state(wa_id, UserState.MAIN_MENU)
        history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

        credit_query = "What is your credit policy — credit period, payment terms, and credit eligibility?"
        brain_result = await process_with_brain_async(credit_query, wa_id=wa_id, history=history)

        response_text = _clean_response(brain_result.get("answer", ""))

        if can_send_whatsapp:
            send_whatsapp_message(wa_id, response_text)
        return _result(response_text, route="credit_policy", interactive=build_main_menu_buttons(), whatsapp_sent=True)

    # ── CATEGORY: Browse specific category ────────────────────────────────────
    if action == "CATEGORY":
        category = msg_id.replace("cat_", "") if msg_id.startswith("cat_") else text
        set_state(wa_id, UserState.BROWSING_PRODUCTS, {"category": category})
        interactive = build_product_catalog_list()
        if can_send_whatsapp:
            logger.info(f"SENDING_INTERACTIVE | to={wa_id} | action=CATEGORY | cat={category} | type=list")
            try:
                from .whatsapp import send_category_menu
                send_category_menu(wa_id, category)
            except Exception as e:
                logger.error(f"Failed to send category {category} to {wa_id}: {e}")
        response_text = f"Category: {category}"
        return _result(response_text, route="category", interactive=interactive, whatsapp_sent=True)

    # ── PRODUCT: Show specific product ────────────────────────────────────────
    if action == "PRODUCT":
        product = None
        for _prefix in ("product_", "prod_", "cat_prod_"):
            if msg_id.startswith(_prefix):
                try:
                    product_id = int(msg_id.replace(_prefix, ""))
                    from ..database import get_product
                    product = get_product(product_id)
                except (ValueError, IndexError):
                    pass
                if product:
                    break
        
        if not product:
            product = _find_product_for_menu(text)
        
        if product:
            set_state(wa_id, UserState.VIEWING_PRODUCT, {"product_id": product.get("id")})
            # Save as active product so Add to Cart / Checkout know the target.
            from .orchestrator import update_conversation_context as _ucc
            _ucc(
                wa_id,
                active_product_id=product.get("id"),
                active_product_name=product.get("name"),
                last_topic="viewing_product",
            )
            name = product.get("name", text)
            interactive = build_product_buttons(name)
            interactive["body"] = (
                f"*{name}*\n"
                f"Price: {product.get('price', 'N/A')}\n"
                f"{product.get('short_description') or product.get('description') or ''}"
            ).strip()
            pub_img = _public_image(product.get("media_url"))
            interactive["product"] = {
                "id": product.get("id"),
                "name": name,
                "price": product.get("price"),
                "media_url": pub_img or product.get("media_url"),
                "slug": product.get("slug"),
            }
            interactive["media_url"] = pub_img
            sent = False
            if can_send_whatsapp:
                try:
                    sent = bool(send_product_with_image(wa_id, product))
                except Exception as e:
                    logger.error(f"Failed to send product to {wa_id}: {e}")
            response_text = f"Product: {name}"
            return _result(response_text, route="product", interactive=interactive, media_url=pub_img, media_type="image", whatsapp_sent=sent)

    # ── AI_MODE: Enter AI conversation mode ───────────────────────────────────
    if action == "AI_MODE" or should_enter_ai_mode(text, parsed_msg, wa_id):
        set_state(wa_id, UserState.AI_MODE)
        # Fall through to brain pipeline below
        logger.info(f"Entering AI_MODE for {wa_id}")

    # ── CART: Add the currently-viewed product to the user's cart ────────────
    if action == "CART":
        from ..database import get_product
        context = get_conversation_context(wa_id)
        product = None
        # Prefer the product ID embedded in the add-to-cart button.
        if msg_id.startswith("b2c_add_cart_") or msg_id.startswith("menu_add_cart_"):
            try:
                _pid = int(msg_id.split("_")[-1])
                product = get_product(_pid)
            except (ValueError, IndexError):
                product = None
        if product is None:
            product_id = context.get("active_product_id")
            if product_id:
                product = get_product(product_id)
        if product is None:
            # No product in context — show the catalog so the user can pick one.
            response_text = "Which product would you like to add to your cart? Pick one below:"
            sent = False
            if can_send_whatsapp:
                try:
                    from .whatsapp import send_products_by_category
                    sent = bool(send_products_by_category(wa_id))
                except Exception as e:
                    logger.error(f"Failed to send catalog for empty-cart hint to {wa_id}: {e}")
                    try:
                        sent = bool(send_whatsapp_message(wa_id, response_text))
                    except Exception as e2:
                        logger.error(f"Failed to send cart hint to {wa_id}: {e2}")
            return _result(response_text, route="cart", interactive=build_product_catalog_list(), whatsapp_sent=True)

        cart_service.add_to_cart(wa_id, product)
        count = cart_service.cart_count(wa_id)
        name = product.get("name", "Product")
        pub_img = _public_image(product.get("media_url"))
        response_text = (
            f"✅ *{name}* added to your cart!\n\n"
            f"You now have *{count}* item(s) in your cart.\n\n"
            "What would you like to do next?"
        )
        sent = False
        if can_send_whatsapp:
            try:
                # Single interactive message: product image header + text + buttons.
                sent = bool(send_interactive_buttons(
                    to=wa_id,
                    body_text=response_text,
                    buttons=[
                        {"id": "b2c_products", "title": "View Products"},
                        {"id": "b2c_view_cart", "title": "View Cart"},
                        {"id": "b2c_checkout", "title": "Checkout"},
                    ],
                    footer_text=get_brand_name(wa_id),
                    header_media=({"type": "image", "image": {"link": pub_img}} if pub_img else None),
                ))
            except Exception as e:
                logger.error(f"Failed to send cart confirmation to {wa_id}: {e}")
        return _result(response_text, route="cart", interactive=build_main_menu_buttons(),
                       media_url=pub_img, media_type="image", whatsapp_sent=sent)

    # ── VIEW_CART: Show the user's current cart contents ─────────────────────
    if action == "VIEW_CART":
        items = cart_service.get_cart(wa_id)
        response_text = cart_service.format_cart_text(wa_id)
        sent = False
        if can_send_whatsapp:
            try:
                buttons = [
                    {"id": "b2c_continue_shopping", "title": "Add More"},
                    {"id": "menu_buy_now", "title": "Checkout"},
                    {"id": "main_menu", "title": "Main Menu"},
                ]
                if not items:
                    buttons = [
                        {"id": "menu_products", "title": "Browse Products"},
                        {"id": "main_menu", "title": "Main Menu"},
                    ]
                sent = bool(send_interactive_buttons(
                    to=wa_id,
                    body_text=response_text,
                    buttons=buttons,
                    footer_text=get_brand_name(wa_id),
                ))
            except Exception as e:
                logger.error(f"Failed to send cart view to {wa_id}: {e}")
        return _result(response_text, route="view_cart", interactive=build_main_menu_buttons(), whatsapp_sent=sent)

    # ── CHECKOUT: Show order summary and ask for confirmation ────────────────
    if action == "CHECKOUT":
        items = cart_service.get_cart(wa_id)
        if not items:
            # Empty cart — send catalog so the user can pick products first.
            response_text = "Your cart is empty. Pick products below, then tap Checkout:"
            sent = False
            if can_send_whatsapp:
                try:
                    from .whatsapp import send_products_by_category
                    sent = bool(send_products_by_category(wa_id))
                except Exception as e:
                    logger.error(f"Failed to send catalog for empty checkout to {wa_id}: {e}")
                    try:
                        sent = bool(send_whatsapp_message(wa_id, response_text))
                    except Exception as e2:
                        logger.error(f"Failed to send empty-checkout hint to {wa_id}: {e2}")
            return _result(response_text, route="checkout", interactive=build_product_catalog_list(), whatsapp_sent=True)

        # Cart has items — show summary and ask to confirm.
        set_state(wa_id, UserState.AWAITING_CHECKOUT_CONFIRM, {"cart_snapshot": cart_service.cart_total(wa_id)})
        summary = cart_service.format_cart_text(wa_id)
        response_text = f"{summary}\n\nShall I place this order?"
        sent = False
        if can_send_whatsapp:
            try:
                sent = bool(send_interactive_buttons(
                    to=wa_id,
                    body_text=response_text,
                    buttons=[
                        {"id": "b2c_confirm_order", "title": "Confirm Order"},
                        {"id": "b2c_view_cart", "title": "View Cart"},
                        {"id": "main_menu", "title": "Main Menu"},
                    ],
                    footer_text=get_brand_name(wa_id),
                ))
            except Exception as e:
                logger.error(f"Failed to send checkout summary to {wa_id}: {e}")
                try:
                    sent = bool(send_whatsapp_message(wa_id, response_text))
                except Exception as e2:
                    logger.error(f"Failed to send checkout text to {wa_id}: {e2}")
        return _result(response_text, route="checkout", interactive=build_main_menu_buttons(), whatsapp_sent=sent)

    # ── CHECKOUT CONFIRM: Record the order intent so staff can process it ────
    if msg_id in ("checkout_confirm", "b2c_confirm_order") or get_current_state(wa_id) == UserState.AWAITING_CHECKOUT_CONFIRM and (
        text.strip().lower() in ("confirm", "yes", "place order", "confirm order")
    ):
        items = cart_service.get_cart(wa_id)
        if not items:
            response_text = "Your cart is empty. Browse products and add items before checkout."
            sent = False
            if can_send_whatsapp:
                try:
                    sent = bool(send_whatsapp_message(wa_id, response_text))
                except Exception as e:
                    logger.error(f"Failed to send empty-cart checkout notice to {wa_id}: {e}")
            return _result(response_text, route="checkout", interactive=build_main_menu_buttons(), whatsapp_sent=sent)

        # Unified, transactional order creation (idempotent + stock-checked).
        try:
            from backend.services.order_service import create_order, OrderError
        except Exception as e:
            logger.error(f"Failed to import order_service: {e}")
            create_order = None

        if create_order is not None:
            order_lines = [f"{it.get('name')} x{it.get('qty', it.get('quantity', 1))} @ ₹{it.get('price')}" for it in items]
            order_text = "; ".join(order_lines)
            try:
                result = create_order(
                    wa_id=wa_id,
                    items=items,
                    source="kb_checkout",
                    idempotency_key=str(uuid.uuid4()),
                )
                if not result.get("ok"):
                    raise RuntimeError(result.get("error", "order failed"))
                order_number = result["order_number"]
                total = result["total"]
            except OrderError as oe:
                # OOS or session conflict — send user back to their cart.
                response_text = (
                    f"Sorry, we couldn't place your order: {oe.detail or oe.reason}.\n"
                    "Your cart is unchanged — tap Checkout to try again."
                )
                sent = False
                if can_send_whatsapp:
                    try:
                        sent = bool(send_whatsapp_message(wa_id, response_text))
                    except Exception as e:
                        logger.error(f"Failed to send checkout failure notice to {wa_id}: {e}")
                return _result(response_text, route="checkout_failed", interactive=build_main_menu_buttons(), whatsapp_sent=sent)

            # Record for the human team (kept from legacy behaviour).
            try:
                from ..database import save_chat as kb_save_chat
                kb_save_chat(wa_id, "", "CHECKOUT ORDER", f"Order: {order_text} | Total: ₹{total}", "checkout_order")
            except Exception as e:
                logger.error(f"Failed to record checkout order for {wa_id}: {e}")

            cart_service.clear_cart(wa_id)
            reset_to_main_menu(wa_id)

            response_text = (
                f"🎉 Order placed! Your order ID is *{order_number}*.\n\n"
                f"{chr(10).join(order_lines)}\n\n"
                f"*Total: ₹{total}*\n\n"
                "Our team will contact you shortly to confirm delivery details."
            )
        else:
            # Fallback: legacy non-transactional path if order_service unavailable.
            order_lines = [f"{it.get('name')} x{it.get('quantity', 1)} @ ₹{it.get('price')}" for it in items]
            order_text = "; ".join(order_lines)
            total = cart_service.cart_total(wa_id)
            try:
                from ..database import save_chat as kb_save_chat
                kb_save_chat(wa_id, "", "CHECKOUT ORDER", f"Order: {order_text} | Total: ₹{total}", "checkout_order")
            except Exception as e:
                logger.error(f"Failed to record checkout order for {wa_id}: {e}")
            cart_service.clear_cart(wa_id)
            reset_to_main_menu(wa_id)
            response_text = (
                f"🎉 Order placed!\n\n"
                f"{chr(10).join(order_lines)}\n\n"
                f"*Total: ₹{total}*\n\n"
                "Our team will contact you shortly to confirm delivery details."
            )
        sent = False
        if can_send_whatsapp:
            try:
                sent = bool(send_interactive_buttons(
                    to=wa_id,
                    body_text=response_text,
                    buttons=[{"id": "main_menu", "title": "Main Menu"}],
                    footer_text=get_brand_name(wa_id),
                ))
            except Exception as e:
                logger.error(f"Failed to send order confirmation to {wa_id}: {e}")
                try:
                    sent = bool(send_whatsapp_message(wa_id, response_text))
                except Exception as e2:
                    logger.error(f"Failed to send order confirmation text to {wa_id}: {e2}")
        return _result(response_text, route="checkout_confirmed", interactive=build_main_menu_buttons(), whatsapp_sent=sent)

    # ── HUMAN: Escalate to human agent ────────────────────────────────────────
    if action == "HUMAN":
        set_state(wa_id, UserState.TALKING_TO_HUMAN)
        sent = False
        if can_send_whatsapp:
            try:
                # Send the confirmation as interactive buttons so it actually
                # delivers (the plain-text endpoint can be blocked by opt-out).
                sent = bool(send_interactive_buttons(
                    to=wa_id,
                    body_text="I'll connect you with our team. Someone will be with you shortly.",
                    buttons=[
                        {"id": "main_menu", "title": "Main Menu"},
                    ],
                    footer_text=get_brand_name(wa_id),
                ))
                if not sent:
                    # Fallback: plain text if interactive send fails.
                    sent = bool(send_whatsapp_message(wa_id, "I'll connect you with our team. Someone will be with you shortly."))
            except Exception as e:
                logger.error(f"Failed to send human escalation to {wa_id}: {e}")
        response_text = "I'll connect you with our team. Someone will be with you shortly."
        return _result(response_text, route="human", interactive=build_main_menu_buttons(), whatsapp_sent=sent)

    # ── LANGUAGE: Language selection ──────────────────────────────────────────
    if action == "LANGUAGE":
        set_state(wa_id, UserState.LANGUAGE_SELECT)
        interactive = build_language_buttons()
        if can_send_whatsapp:
            try:
                send_interactive_buttons(
                    to=wa_id,
                    body_text="Select your language:",
                    buttons=interactive["buttons"],
                )
            except Exception as e:
                logger.error(f"Failed to send language menu to {wa_id}: {e}")
        response_text = interactive.get("body") or "Select your language:"
        return _result(response_text, route="language", interactive=interactive, whatsapp_sent=True)

    # ── Handle fuzzy correction button clicks (NEW FEATURE) ───────────────────
    if msg_id.startswith("fuzzy_product_"):
        product_id = int(msg_id.replace("fuzzy_product_", ""))
        from ..database import get_product
        from .orchestrator import update_conversation_context

        product = get_product(product_id)
        if product:
            # Update conversation context with selected product
            update_conversation_context(
                wa_id,
                active_product_id=product.get("id"),
                active_product_name=product.get("name"),
                active_category=product.get("category"),
                last_topic="fuzzy_correction_selection"
            )

            # Show product details
            name = product.get("name", text)
            interactive = build_product_buttons(name)
            interactive["body"] = (
                f"*{name}*\n"
                f"Price: {product.get('price', 'N/A')}\n"
                f"{product.get('short_description') or product.get('description', '')}"
            ).strip()
            pub_img = _public_image(product.get("media_url"))
            interactive["media_url"] = pub_img
            interactive["product"] = {
                "id": product.get("id"),
                "name": name,
                "price": product.get("price"),
                "media_url": pub_img or product.get("media_url"),
                "slug": product.get("slug"),
            }

            sent = False
            if can_send_whatsapp:
                try:
                    sent = bool(send_product_with_image(wa_id, product))
                except Exception as e:
                    logger.error(f"Failed to send fuzzy-corrected product to {wa_id}: {e}")
            response_text = f"Great choice! Here are details for *{name}*:"
            return _result(response_text, route="fuzzy_product_selected", interactive=interactive, media_url=pub_img, media_type="image", whatsapp_sent=sent)

    # ── Handle "search as typed" from fuzzy correction ────────────────────────
    if msg_id == "fuzzy_search_original":
        # Fall through to normal brain pipeline with original query
        logger.info(f"FUZZY_ORIGINAL_SEARCH | to={wa_id} | query='{text[:50]}'")
        # Continue to DEFAULT pipeline below

    # ── Handle Ollama dynamic button actions (NEW FEATURE) ───────────────────
    if action == "OLLAMA_DYNAMIC_ACTION":
        # User clicked a dynamic button predicted by Ollama
        # Pass the button ID as a natural language query to the brain pipeline
        # This allows contextual conversation flow
        button_title = parsed_msg.get("title", msg_id.replace("_", " ").title())
        dynamic_query = f"User clicked: {button_title}"
        logger.info(f"OLLAMA_DYNAMIC_ACTION | to={wa_id} | button_id={msg_id} | title={button_title} | query='{dynamic_query}'")

        # Use the enhanced query with conversation context
        enhanced_dynamic_query = enhance_query_with_context(dynamic_query, wa_id)

        # Call Ollama with the dynamic action context
        system_prompt = _build_system_prompt(wa_id=wa_id)
        retrieved_context, sources = _retrieve_context(enhanced_dynamic_query, wa_id=wa_id)

        ollama_result = await generate_ollama_dynamic_response(
            system_prompt=system_prompt,
            user_query=enhanced_dynamic_query,
            context=retrieved_context
        )

        response_text = _clean_response(ollama_result.get("answer", ""))
        dynamic_actions = ollama_result.get("next_actions", [])

        logger.info(f"OLLAMA_DYNAMIC_RESPONSE | answer_length={len(response_text)} | actions_count={len(dynamic_actions)}")

        # Send response with new dynamic buttons
        sent = False
        if can_send_whatsapp:
            try:
                if dynamic_actions:
                    whatsapp_buttons = []
                    for action in dynamic_actions:
                        whatsapp_buttons.append({
                            "type": "reply",
                            "reply": {
                                "id": action.get("id", "unknown")[:256],
                                "title": action.get("title", "Option")[:20]
                            }
                        })

                    sent = bool(send_interactive_buttons(
                        to=wa_id,
                        body_text=response_text[:1024],
                        buttons=whatsapp_buttons
                    ))
                else:
                    sent = bool(send_whatsapp_message(wa_id, response_text))
            except Exception as e:
                logger.error(f"Failed to send dynamic action response to {wa_id}: {e}")

        # Build interactive result
        interactive_buttons = build_main_menu_buttons()
        if dynamic_actions:
            interactive_buttons["buttons"] = [
                {"id": action.get("id", "")[:256], "title": action.get("title", "")[:20]}
                for action in dynamic_actions
            ]

        return _result(response_text, route="ollama_dynamic", interactive=interactive_buttons, whatsapp_sent=sent)

    # ── Handle language selection ─────────────────────────────────────────────
    if action == "SET_LANGUAGE" or msg_id.startswith("lang_"):
        lang_code = msg_id.replace("lang_", "") if msg_id.startswith("lang_") else text
        from .menu_router import set_user_lang
        set_user_lang(wa_id, lang_code)
        reset_to_main_menu(wa_id)
        interactive = build_main_menu_list(wa_id)
        sent = False
        if can_send_whatsapp:
            try:
                lang_names = {"en": "English", "hi": "हिंदी", "gu": "ગુજરાતી"}
                send_whatsapp_message(wa_id, f"Language set to {lang_names.get(lang_code, lang_code)}.")
                sent = bool(send_main_menu(wa_id))
            except Exception as e:
                logger.error(f"Failed to set language for {wa_id}: {e}")
        response_text = f"Language set to {lang_code}"
        return _result(response_text, route="language", interactive=interactive, whatsapp_sent=sent)

    # ── IMAGE_REQUEST: Send a sample product image ──────────────────────────
    if _is_image_request(text):
        logger.info(f"IMAGE_REQUEST | to={wa_id} | query={text[:100]}")
        product = _find_product_image(text)
        pub_img = _public_image(product.get("media_url")) if product else None
        if product and pub_img:
            # Save as active product so Add to Cart works after a photo view.
            from .orchestrator import update_conversation_context as _ucc
            _ucc(
                wa_id,
                active_product_id=product.get("id"),
                active_product_name=product.get("name"),
                last_topic="viewing_product",
            )
            response_text = (
                f"Here's a look at *{product.get('name', '')}*!\n"
                f"Price: {product.get('price') or product.get('mrp') or 'N/A'}"
            )
            sent = False
            if can_send_whatsapp:
                try:
                    product["media_url"] = pub_img
                    sent = bool(send_product_with_image(wa_id, product))
                except Exception as e:
                    logger.error(f"Failed to send product image to {wa_id}: {e}")
            return _result(response_text, route="image_request", media_url=pub_img, media_type="image", whatsapp_sent=sent)

        # Image request but nothing matched — give a helpful reply instead of a
        # vague brain-generated "I don't have photos" answer.
        names = [p.get("name") for p in _all_products_with_images()[:5]]
        if names:
            response_text = ("I can send you photos of our products! Which one would you like to see? "
                             + " - ".join(f"*{n}*" for n in names))
        else:
            response_text = "I can send you product photos - could you tell me which product you'd like to see?"
        if can_send_whatsapp:
            try:
                send_whatsapp_message(wa_id, response_text)
            except Exception as e:
                logger.error(f"Failed to send image fallback to {wa_id}: {e}")
        return _result(response_text, route="image_request", whatsapp_sent=True)

    # ── Priority 5: Visual Fallback Menu (NEW FEATURE) ────────────────────────
    # Check if we should show visual fallback menu instead of apology
    if should_trigger_fallback_menu(text, wa_id):
        logger.info(f"FALLBACK_MENU_TRIGGERED | to={wa_id} | query='{text[:50]}...'")

        # Show dynamic main menu instead of generic apology
        reset_to_main_menu(wa_id)
        interactive = build_main_menu_list(wa_id)

        sent = False
        if can_send_whatsapp:
            try:
                sent = bool(send_main_menu(wa_id))
            except Exception as e:
                logger.error(f"Failed to send fallback menu to {wa_id}: {e}")

        response_text = "I'm not sure I understood that correctly. Here's the main menu - what would you like to explore?"
        return _result(response_text, route="fallback_menu", interactive=interactive, whatsapp_sent=sent)

    # ── DEFAULT: Brain/RAG Pipeline with Dynamic Buttons (OLLAMA) ─────────────
    # This handles AI_MODE, general queries, and fallback with enhanced context
    # Uses Ollama for intelligent next-action prediction

    # ENHANCE: Add conversation context to query for better LLM understanding
    enhanced_query = enhance_query_with_context(text, wa_id)
    if enhanced_query != text:
        logger.info(f"QUERY_ENHANCED | original='{text[:40]}...' enhanced='{enhanced_query[:60]}...'")

    history = get_recent_history(wa_id, limit=5, ttl_minutes=get_response_settings().get("memory_ttl_minutes", 30))

    # ============================================
    # NEW: Use Ollama for dynamic button prediction
    # ============================================

    # Build system prompt and retrieve context for Ollama
    system_prompt = _build_system_prompt(wa_id=wa_id)
    retrieved_context, sources = _retrieve_context(enhanced_query, wa_id=wa_id)

    # ============================================
    # AUTO-ESCALATION: suppress RAG answer when confidence is too low or the
    # user explicitly asked to speak to a human. Do NOT send the RAG answer;
    # send "I'm not sure about that. Connecting you to support...", set
    # user_states.human_handover = True, and STOP processing.
    # ============================================
    try:
        from .orchestrator import check_auto_escalation
        _escalate, _escalation_result = check_auto_escalation(text, sources, wa_id)
        if _escalate and _escalation_result:
            _esc_sent = False
            if can_send_whatsapp:
                try:
                    _esc_sent = bool(send_whatsapp_message(wa_id, _escalation_result.get("answer", "")))
                except Exception as e:
                    logger.error(f"Failed to send auto-escalation message to {wa_id}: {e}")
            _escalation_result["whatsapp_sent"] = _esc_sent
            return _escalation_result
    except Exception as e:
        logger.error(f"Auto-escalation check failed for {wa_id}: {e}")

    # Call Ollama with dynamic response generation
    logger.info(f"OLLAMA_DYNAMIC_REQUEST | wa_id={wa_id} | query='{enhanced_query[:100]}...'")
    ollama_result = await generate_ollama_dynamic_response(
        system_prompt=system_prompt,
        user_query=enhanced_query,
        context=retrieved_context
    )

    # Extract answer and dynamic next actions from Ollama
    response_text = _clean_response(ollama_result.get("answer", ""))
    dynamic_actions = ollama_result.get("next_actions", [])

    logger.info(f"OLLAMA_DYNAMIC_RESULT | answer_length={len(response_text)} | actions_count={len(dynamic_actions)}")
    for i, action in enumerate(dynamic_actions):
        logger.info(f"ACTION_{i+1} | id={action.get('id')} | title={action.get('title')}")

    # Update conversation context from response (legacy)
    extract_product_context_from_response(response_text, wa_id)

    # ============================================
    # FIX: Improved product-specific image mapping
    # ============================================
    # Enhanced logic to properly map queries to specific product images
    # instead of always pulling the same fallback image

    media_url, media_type = None, None
    logger.debug(f"Response text after cleaning: {response_text[:200]}")

    # Try multiple search strategies for better product mapping
    products = []

    # Strategy 1: Direct product search with the original query
    products = search_products(text, limit=3)
    if products:
        logger.info(f"Strategy 1: Direct search found {len(products)} products for '{text[:50]}...'")

    # Strategy 2: If no results, try enhanced query (if different)
    if not products and enhanced_query != text:
        products = search_products(enhanced_query, limit=3)
        if products:
            logger.info(f"Strategy 2: Enhanced search found {len(products)} products for '{enhanced_query[:50]}...'")

    # Strategy 3: Extract product name from response text if Ollama mentioned a specific product
    if not products and response_text:
        # Look for product name patterns in the response
        import re
        # Match patterns like "Peanut Chikki", "Groundnut Chikki", etc.
        product_matches = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', response_text)
        for product_name in product_matches[:2]:  # Try first 2 potential matches
            specific_products = search_products(product_name, limit=2)
            if specific_products:
                products = specific_products
                logger.info(f"Strategy 3: Response-based search found {len(products)} products for '{product_name}'")
                break

    # Get the best matching product's image
    if products:
        # Use the first (highest scored) product
        best_product = products[0]
        media_url = best_product.get("media_url")
        product_name = best_product.get("name", "Unknown")
        logger.info(f"PRODUCT_IMAGE_MAPPED | to={wa_id} | product='{product_name}' | image={media_url}")

    if media_url:
        media_type = "image"
        logger.info("Product image successfully mapped: %s", media_url)

    pub_media = _public_image(media_url) if media_url else None
    logger.info(f"KB_RESPONSE | to={wa_id} | resp={(response_text or '')[:200]} | media={pub_media or media_url or 'none'} | media_type={media_type or 'none'}")

    # Omit predicted buttons whose content is not present in the matched product
    dynamic_actions = _filter_actions_present(dynamic_actions, products)

    sent = False
    if can_send_whatsapp:
        try:
            # ============================================
            # FIX: Send the product image alongside the reply/buttons
            # ============================================
            # Send the standalone product image whenever a browsing query has
            # media available, regardless of whether dynamic buttons are also
            # being sent. (Previously the image was suppressed whenever buttons
            # were present, which caused product images to never reach WhatsApp.)

            # Check if dynamic buttons exist first
            has_dynamic_buttons = bool(dynamic_actions)

            # Determine if we should send image
            if not _is_informational_query(text) and (pub_media or media_url):
                # Browsing intent AND media available - send image
                should_send_image = True
            else:
                # Informational query or no media - don't send image
                should_send_image = False

            # Log the decision clearly for debugging
            query_type = "browsing" if not _is_informational_query(text) else "informational"
            logger.info(f"IMAGE_SEND_DECISION | to={wa_id} | send={should_send_image} | query_type={query_type} | has_buttons={has_dynamic_buttons} | original_query='{text[:100]}'")

            if should_send_image:
                image_sent = send_image(wa_id, media_url or pub_media)
                if image_sent:
                    logger.info(f"Image sent to {wa_id}: {pub_media or media_url}")
                else:
                    logger.warning(f"send_image returned False for {pub_media or media_url}")

            # ============================================
            # NEW: Send dynamic Ollama-predicted buttons
            # ============================================
            if dynamic_actions:
                try:
                    # Format dynamic actions for WhatsApp button structure
                    whatsapp_buttons = []
                    for action in dynamic_actions:
                        whatsapp_buttons.append({
                            "type": "reply",
                            "reply": {
                                "id": action.get("id", "unknown")[:256],  # WhatsApp limit
                                "title": action.get("title", "Option")[:20]  # WhatsApp 20 char limit
                            }
                        })

                    logger.info(f"SENDING_DYNAMIC_BUTTONS | to={wa_id} | count={len(whatsapp_buttons)} | buttons={[b['reply']['title'] for b in whatsapp_buttons]}")

                    # Send main response with dynamic buttons
                    sent = bool(send_interactive_buttons(
                        to=wa_id,
                        body_text=response_text[:1024],  # WhatsApp text limit
                        buttons=whatsapp_buttons
                    ))

                    logger.info(f"DYNAMIC_BUTTONS_SENT | to={wa_id} | {len(whatsapp_buttons)} buttons | sent={sent}")

                except Exception as e:
                    logger.error(f"Failed to send dynamic buttons to {wa_id}: {e}")
                    # Fallback to regular text message if buttons fail
                    sent = bool(send_whatsapp_message(wa_id, response_text))
            else:
                # No dynamic actions predicted, send regular text message
                logger.info(f"SENDING_TEXT_ONLY | to={wa_id} | no_dynamic_actions")
                sent = bool(send_whatsapp_message(wa_id, response_text))

        except Exception as e:
            logger.error(f"Failed to send reply to {wa_id}: {e}")

    # Build interactive result with dynamic buttons for API responses
    interactive_buttons = build_main_menu_buttons()

    # Add Ollama-predicted dynamic buttons to the response
    if dynamic_actions:
        interactive_buttons["buttons"] = [
            {"id": action.get("id", "")[:256], "title": action.get("title", "")[:20]}
            for action in dynamic_actions
        ]
        logger.info(f"API_RESPONSE | Including {len(dynamic_actions)} dynamic Ollama-predicted buttons")

    return _result(response_text, route="kb", media_url=pub_media, media_type=media_type, interactive=interactive_buttons, whatsapp_sent=sent)


def _find_product_for_menu(text: str) -> dict | None:
    """Find a product by name, slug, or ID from text."""
    lower = text.lower().strip()

    if lower.startswith("product_"):
        try:
            product_id = int(lower.replace("product_", ""))
            from ..database import get_product
            product = get_product(product_id)
            if product:
                return product
        except (ValueError, IndexError):
            pass

    if lower.startswith("prod_"):
        try:
            product_id = int(lower.replace("prod_", ""))
            from ..database import get_product
            product = get_product(product_id)
            if product:
                return product
        except (ValueError, IndexError):
            pass

    if lower.isdigit():
        from ..database import get_db_context
        idx = int(lower) - 1
        with get_db_context() as conn:
            rows = conn.execute(
                "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category"
            ).fetchall()
        categories = [r[0] for r in rows if r[0]]
        counter = 0
        for cat in categories[:5]:
            items = _fetch_items_from_category_for_menu(cat, limit=10)
            for item in items:
                if counter == idx and item.get("type") == "product":
                    from ..database import get_product
                    try:
                        pid = int(item["id"].replace("product_", "").replace("prod_", ""))
                        return get_product(pid)
                    except (ValueError, KeyError):
                        pass
                counter += 1
                if counter >= 50:
                    break
            if counter >= 50:
                break

    products = search_products(lower, limit=5)
    if products:
        return products[0]

    for p in get_products_by_category("products", limit=50):
        if p["name"].lower() in lower or lower in p["name"].lower():
            return p

    return None


def _fetch_items_from_category_for_menu(category: str, limit: int = 10) -> list:
    from ..database import get_db_context
    items = []
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT id, name, short_description, price, media_url "
            "FROM products WHERE category = ? AND is_active = 1 ORDER BY sort_order ASC LIMIT ?",
            (category, limit),
        ).fetchall()
        for r in rows:
            items.append({
                "id": f"product_{r[0]}",
                "title": r[1],
                "description": (r[2] or "")[:50],
                "type": "product",
            })
    return items
