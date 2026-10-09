from typing import Dict, List
from routing.config import BUSINESS_NAME, logger
from ..database import get_user_state, set_user_state, update_user_context, clear_user_context

# Unified menu catalog & renderer (shared across B2C/B2B/KB)
from services.menu_catalog import get_kb_main_menu, get_main_menu_buttons as _catalog_main_buttons
from services.menu_service import build_list_menu, build_button_menu


# ── Menu Configuration ─────────────────────────────────────────────────────────
# The main menu is now rendered dynamically through services.menu_service using
# items from services.menu_catalog. This keeps B2C, B2B, and KB menus visually
# consistent while still allowing the legacy get_menu_config() helper to work.

MENU_CONFIG = {
    "categories": {
        "type": "buttons",
        "header": "Categories",
        "body": "Select a category to browse:",
        "footer": "Tap Main Menu to go back",
        "buttons": []  # Dynamically populated from product categories
    },
    "product_detail": {
        "type": "buttons",
        "header": "Product",
        "body": "",  # Filled with product name
        "footer": "Tap for more options",
        "buttons": [
            {"id": "b2c_products", "title": "View Products"},
            {"id": "b2c_view_cart", "title": "View Cart"},
            {"id": "main_menu", "title": "Main Menu"},
        ]
    }
}


# ── Menu Keywords (Multi-language) ─────────────────────────────────────────────

MENU_KEYWORDS = {
    "en": ["menu", "main menu", "home", "0", "start", "back", "main"],
    "hi": ["मेनू", "मुख्य मेनू", "होम", "0", "शुरू", "वापस"],
    "gu": ["મેનુ", "મુખ્ય મેનુ", "હોમ", "0", "શરૂ", "પાછા"],
}

CATALOG_KEYWORDS = {
    "en": [
        "product catalogue", "product catalog", "catalogue", "catalog",
        "send catalogue", "send catalog", "get catalogue", "get catalog",
        "brochure", "send brochure",
    ],
    "hi": ["कैटलॉग"],
    "gu": ["કેટાલોગ"],
}

# Keywords for browsing the PRODUCT LIST (interactive list of products).
# Kept separate from CATALOG_KEYWORDS so "View Products" sends the product
# list while "Catalogue" sends the catalogue PDF.
PRODUCTS_KEYWORDS = {
    "en": [
        "view products", "browse products", "show products", "show me products",
        "show me the products", "list products", "product list", "products list",
        "all products", "full products", "whole products", "product menu",
        "show menu", "what do you have", "what do you sell", "what products",
        "your product range", "send me the products",
    ],
    "hi": ["उत्पाद", "सूची", "दिखाओ"],
    "gu": ["ઉત્પાદનો", "યાદી", "બતાવો"],
}


# ── User States ────────────────────────────────────────────────────────────────

class UserState:
    MAIN_MENU = "MAIN_MENU"
    BROWSING_CATEGORIES = "BROWSING_CATEGORIES"
    BROWSING_PRODUCTS = "BROWSING_PRODUCTS"
    VIEWING_PRODUCT = "VIEWING_PRODUCT"
    AI_MODE = "AI_MODE"
    AWAITING_ORDER_ID = "AWAITING_ORDER_ID"
    AWAITING_COMPLAINT_TYPE = "AWAITING_COMPLAINT_TYPE"
    AWAITING_COMPLAINT_DESC = "AWAITING_COMPLAINT_DESC"
    TALKING_TO_HUMAN = "TALKING_TO_HUMAN"
    LANGUAGE_SELECT = "LANGUAGE_SELECT"
    AWAITING_CHECKOUT_CONFIRM = "AWAITING_CHECKOUT_CONFIRM"  # Cart checkout awaiting confirmation
    OLLAMA_DYNAMIC_ACTION = "OLLAMA_DYNAMIC_ACTION"  # NEW: State for Ollama-predicted dynamic button interactions


# ── Helper Functions ───────────────────────────────────────────────────────────

def is_menu_keyword(text: str, lang: str = "en") -> bool:
    """Check if text is a menu trigger keyword."""
    lower = text.lower().strip()
    keywords = MENU_KEYWORDS.get(lang, MENU_KEYWORDS["en"])
    return lower in keywords


def is_catalog_keyword(text: str, lang: str = "en") -> bool:
    """Check if text is a catalog/product trigger keyword."""
    lower = text.lower().strip()
    keywords = CATALOG_KEYWORDS.get(lang, CATALOG_KEYWORDS["en"])
    return any(k in lower for k in keywords)


