"""Universal product/offering browsing on WhatsApp using list menus.

Supports all tenant verticals:
- Tours & Travel (Tour packages, destinations, itineraries)
- Real Estate (Apartments, villas, plots, commercial spaces)
- Banking (Savings accounts, credit cards, loans)
- Finance (Tax planning, advisory, GST compliance)
- IT & Software (Web development, mobile apps, consulting)
- E-commerce / Retail / General (Products, catalogue items)

Design guarantees:
1. Feature-Gated: Offerings button only renders if tenant has >= 1 active product.
2. Vertical-Tailored Button Titles: Strictly <= 20 chars for WhatsApp buttons.
3. 2-Tier List Menu:
   - <= 10 products: Direct Category-grouped list menu.
   - > 10 products: Category Selector list first, then category products.
4. Detail Card: Formatted highlights, price/rates, and attached PDF brochure.
5. Direct Enquiry CTA: Launches lead capture flow with the product pre-filled.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Dict, Any, List

logger = logging.getLogger("offerings_flow")

# Row id prefixes for WhatsApp interactive lists and buttons
PROD_ROW_PREFIX = "prod_"
CAT_ROW_PREFIX = "cat_"
BOOK_PROD_PREFIX = "book_prod_"

# WhatsApp Cloud API limits
ROW_TITLE_MAX = 24
ROW_DESC_MAX = 72
SECTION_TITLE_MAX = 24
MAX_LIST_ROWS = 10
CARD_MAX_CHARS = 3800

# Vertical-tailored button titles (strictly <= 20 chars for reply buttons)
VERTICAL_BUTTON_TITLES = {
    "tours_travel": "🎒 Tour Packages",
    "real_estate": "🏢 View Properties",
    "banking": "🏦 Banking Products",
    "finance": "💼 Our Services",
    "it_software": "💻 Our Services",
    "ecommerce": "🛍️ Browse Products",
    "generic": "📋 Our Offerings",
}

# Vertical-tailored menu action IDs
VERTICAL_ACTION_IDS = {
    "tours_travel": "menu_packages",
    "real_estate": "menu_properties",
    "banking": "menu_banking_products",
    "finance": "menu_services",
    "it_software": "menu_services",
    "ecommerce": "menu_products",
    "generic": "menu_offerings",
}

# Vertical-tailored CTA titles on product cards (strictly <= 20 chars)
VERTICAL_CTA_TITLES = {
    "tours_travel": "Book This Package",
    "real_estate": "Enquire Property",
    "banking": "Apply Now",
    "finance": "Request Proposal",
    "it_software": "Enquire Service",
    "ecommerce": "Buy / Enquire",
    "generic": "Enquire Now",
}

# Common free-text phrases asking for the catalogue / offerings
OFFERINGS_PHRASES = {
    "products", "our products", "show products", "browse products", "product list",
    "packages", "our packages", "tour packages", "holiday packages", "show packages",
    "properties", "view properties", "our properties", "flats", "villas", "apartments",
    "services", "our services", "show services", "solutions",
    "offerings", "our offerings", "catalogue", "catalog", "brochure", "items",
    "banking products", "accounts", "cards", "loans",
}

ENQUIRY_BUTTON_ALIASES = {
    "book this package", "book this tour", "enquire property", "apply now",
    "request proposal", "enquire service", "buy / enquire", "enquire now",
    "enquire this product", "book now",
}

ENQUIRY_VERBS = (
    "book", "booked", "booking", "apply", "enquire", "enquiry",
    "inquire", "inquiry", "interested", "quote",
)

QUESTION_CUES_RE = re.compile(
    r"\b(where|which|why|who|whom|whose|when|how|what|can\s+i|can\s+we|is\s+there|are\s+there|will\s+there|will\s+we|will\s+i|do\s+you|do\s+we|could\s+you)\b",
    re.IGNORECASE,
)

ATTRIBUTE_INQUIRY_RE = re.compile(
    r"\b(pickup|pick\s*up|drop|drop\s*off|dropoff|hotel|hotels|stay|room|rooms|food|meal|meals|flight|flights|airfare|train|ticket|transport|cab|vehicle|refund|cancel|cancellation|guide|driver|timing|timings|rate|interest|emi|eligibility|bhk|sqft|possession|rera|amenities|maintenance|tenure|fees|charges)\b",
    re.IGNORECASE,
)


def _db():
    import database as db
    return db


def _state():
    try:
        from services import state_manager
    except ImportError:
        from backend.services import state_manager
    return state_manager


def _sender():
    try:
        from services import whatsapp_sender
    except ImportError:
        from backend.services import whatsapp_sender
    return whatsapp_sender


def _normalize(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(
        r"[\u2190-\u21FF\u2300-\u27BF\uFE0E\uFE0F\U0001F000-\U0001FAFF]", " ",
        str(text),
    )
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _slugify(text: str) -> str:
    clean = _normalize(text)
    return re.sub(r"\s+", "_", clean)[:40]


def get_tenant_vertical(tenant_id: str = None) -> str:
    """Resolve the industry vertical for a tenant."""
    try:
        from shared.tenancy.loader import get_tenant_profile
        profile = get_tenant_profile(tenant_id)
        if profile and getattr(profile, "vertical", None):
            return profile.vertical
    except Exception:
        pass
    try:
        from shared.tenancy.store import get_tenant
        row = get_tenant(tenant_id)
        if row and row.get("vertical"):
            return row["vertical"]
    except Exception:
        pass
    return "generic"


def get_vertical_offerings_button(tenant_id: str = None) -> Optional[Dict[str, str]]:
    """Return the offerings button definition if the tenant has active products.
    Returns None if the tenant has 0 active products (Feature Gating).
    """
    db = _db()
    count = db.count_products(tenant_id=tenant_id, active_only=True)
    if count <= 0:
        return None

    vertical = get_tenant_vertical(tenant_id)
    title = VERTICAL_BUTTON_TITLES.get(vertical, VERTICAL_BUTTON_TITLES["generic"])
    btn_id = VERTICAL_ACTION_IDS.get(vertical, VERTICAL_ACTION_IDS["generic"])
    return {"id": btn_id, "title": title}


def _brand_name(tenant_id: str = None) -> str:
    try:
        from shared.tenancy.loader import get_tenant_profile
        profile = get_tenant_profile(tenant_id)
        if profile and profile.brand and profile.brand.name:
            return profile.brand.name
    except Exception:
        pass
    try:
        from shared.tenancy.store import get_tenant
        row = get_tenant(tenant_id)
        if row and (row.get("display_name") or row.get("company_name")):
            return row.get("display_name") or row.get("company_name")
    except Exception:
        pass
    return "Our Team"


# ── State / Pending Product ───────────────────────────────────────────────────

def remember_product(wa_id: str, product: dict) -> None:
    """Remember the product the user is currently viewing."""
    if not product or not wa_id:
        return
    attrs = product.get("attrs_json") or {}
    payload = {
        "id": product.get("id"),
        "name": product.get("name"),
        "category": product.get("category"),
        "price": product.get("price"),
        "tenant_id": product.get("tenant_id"),
        "destination": attrs.get("destination") or "",
    }
    sm = _state()
    try:
        sm.ensure_conversation_row(wa_id)

        def apply(ctx):
            ctx["pending_product"] = payload
            # Compatibility with tours package_flow
            if attrs.get("destination") or attrs.get("package_name"):
                ctx["pending_package"] = {
                    "id": product.get("id"),
                    "name": product.get("name"),
                    "destination": str(attrs.get("destination") or ""),
                }

        sm.update_context_with_retry(wa_id, apply)
    except Exception as e:
        logger.warning("could not remember product for %s: %s", wa_id, e)


def pending_product(wa_id: str) -> dict:
    sm = _state()
    try:
        ctx, _version = sm.read_user_context(wa_id)
    except Exception:
        return {}
    p = ctx.get("pending_product")
    return p if isinstance(p, dict) else {}


# ── Product Formatting ───────────────────────────────────────────────────────

def product_card(product: dict, vertical: str = "generic") -> str:
    """Format a human-readable WhatsApp detail card for any product."""
    name = product.get("name") or "Offering"
    category = product.get("category") or ""
    price = product.get("price") or ""
    desc = product.get("description") or product.get("short_description") or ""
    attrs = product.get("attrs_json") or {}

    # Icon by vertical
    icon = "📦"
    if vertical == "tours_travel":
        icon = "🎒"
    elif vertical == "real_estate":
        icon = "🏢"
    elif vertical == "banking":
        icon = "🏦"
    elif vertical == "finance":
        icon = "💼"
    elif vertical == "it_software":
        icon = "💻"

    lines = [f"{icon} *{name}*", ""]

    if category:
        lines.append(f"🏷️ *Category:* {category}")

    # Vertical-specific metadata
    if vertical == "tours_travel":
        dest = attrs.get("destination")
        if dest:
            lines.append(f"📍 *Destination:* {dest}")
        dur = attrs.get("duration")
        if dur:
            lines.append(f"🗓️ *Duration:* {dur}")
    elif vertical == "real_estate":
        loc = attrs.get("location")
        if not loc:
            parts = [p for p in (attrs.get("locality"), attrs.get("city")) if p]
            if parts:
                loc = ", ".join(parts)
        if loc:
            lines.append(f"📍 *Location:* {loc}")
        config = attrs.get("configuration") or attrs.get("configurations") or attrs.get("bhk") or attrs.get("property_type")
        if config:
            lines.append(f"🏠 *Configuration:* {config}")
        area = attrs.get("carpet_area") or attrs.get("area") or attrs.get("leasable_area")
        if area:
            lines.append(f"📐 *Area:* {area}")
        possession = attrs.get("possession") or attrs.get("status")
        if possession:
            lines.append(f"🔑 *Possession:* {possession}")
        rera = attrs.get("rera_id") or attrs.get("rera")
        if rera:
            lines.append(f"📜 *RERA:* {rera}")
    elif vertical == "banking":
        interest = attrs.get("interest_rate") or attrs.get("rate")
        if interest:
            lines.append(f"📈 *Interest Rate:* {interest}")
        min_bal = attrs.get("min_balance")
        if min_bal:
            lines.append(f"💵 *Min Balance / Criteria:* {min_bal}")

    # Pricing
    if price:
        lines.append(f"💰 *Price / Rate:* {price}")
    else:
        lines.append("💰 *Pricing:* Custom quote / varies by requirement")

    # Description
    if desc:
        lines.extend(["", f"ℹ️ *Overview:*\n{desc}"])

    # Inclusions / Features
    includes = attrs.get("includes") or attrs.get("features") or attrs.get("amenities")
    if includes:
        lines.append("\n✅ *Highlights & Inclusions:*")
        parts = re.split(r"[\n\r]+|(?<=\s)•", str(includes))
        for p in parts:
            item = p.strip(" \t\r\n•-–—*")
            if item:
                lines.append(f"• {item[:150]}")

    # Itinerary if tours
    itinerary = attrs.get("itinerary")
    if itinerary and vertical == "tours_travel":
        lines.append("\n🗺️ *Itinerary Overview:*")
        text = str(itinerary).replace("\r\n", "\n")
        text = re.sub(r"(?<!^)(?=Day\s*\d+\s*:)", "\n", text)
        for part in text.split("\n")[:10]:
            l = part.strip(" \t\r\n•-–—*")
            if l:
                lines.append(f"• {l[:200]}")

    card = "\n".join(lines).strip()
    if len(card) > CARD_MAX_CHARS:
        card = card[:CARD_MAX_CHARS].rsplit("\n", 1)[0]
    return card


# ── Interactive List Menus ───────────────────────────────────────────────────

async def send_offerings_list(
    wa_id: str, tenant_id: str = None, category: str = None
) -> bool:
    """Send an interactive WhatsApp list menu of available products.
    If total products > 10 and no category is selected, sends the Category Selector.
    """
    db = _db()
    sender = _sender()
    brand = _brand_name(tenant_id)

    if category:
        products = db.list_products(category=category, active_only=True, limit=50, tenant_id=tenant_id)
    else:
        products = db.list_products(active_only=True, limit=100, tenant_id=tenant_id)

    if not products:
        logger.info("send_offerings_list: no active products for tenant %s (cat=%s)", tenant_id, category)
        return False

    # Large Catalog (> 10 items) and no category filter: Category Selector Menu
    if category is None and len(products) > MAX_LIST_ROWS:
        categories = db.list_product_categories(active_only=True, tenant_id=tenant_id)
        if len(categories) > 1:
            rows = []
            for cat in categories[:MAX_LIST_ROWS]:
                c_count = db.count_products(category=cat, active_only=True, tenant_id=tenant_id)
                rows.append({
                    "id": f"{CAT_ROW_PREFIX}{_slugify(cat)}",
                    "title": cat[:ROW_TITLE_MAX],
                    "description": f"{c_count} offerings available • Tap to view"[:ROW_DESC_MAX],
                })
            sections = [{"title": "Select Category"[:SECTION_TITLE_MAX], "rows": rows}]
            header = f"{brand} — Categories"[:60]
            body = "Please choose a category below to browse our available offerings:"
            return await sender.send_list_menu(
                wa_id, header, body, "Select Category", sections, tenant_id=tenant_id
            )

    # Standard / Filtered Product List Menu
    # Group products by category
    cats = sorted({(p.get("category") or "General") for p in products})
    sections = []
    total_rows = 0

    for cat in cats:
        if total_rows >= MAX_LIST_ROWS:
            break
        c_prods = [p for p in products if (p.get("category") or "General") == cat]
        rows = []
        for p in c_prods:
            if total_rows >= MAX_LIST_ROWS:
                break
            price = (p.get("price") or "").strip()
            desc = (p.get("short_description") or p.get("description") or "").strip()
            desc_part = f"{price} • {desc}" if price and desc else (price or desc or "Tap to view details")
            rows.append({
                "id": f"{PROD_ROW_PREFIX}{p.get('id')}",
                "title": (p.get("name") or "Item")[:ROW_TITLE_MAX],
                "description": desc_part[:ROW_DESC_MAX],
            })
            total_rows += 1

        if rows:
            sections.append({
                "title": cat[:SECTION_TITLE_MAX],
                "rows": rows,
            })

    header = f"{brand} — {category}"[:60] if category else f"{brand} — Offerings"[:60]
    body = "Here are our available offerings. Tap one to view complete details, features and booking options:"
    return await sender.send_list_menu(
        wa_id, header, body, "View Details", sections, tenant_id=tenant_id
    )


async def send_product_details(wa_id: str, product: dict, tenant_id: str = None) -> bool:
    """Send the product detail card and interactive booking/enquiry button."""
    remember_product(wa_id, product)
    sender = _sender()
    vertical = get_tenant_vertical(tenant_id)

    card_text = product_card(product, vertical=vertical)
    card_ok = await sender.send_text_message(wa_id, card_text)

    # If the product carries an attached PDF brochure document, send it!
    media_url = product.get("media_url")
    media_type = (product.get("media_type") or "").lower()
    attrs = product.get("attrs_json") or {}
    if isinstance(attrs, str):
        try:
            import json as _json
            attrs = _json.loads(attrs)
        except Exception:
            attrs = {}
    doc_url = None
    if media_url and ("pdf" in media_type or media_url.lower().endswith(".pdf")):
        doc_url = media_url
    elif attrs.get("brochure_url"):
        doc_url = attrs.get("brochure_url")

    if doc_url:
        try:
            filename = f"{product.get('name')}_Brochure.pdf"
            await sender.send_document_message(wa_id, doc_url, filename=filename)
        except Exception as e:
            logger.debug("could not send product document for %s: %s", wa_id, e)

    cta_title = VERTICAL_CTA_TITLES.get(vertical, VERTICAL_CTA_TITLES["generic"])
    buttons = [{
        "type": "reply",
        "reply": {
            "id": f"{BOOK_PROD_PREFIX}{product.get('id')}",
            "title": cta_title[:20],
        },
    }]
    body = (
        f"Interested in *{product.get('name')}*? "
        "Tap below and our team will confirm availability and assist you!"
    )
    btn_ok = await sender.send_button_message(
        wa_id, body, buttons, tenant_id=tenant_id
    )
    return bool(card_ok and btn_ok)


async def _start_enquiry(wa_id: str, product: Optional[dict], tenant_id: str) -> dict:
    """Launch the lead enquiry flow seeded with the product name."""
    try:
        from services import flow_runner
    except ImportError:
        from backend.services import flow_runner

    vertical = get_tenant_vertical(tenant_id)
    flow_name = "book_package" if vertical == "tours_travel" else "lead_capture"

    seed = {}
    if product:
        name = product.get("name") or ""
        seed["package"] = name
        seed["product"] = name
        seed["service"] = name
        seed["offering"] = name

    outcome = flow_runner.start_flow(
        wa_id, flow_name, tenant_id=tenant_id, seed=seed
    )
    if not outcome.get("handled"):
        # Fallback to book_callback if lead_capture is not registered
        outcome = flow_runner.start_flow(
            wa_id, "book_callback", tenant_id=tenant_id, seed=seed
        )

    sender = _sender()
    for msg in outcome.get("messages") or []:
        if isinstance(msg, dict) and msg.get("type") == "buttons":
            await sender.send_button_message(
                wa_id, msg.get("text", ""), msg.get("buttons", []), tenant_id=tenant_id
            )
        else:
            await sender.send_text_message(wa_id, msg)

    return {
        "handled": True,
        "action": "product_enquiry",
        "product": product.get("name") if product else "",
    }


# ── Free-Text Matching ───────────────────────────────────────────────────────

def _is_enquiry_button_tap(text: str) -> bool:
    return _normalize(text) in ENQUIRY_BUTTON_ALIASES


def _has_enquiry_verb(text: str) -> bool:
    needle = f" {_normalize(text)} "
    return any(f" {v}" in needle or needle.endswith(f" {v}") for v in ENQUIRY_VERBS)


def is_offerings_request(tenant_id: str, text: str, pressed_id: str = "") -> bool:
    raw_id = (pressed_id or "").strip()
    if raw_id in VERTICAL_ACTION_IDS.values() or raw_id in ("menu_packages", "menu_properties", "menu_banking_products", "menu_services", "menu_products", "menu_offerings"):
        return True
    needle = _normalize(text)
    return needle in OFFERINGS_PHRASES


def find_product(tenant_id: str, text: str, products: list = None) -> Optional[dict]:
    needle = _normalize(text)
    if not needle or len(needle) < 3:
        return None
    db = _db()
    if products is None:
        products = db.list_products(active_only=True, limit=100, tenant_id=tenant_id)
    if not products:
        return None

    # Exact match on full name
    for p in products:
        if needle == _normalize(p.get("name")):
            return p
    # Exact match on truncated row title
    for p in products:
        if needle == _normalize((p.get("name") or "")[:ROW_TITLE_MAX]):
            return p
    # Whole-word substring match inside sentence
    for p in products:
        title = _normalize((p.get("name") or "")[:ROW_TITLE_MAX])
        if len(title) >= 5 and re.search(rf"\b{re.escape(title)}\b", needle):
            return p
    return None


def _is_specific_product_question(text: str, product: dict) -> bool:
    if not text:
        return False
    raw = text.strip()
    has_qmark = "?" in raw
    has_attr = bool(ATTRIBUTE_INQUIRY_RE.search(raw))
    has_question_cue = bool(QUESTION_CUES_RE.search(raw))

    if has_attr:
        return True
    if has_qmark and has_question_cue:
        return True

    clean = _normalize(raw)
    p_title = _normalize(product.get("name") or "")
    words = clean.split()
    if len(words) > len(p_title.split()) + 3 and has_question_cue:
        return True

    return False


# ── Action Handler ───────────────────────────────────────────────────────────

async def handle_offerings_action(
    wa_id: str, text: str, tenant_id: str = None, pressed_id: str = ""
) -> Optional[dict]:
    """Unified handler for all product/offering browsing across all tenant verticals.
    Returns None when the interaction is not about offerings so normal routing continues.
    """
    db = _db()
    raw_id = (pressed_id or "").strip()
    raw_text = (text or "").strip()

    # 1. Product row tap from list menu (e.g. prod_12)
    if raw_id.startswith(PROD_ROW_PREFIX):
        pid_str = raw_id[len(PROD_ROW_PREFIX):]
        if pid_str.isdigit():
            prod = db.get_product(int(pid_str), tenant_id=tenant_id)
            if prod:
                await send_product_details(wa_id, prod, tenant_id=tenant_id)
                return {"handled": True, "action": "product_details", "product": prod.get("name")}

    # 2. Category row tap from Category Selector menu (e.g. cat_home_loans)
    if raw_id.startswith(CAT_ROW_PREFIX):
        cat_slug = raw_id[len(CAT_ROW_PREFIX):]
        categories = db.list_product_categories(active_only=True, tenant_id=tenant_id)
        matched_cat = None
        for cat in categories:
            if _slugify(cat) == cat_slug:
                matched_cat = cat
                break
        if matched_cat:
            sent = await send_offerings_list(wa_id, tenant_id=tenant_id, category=matched_cat)
            if sent:
                return {"handled": True, "action": "category_products", "category": matched_cat}

    # 3. Enquiry / Booking button tap on a detail card
    if raw_id.startswith(BOOK_PROD_PREFIX):
        pid_str = raw_id[len(BOOK_PROD_PREFIX):]
        prod = db.get_product(int(pid_str), tenant_id=tenant_id) if pid_str.isdigit() else None
        return await _start_enquiry(wa_id, prod, tenant_id=tenant_id)

    if _is_enquiry_button_tap(raw_text):
        pending = pending_product(wa_id)
        prod = db.get_product(pending.get("id"), tenant_id=tenant_id) if pending.get("id") else None
        return await _start_enquiry(wa_id, prod, tenant_id=tenant_id)

    # 4. Catalog / offerings requested ("Tour Packages", "View Properties", "Banking Products", "menu_packages")
    if is_offerings_request(tenant_id, raw_text, raw_id):
        sent = await send_offerings_list(wa_id, tenant_id=tenant_id)
        if sent:
            return {"handled": True, "action": "offerings_list"}
        return None

    # 5. Free-text mention of a specific product
    prod = find_product(tenant_id, raw_text)
    if prod:
        remember_product(wa_id, prod)
        if _has_enquiry_verb(raw_text):
            return await _start_enquiry(wa_id, prod, tenant_id=tenant_id)
        if _is_specific_product_question(raw_text, prod):
            logger.info("PRODUCT_SPECIFIC_QUESTION | wa_id=%s | prod=%s | falling through to FAQ/RAG",
                        wa_id, prod.get("name"))
            return None
        await send_product_details(wa_id, prod, tenant_id=tenant_id)
        return {"handled": True, "action": "product_details", "product": prod.get("name")}

    return None


# Backward-compatibility alias
handle_package_action = handle_offerings_action