def is_products_keyword(text: str, lang: str = "en") -> bool:
    """Check if text asks to VIEW the product list (not the catalogue PDF)."""
    lower = text.lower().strip()
    keywords = PRODUCTS_KEYWORDS.get(lang, PRODUCTS_KEYWORDS["en"])
    return any(k in lower for k in keywords)


def parse_interactive_message(msg: dict) -> dict:
    """
    Parse incoming WhatsApp interactive message (button_reply or list_reply).
    
    Returns:
        {
            "type": "button_reply" | "list_reply" | "text" | "image" | "document",
            "id": str | None,
            "title": str | None,
            "description": str | None,
            "text": str,
        }
    """
    msg_type = msg.get("type", "text")
    result = {
        "type": msg_type,
        "id": None,
        "title": None,
        "description": None,
        "text": "",
    }
    
    if msg_type == "text":
        result["text"] = msg.get("text", {}).get("body", "")
    
    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        interactive_type = interactive.get("type", "")
        
        if interactive_type == "button_reply":
            btn = interactive.get("button_reply", {})
            result["type"] = "button_reply"
            result["id"] = btn.get("id", "")
            result["title"] = btn.get("title", "")
            result["text"] = f"{result['title']} [ID:{result['id']}]"
        
        elif interactive_type == "list_reply":
            lst = interactive.get("list_reply", {})
            result["type"] = "list_reply"
            result["id"] = lst.get("id", "")
            result["title"] = lst.get("title", "")
            result["description"] = lst.get("description", "")
            result["text"] = f"{result['title']} [ID:{result['id']}]"
    
    elif msg_type == "image":
        image_data = msg.get("image", {})
        result["text"] = image_data.get("caption", "[Image]")
    
    elif msg_type == "document":
        doc_data = msg.get("document", {})
        filename = doc_data.get("filename", "")
        result["text"] = f"[Document: {filename}]"
    
    return result


def get_menu_config(menu_type: str = "main") -> dict:
    """Get menu configuration by type.

    Note: 'main' is now generated dynamically; this helper returns the legacy
    static config for non-main types or a generated main menu for compatibility.
    """
    if menu_type == "main":
        return build_main_menu_list()
    return MENU_CONFIG.get(menu_type, {})


def build_main_menu_list(wa_id: str = None) -> dict:
    """Build the main menu interactive list payload using the unified catalog."""
    items = get_kb_main_menu(wa_id or "")
    # Admin-editable style (falls back to defaults when not configured).
    settings = {}
    try:
        from database import get_menu_settings  # backend database (sys.path set by kb imports)
        settings = get_menu_settings("kb_main")
    except Exception:
        settings = {}
    return build_list_menu(
        header=settings.get("header") or f"Hi there! 👋 Welcome to {BUSINESS_NAME}",
        body=settings.get("body") or "What can I help you with?",
        button_text=settings.get("button_text") or "Main Menu",
        items=items,
    )


def build_product_catalog_list() -> dict:
    """Build product catalog as an interactive list (by category)."""
    from ..database import get_db_context

    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category"
        ).fetchall()
    categories = [r[0] for r in rows if r[0]]

    sections = []
    for cat in categories[:5]:
        with get_db_context() as conn:
            products = conn.execute(
                "SELECT id, name, short_description FROM products "
                "WHERE category = ? AND is_active = 1 ORDER BY sort_order ASC LIMIT 10",
                (cat,),
            ).fetchall()
        if not products:
            continue
        cat_rows = [
            {
                "id": f"product_{r[0]}",
                "title": (r[1] or "")[:24],
                "description": (r[2] or "")[:72],
            }
            for r in products
        ]
        sections.append({"title": str(cat).title()[:24], "rows": cat_rows})

    if not sections:
        return {
            "type": "buttons",
            "header": "Our Products",
            "body": "No products available yet. Check back soon!",
            "footer": "Tap Main Menu to go back",
            "buttons": [{"id": "main_menu", "title": "Main Menu"}],
        }

    return {
        "type": "list",
        "header": "Our Products",
        "body": "Browse our product range by category:",
        "button": "View Products",
        "footer": f"{len(categories)} categories available",
        "sections": sections,
    }


def build_language_buttons() -> dict:
    """Build language selection buttons."""
    return {
        "type": "buttons",
        "header": "Language",
        "body": "Select your language:",
        "footer": "Tap to change",
        "buttons": [
            {"id": "lang_en", "title": "English"},
            {"id": "lang_hi", "title": "हिंदी"},
            {"id": "lang_gu", "title": "ગુજરાતી"},
        ],
    }


def build_category_buttons(categories: List[str]) -> dict:
    """Build category selection buttons from product categories."""
    buttons = []
    for cat in categories[:3]:  # Max 3 buttons for WhatsApp
        buttons.append({
            "id": f"cat_{cat}",
            "title": cat.title()[:20],  # Max 20 chars for button title
        })
    buttons.append({
        "id": "main_menu",
        "title": "Main Menu",
    })
    return {
        "type": "buttons",
        "header": "Categories",
        "body": "Select a category:",
        "footer": "Tap Main Menu to go back",
        "buttons": buttons,
    }


def build_product_buttons(product_name: str) -> dict:
    """Build product detail action buttons."""
    return {
        "type": "buttons",
        "header": product_name[:40],  # Max 40 chars
        "body": "What would you like to do?",
        "footer": "Tap Main Menu to go back",
        "buttons": [
            {"id": "b2c_products", "title": "View Products"},
            {"id": "b2c_view_cart", "title": "View Cart"},
            {"id": "main_menu", "title": "Main Menu"},
        ]
    }


def build_main_menu_buttons() -> dict:
    """Build simple Main Menu + Ask AI buttons for text responses."""
    return build_button_menu(
        body="",  # Will be filled with the response text by caller
        items=_catalog_main_buttons(),
    )


# ── State Management Wrappers ──────────────────────────────────────────────────

def get_current_state(wa_id: str) -> str:
    """Get user's current state string."""
    state_data = get_user_state(wa_id)
    return state_data.get("state", UserState.MAIN_MENU)


def set_state(wa_id: str, state: str, context: dict = None) -> bool:
    """Set user state with optional context."""
    return set_user_state(wa_id, state, context)


def reset_to_main_menu(wa_id: str) -> bool:
    """Reset user to MAIN_MENU state."""
    return clear_user_context(wa_id)


def is_in_state(wa_id: str, state: str) -> bool:
    """Check if user is in specific state."""
    return get_current_state(wa_id) == state


def get_user_lang(wa_id: str) -> str:
    """Get user's preferred language."""
    state_data = get_user_state(wa_id)
    return state_data.get("lang", "en")


def set_user_lang(wa_id: str, lang: str) -> bool:
    """Set user's preferred language."""
    current = get_user_state(wa_id)
    return set_user_state(wa_id, current.get("state", UserState.MAIN_MENU), 
                          current.get("context_json", {}), lang)


# ── Route Decision Logic ───────────────────────────────────────────────────────

def should_show_main_menu(text: str, parsed_msg: dict, wa_id: str) -> bool:
    """
    Determine if we should show main menu based on input.
    
    Returns True if:
    - Text is a menu keyword
    - Interactive ID is 'main_menu'
    - User typed '0' (universal menu shortcut)
    """
    lang = get_user_lang(wa_id)
    
    # Check menu keywords
    if is_menu_keyword(text, lang):
        return True
    
    # Check interactive reply ID
    if parsed_msg.get("id") == "main_menu":
        return True
    
    # Universal shortcut
    if text.strip() == "0":
        return True
    
    return False


def should_enter_ai_mode(text: str, parsed_msg: dict, wa_id: str) -> bool:
    """
    Determine if we should enter AI mode.
    
    Returns True if:
    - Interactive ID is 'menu_ai'
    - User is already in AI_MODE state and not requesting menu
    """
    current_state = get_current_state(wa_id)
    
    # Explicit AI mode request
    if parsed_msg.get("id") == "menu_ai":
        return True
    
    # Already in AI mode and not requesting menu
    if current_state == UserState.AI_MODE and not should_show_main_menu(text, parsed_msg, wa_id):
        return True
    
    return False


def resolve_pending_option(text: str, wa_id: str) -> dict | None:
    """If user replied with a number/title matching last menu, return that option."""
    raw = (text or "").strip()
    if not raw:
        return None
    state = get_user_state(wa_id)
    options = (state.get("context_json") or {}).get("pending_options") or []
    if not options:
        return None

    # pure number: 1, 2, ...
    if raw.isdigit():
        n = int(raw)
        for opt in options:
            if int(opt.get("n", -1)) == n:
                return opt
        return None

    # "1." or "1)" style
    import re
    m = re.match(r"^(\d+)\s*[.)\-:]", raw)
    if m:
        n = int(m.group(1))
        for opt in options:
            if int(opt.get("n", -1)) == n:
                return opt

    lower = raw.lower()
    for opt in options:
        title = (opt.get("title") or "").lower()
        oid = (opt.get("id") or "").lower()
        if lower == title or lower == oid or (title and title in lower):
            return opt
    return None


def pop_pending_options(wa_id: str) -> None:
    """Clear pending menu options after a selection is consumed."""
    try:
        state = get_user_state(wa_id)
        ctx = dict(state.get("context_json") or {})
        if "pending_options" in ctx:
            ctx.pop("pending_options", None)
            set_user_state(wa_id, state.get("state", UserState.MAIN_MENU), ctx)
    except Exception as e:
        logger.debug(f"pop_pending_options failed: {e}")


def action_for_option_id(msg_id: str, parsed_msg: dict = None) -> str:
    if not msg_id:
        return "DEFAULT"
    if msg_id == "main_menu":
        return "MAIN_MENU"
    # ── Canonical b2c_* shop button contract (docs/cart_contract.md) ────────
    # Legacy menu_* IDs remain permanently mapped to the same actions.
    if msg_id == "b2c_confirm_order" or msg_id == "checkout_confirm":
        return "CHECKOUT_CONFIRM"
    if msg_id == "b2c_cancel_order":
        return "MAIN_MENU"  # cancel → safe exit to main menu
    if msg_id == "b2c_view_cart":
        return "VIEW_CART"
    if msg_id == "b2c_checkout":
        return "CHECKOUT"
    if msg_id == "b2c_products" or msg_id == "b2c_continue_shopping":
        return "PRODUCTS"
    if msg_id.startswith("b2c_add_cart_"):
        return "CART"
    if msg_id.startswith("b2c_buynow_"):
        return "CHECKOUT"
    if msg_id.startswith("menu_"):
            action_map = {
                "menu_products": "PRODUCTS",
                "menu_browse": "PRODUCTS",
                "menu_ai": "AI_MODE",
                "menu_faq": "DEFAULT",
                "menu_human": "HUMAN",
                "menu_orders": "ORDER",
                "menu_lang": "LANGUAGE",
                "menu_offers": "PRODUCTS",
                "menu_add_cart": "CART",
                "menu_buy_now": "CHECKOUT",
                "menu_view_cart": "VIEW_CART",
                "menu_new_arrivals": "NEW_ARRIVALS",
                "menu_catalogue": "CATALOG",
                "menu_catalog": "CATALOG",
                "menu_brochure": "CATALOG",
                "menu_services": "SERVICE_ENQUIRY",
                "menu_return_policy": "RETURN_POLICY",
                "menu_shipping_policy": "SHIPPING_POLICY",
                "menu_about": "ABOUT_COMPANY",
                "menu_payment_terms": "PAYMENT_TERMS",
                "menu_product_info": "PRODUCT_INFO",
                "menu_discounts": "DISCOUNTS",
                "menu_gst": "GST_INFO",
                "menu_credit_policy": "CREDIT_POLICY",
                # Common admin-created policy items (alias → policy pipeline).
                # Unknown menu_* IDs fall back to their clean title via
                # action_for_option_id's alias resolution below.
                "menu_cancellation_policy": "RETURN_POLICY",
                "menu_refund_policy": "RETURN_POLICY",
                "menu_privacy_policy": "PRIVACY_POLICY",
                "menu_terms": "TERMS_CONDITIONS",
                "menu_terms_conditions": "TERMS_CONDITIONS",
                "menu_contact": "CONTACT_SUPPORT",
                "menu_contact_support": "CONTACT_SUPPORT",
            }
            action = action_map.get(msg_id)
            if action:
                return action
            # Admin-created items with unknown menu_* IDs: try to resolve the
            # action from the clean item title (e.g. "🚚 Shipping Policy" →
            # a known policy keyword) instead of leaking the raw ID string
            # (emoji + "menu_shipping_policy") into the FAQ classifier.
            title = str((parsed_msg or {}).get("title") or "").strip()
            if title:
                lowered = title.lower()
                if "shipping" in lowered or "delivery" in lowered:
                    return "SHIPPING_POLICY"
                if "cancel" in lowered or "refund" in lowered or "return" in lowered:
                    return "RETURN_POLICY"
                if "privacy" in lowered:
                    return "PRIVACY_POLICY"
                if "terms" in lowered:
                    return "TERMS_CONDITIONS"
                if "discount" in lowered or "offer" in lowered:
                    return "DISCOUNTS"
                if "gst" in lowered or "tax" in lowered:
                    return "GST_INFO"
                if "credit" in lowered:
                    return "CREDIT_POLICY"
                if "contact" in lowered or "support" in lowered:
                    return "CONTACT_SUPPORT"
                if "complaint" in lowered:
                    return "COMPLAINT"
                if "cart" in lowered:
                    return "VIEW_CART"
                if "human" in lowered or "support team" in lowered:
                    return "HUMAN"
            return "DEFAULT"
    if msg_id.startswith("cat_"):
        return "CATEGORY"
    if msg_id.startswith("product_") or msg_id.startswith("prod_"):
        return "PRODUCT"
    if msg_id.startswith("lang_"):
        return "SET_LANGUAGE"

    # ============================================
    # B2C Customer Support button IDs
    # ============================================
    if msg_id.startswith("action_"):
        action_map = {
            "action_track_order": "TRACK_ORDER",
            "action_complaint": "COMPLAINT",
        }
        return action_map.get(msg_id, "DEFAULT")
    if msg_id.startswith("complaint_"):
        # Complaint-type selection buttons
        return "COMPLAINT_TYPE"

    # ============================================
    # NEW: Handle dynamic Ollama-predicted button IDs
    # ============================================
    # If the ID doesn't match any static menu patterns, treat it as a dynamic button
    # These IDs were generated by Ollama to represent logical next actions
    # We'll route them through the OLLAMA_DYNAMIC_ACTION pipeline
    logger.info(f"DYNAMIC_BUTTON_ID | id={msg_id} | routing as OLLAMA_DYNAMIC_ACTION")
    return "OLLAMA_DYNAMIC_ACTION"


def get_route_action(text: str, parsed_msg: dict, wa_id: str) -> str:
    """
    Determine the routing action for this message.

    Returns one of:
    - "MAIN_MENU" - Show main menu
    - "PRODUCTS" - Show product list (interactive)
    - "CATALOG" - Show product catalog
    - "PRODUCT" - Show specific product
    - "AI_MODE" - Enter AI conversation mode
    - "CATEGORY" - Browse category
    - "ORDER" - Order-related action
    - "HUMAN" - Escalate to human
    - "LANGUAGE" - Language selection
    - "NEW_ARRIVALS" - Show new arrivals
    - "CATALOG_FAQ" - Show catalogue from FAQ
    - "RETURN_POLICY" - Show return policy
    - "ABOUT_COMPANY" - Show about company info
    - "PAYMENT_TERMS" - Show payment & terms
    - "OLLAMA_DYNAMIC_ACTION" - Handle dynamic Ollama-predicted button clicks
    - "DEFAULT" - Use brain/RAG pipeline with dynamic button generation
    """
    lang = get_user_lang(wa_id)
    msg_id = parsed_msg.get("id") or ""
    current_state = get_current_state(wa_id)

    # Priority 1: Menu keywords always go to main menu
    if should_show_main_menu(text, parsed_msg, wa_id):
        return "MAIN_MENU"

    # Priority 1b: Numbered text-menu replies (send2 has no interactive lists)
    if not msg_id:
        pending = resolve_pending_option(text, wa_id)
        if pending:
            msg_id = pending.get("id") or ""
            parsed_msg["id"] = msg_id
            parsed_msg["title"] = pending.get("title") or text
            pop_pending_options(wa_id)

    # Priority 2: Interactive / pending option IDs
    if msg_id:
        action = action_for_option_id(msg_id, parsed_msg)
        if action != "DEFAULT" or msg_id.startswith("menu_"):
            return action
        if msg_id.startswith("product_") or msg_id.startswith("cat_"):
            return action_for_option_id(msg_id, parsed_msg)

    # Priority 3: Catalogue / product-list keywords.
    # "Catalogue" requests the PDF; "View Products" requests the product list.
    if is_catalog_keyword(text, lang):
        return "CATALOG"
    if is_products_keyword(text, lang):
        return "PRODUCTS"

    # Priority 4: State-based routing
    if current_state == UserState.AI_MODE:
        return "AI_MODE"

    if current_state == UserState.BROWSING_PRODUCTS:
        if text.isdigit():
            return "PRODUCT"

    # B2C Support states: route any message received while mid-workflow back to
    # the support handler so the multi-step flows continue correctly.
    if current_state in (
        UserState.AWAITING_ORDER_ID,
        UserState.AWAITING_COMPLAINT_TYPE,
        UserState.AWAITING_COMPLAINT_DESC,
    ):
        return "SUPPORT"

    # Priority 5: Check if this is a dynamic Ollama button ID (catch-all for unknown button IDs)
    # This handles any button ID that doesn't match static patterns but came from our dynamic buttons
    if msg_id and not msg_id.startswith(("menu_", "cat_", "product_", "prod_", "lang_", "fuzzy_")):
        logger.info(f"UNKNOWN_BUTTON_ID | treating as dynamic Ollama action: {msg_id}")
        return "OLLAMA_DYNAMIC_ACTION"

    # Priority 6: Default to brain/RAG with dynamic Ollama button generation
    return "DEFAULT"
