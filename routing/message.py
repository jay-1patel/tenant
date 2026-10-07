import logging
import re

from routing.classifier import classify_query, generate_greeting
from routing.config import SEND_MEDIA, BUSINESS_NAME, CATALOG_DELIVERY_MODE

logger = logging.getLogger("message")


def _get_greeting_menu(wa_id: str):
    """Lazy import to avoid circular imports in standalone KB mode."""
    from services.menu_service import get_greeting_menu
    return get_greeting_menu(wa_id)


BUTTON_INTENTS = [
    {
        "name": "moq",
        "keywords": (
            "moq", "minimum order quantity", "minimum order", "minimum quantity",
            "min order", "min quantity", "min qty", "minimum qty", "order quantity",
        ),
        "buttons": [{"type": "reply", "reply": {"id": "check_moq", "title": "Check MOQ by product"}}],
    },
    {
        "name": "bulk_discount",
        "keywords": (
            "bulk discount", "quantity discount", "volume discount", "wholesale discount",
            "wholesale price", "bulk pricing", "discount on bulk", "discounts on bulk",
            "large order discount", "discount for large order",
        ),
        "buttons": [{"type": "reply", "reply": {"id": "view_discounts", "title": "View qty discounts"}}],
    },
    {
        "name": "credit",
        "keywords": (
            "credit period", "credit terms", "credit line", "credit facility",
            "credit eligibility", "buy now pay later", "net 30", "net 45", "net 60",
        ),
        "buttons": [{"type": "reply", "reply": {"id": "check_credit", "title": "Credit eligibility"}}],
    },
    {
        "name": "payment",
        "keywords": (
            "payment method", "payment methods", "payment option", "payment options",
            "payment terms", "how can i pay", "how to pay", "how do i pay", "ways to pay",
            "mode of payment", "make payment", "payment",
        ),
        "buttons": [{"type": "reply", "reply": {"id": "view_payment", "title": "View payment methods"}}],
    },
]

DOCUMENT_BUTTON_ID = "send_document"
DOCUMENT_BUTTON_TITLE = "View Document"

_DOCUMENT_MEDIA_TYPES = frozenset(
    {"pdf", "doc", "docx", "xlsx", "xls", "csv", "document"}
)


def _media_is_document(media_type: str) -> bool:
    """True only when the attached media is a document (not an image/video)."""
    return (media_type or "").lower().strip() in _DOCUMENT_MEDIA_TYPES

DIRECT_MEDIA_KEYWORDS = (
    "catalogue", "catalog", "brochure", "product list", "price list", "product lineup",
    "product range", "menu", "new arrival", "new arrivals", "new launch", "new launches",
    "new release", "new releases", "new product", "latest product", "latest launch", "fresh drops", "recent additions",
)

NO_FALLBACK_KB_QUERIES = {
    "about company", "about troogood", "about us", "company info",
    "who is the founder", "when was troogood founded", "troogood story",
    "tell me about troogood", "what is troogood",
}


# Question words/phrases indicate the user is asking about the *contents* of
# the document (what's inside, prices, products, specs, etc.) — those should
# get a text answer from the FAQ bot, not the raw PDF.
CONTENT_QUESTION_MARKERS = (
    "tell me", "is there", "are there", "detail", "details",
    "ingredient", "contain", "contains", "included", "inside",
    "spec", "nutrition", "flavour", "flavor",
)


def is_direct_media_query(text) -> bool:
    lower = (text or "").lower()
    # Word-boundary match for question words so "show" is not caught by "how".
    if re.search(r"\b(what|which|how|why|when|who)\b", lower):
        return False
    if any(m in lower for m in CONTENT_QUESTION_MARKERS):
        return False
    return any(kw in lower for kw in DIRECT_MEDIA_KEYWORDS)


# Plain-text triggers for the "send me the full PDF" follow-up that the
# catalogue product-list footer prompts for.
CATALOGUE_PDF_TRIGGERS = (
    "pdf", "send pdf", "catalogue pdf", "catalog pdf", "full catalogue",
    "full catalog", "send catalogue", "send catalog", "send document",
    "catalogue document", "catalog document", "brochure pdf",
    "price list pdf", "product list pdf",
)


def _wants_catalogue_pdf(text) -> bool:
    """True when the plain-text message is a short request for the catalogue PDF."""
    if not text:
        return False
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", (text or "").lower()).strip()
    if not cleaned or len(cleaned) > 40:
        return False
    # Direct phrase match (most common: just "pdf").
    if cleaned in CATALOGUE_PDF_TRIGGERS:
        return True
    # Substring match for multi-word triggers only when the cleaned message
    # is itself short — protects against catching "what is in the pdf" etc.
    if len(cleaned) <= 32:
        for trigger in CATALOGUE_PDF_TRIGGERS:
            if " " in trigger and trigger in cleaned:
                return True
    return False


# Words that mean the user wants the catalogue document itself. Broader
# DIRECT_MEDIA_KEYWORDS (e.g. "menu", "new arrival") should not trigger a PDF.
_CATALOGUE_REQUEST_WORDS = (
    "catalogue", "catalog", "brochure", "product list", "price list",
    "product lineup", "product range",
)


def _wants_catalogue(text) -> bool:
    """True when the text asks for the product catalogue document."""
    lower = (text or "").lower()
    return any(w in lower for w in _CATALOGUE_REQUEST_WORDS)


def _wants_new_arrivals(text) -> bool:
    """True when the text asks for new releases specifically."""
    lower = (text or "").lower()
    return any(w in lower for w in ("arrival", "launch", "latest", "release", "new product"))


# WhatsApp list-menu payload limits (send2.digital / Meta):
#   - 10 sections max
#   - 10 rows per section max
#   - title <= 24 chars
#   - description <= 72 chars
_LIST_TITLE_LIMIT = 24
_LIST_DESC_LIMIT = 72
_LIST_MAX_SECTIONS = 5
_LIST_MAX_ROWS_PER_SECTION = 10


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_catalog_summary(user_text: str) -> dict | None:
    """Build an interactive product-list payload for direct catalogue / new-arrival
    queries (matches `DIRECT_MEDIA_KEYWORDS`).

    Returns a dict shaped like:
        {
            "text": "<body line + PDF hint>",  # plain-text body for send_whatsapp_list_menu
            "header": "Browse our brochure",
            "footer": "Reply *PDF* for the full brochure document.",
            "button_text": "View Products",
            "interactive": {"type": "list", "sections": [...]},
            "media_url": "<catalogue PDF url or None>",
            "media_type": "<catalogue PDF type or None>",
        }

    Returns ``None`` when CATALOG_DELIVERY_MODE is "pdf" (legacy direct-PDF
    fallback), when the products table has no structured rows, or when the
    lookup raises.
    """
    if CATALOG_DELIVERY_MODE == "pdf":
        return None

    lower = (user_text or "").lower()
    wants_arrivals = (
        "arrival" in lower or "launch" in lower or "latest" in lower or "new product" in lower or "release" in lower
    )

    try:
        from backend.database import list_products, get_db_context
        if wants_arrivals:
            products = list_products(category="new_arrival", limit=8)
        else:
            products = list_products(category="catalogue", limit=8)
            if not products:
                products = list_products(limit=8)
    except Exception as e:
        logger.warning(f"catalog summary product lookup failed: {e}")
        return None

    if not products:
        return None

    sections = []
    for cat in sorted({(p.get("category") or "products") for p in products}):
        rows = []
        for p in products:
            if (p.get("category") or "products") != cat:
                continue
            pid = p.get("id")
            if pid is None:
                continue
            price = p.get("price")
            unit = p.get("unit") or ""
            desc_parts = []
            if price:
                desc_parts.append(f"₹{price}" + (f" / {unit}" if unit else ""))
            short = p.get("short_description") or p.get("description") or ""
            if short:
                desc_parts.append(short)
            description = " • ".join(desc_parts) or "Tap to view details"
            rows.append({
                "id": f"product_{pid}",
                "title": _truncate(p.get("name") or f"Product {pid}", _LIST_TITLE_LIMIT),
                "description": _truncate(description, _LIST_DESC_LIMIT),
            })
            if len(rows) >= _LIST_MAX_ROWS_PER_SECTION:
                break
        if rows:
            sections.append({
                "title": _truncate(cat.title(), _LIST_TITLE_LIMIT),
                "rows": rows,
            })
        if len(sections) >= _LIST_MAX_SECTIONS:
            break

    if not sections:
        return None

    # Catalogue PDF fallback metadata for the "Reply *PDF*" text flow.
    media_url = None
    media_type = None
    try:
        from backend.database import get_db_context
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT media_url, media_type FROM products "
                "WHERE category = 'catalogue' AND media_url IS NOT NULL AND is_active = 1 "
                "ORDER BY sort_order ASC LIMIT 1"
            ).fetchone()
        if row:
            media_url = row[0]
            media_type = row[1]
    except Exception as e:
        logger.debug(f"catalogue PDF lookup failed: {e}")

    if wants_arrivals:
        body = "Here are our latest products — tap to see details."
    else:
        body = "Browse our brochure — tap to see details."

    # The "Reply *PDF*" hint goes in the footer because the body becomes the
    # list-menu body, which is rendered above the section list.
    footer = "Reply *PDF* for the full brochure document."

    return {
        "text": body,
        "header": "Our Products",
        "body": body,
        "footer": footer,
        "button_text": "View Products",
        "interactive": {"type": "list", "sections": sections, "body": body, "header": "Our Products", "footer": footer, "button_text": "View Products"},
        "media_url": media_url,
        "media_type": media_type,
    }


def build_catalog_text_fallback(user_text: str) -> dict | None:
    """Legacy behaviour: return a plain-text summary + Browse button for the
    legacy PDF-mode direct-media branch in the webhook. Used only when
    CATALOG_DELIVERY_MODE == "pdf" or when list-building falls through.
    """
    lower = (user_text or "").lower()
    wants_arrivals = "arrival" in lower or "launch" in lower or "latest" in lower or "new product" in lower or "release" in lower
    try:
        from backend.database import list_products
        if wants_arrivals:
            products = list_products(category="new_arrival", limit=8)
        else:
            products = list_products(category="catalogue", limit=8)
            if not products:
                products = list_products(limit=8)
    except Exception as e:
        logger.warning(f"catalog summary product lookup failed: {e}")
        return None

    if not products:
        return None

    lines = ["✨ Here's what we have for you:"]
    for i, p in enumerate(products[:8], start=1):
        price = f" — ₹{p['price']}" if p.get("price") else ""
        desc = (p.get("short_description") or p.get("description") or "")[:60]
        lines.append(f"{i}. {p['name']}{price}")
        if desc:
            lines.append(f"   {desc}")
    lines.append("\nTap below to explore more.")

    buttons = [
        {"type": "reply", "reply": {"id": "menu_products", "title": "Browse Products"}},
    ]
    return {"text": "\n".join(lines), "buttons": buttons}


def _is_distributor(wa_id) -> bool:
    """Return True if wa_id is a registered B2B distributor."""
    if not wa_id:
        return False
    try:
        from backend.database import get_db_context
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT 1 FROM distributors WHERE wa_id = ?", (str(wa_id),)
            ).fetchone()
            return row is not None
    except Exception as e:
        logger.warning(f"distributor check failed for {wa_id}: {e}")
        return False


async def _handle_b2b_message(user_text: str, wa_id: str) -> dict:
    """Route a recognized distributor through the B2B orchestrator.

    The B2B flow sends its own replies (via the shared WhatsApp sender), so we
    signal ``whatsapp_sent=True`` and return no text so the webhook does not
    double-send.
    """
    try:
        from backend.services.orchestrator import process_incoming_message
        result = await process_incoming_message(wa_id, user_text)
        status = result.get("status", "processed")
        logger.info(f"B2B_ROUTE | wa_id={wa_id} | status={status} | msg='{user_text[:80]}'")
        return {
            "answer": "",
            "media_url": None,
            "media_type": None,
            "whatsapp_sent": True,
            "interactive": None,
            "query_type": "b2b_distributor",
        }
    except Exception as e:
        logger.error(f"B2B_ROUTE_FAILED | wa_id={wa_id} | error={e}")
        # Fall back to the normal FAQ/KB handling below.
        return None


def _is_button_reply(raw_message) -> bool:
    if not isinstance(raw_message, dict):
        return False
    return (
        raw_message.get("type") == "interactive"
        and raw_message.get("interactive", {}).get("type") in ("button_reply", "list_reply")
    )


def _interactive_reply_id(raw_message) -> str:
    if not _is_button_reply(raw_message):
        return ""
    interactive = raw_message.get("interactive", {})
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    return str(reply.get("id") or "").strip()


def _try_send_new_arrivals_pdf(wa_id) -> bool:
    if not wa_id:
        return False
    try:
        from kb.services.whatsapp import send_new_arrivals_pdf
        return bool(send_new_arrivals_pdf(wa_id))
    except Exception as e:
        logger.debug(f"send_new_arrivals_pdf import/send failed: {e}")
        return False


def get_buttons_for_query(text) -> list | None:
    lower = (text or "").lower()
    for intent in BUTTON_INTENTS:
        if any(kw in lower for kw in intent["keywords"]):
            return intent["buttons"]
    return None


UNCERTAIN_PHRASES = [
    "i don't know", "i dont know", "i do not know", "don't know", "dont know", "do not know",
    "i'm not sure", "i am not sure", "im not sure", "not sure", "not certain", "not confident",
    "i don't have information", "i do not have information", "don't have information",
    "do not have information", "not have any information", "no information",
    "not enough information", "don't have enough information", "do not have enough information",
    "i don't have enough", "i do not have enough",
    "can't answer", "cannot answer", "can not answer", "unable to answer", "not able to answer",
    "unable to find", "couldn't find", "could not find", "no answer found",
    "not able to help", "beyond my knowledge", "no relevant information",
    "nothing in the context", "not in the context",
]


def is_uncertain_answer(answer: str) -> bool:
    if not answer:
        return False
    lower = answer.lower()
    return any(phrase in lower for phrase in UNCERTAIN_PHRASES)


def get_greeting_response(text: str) -> str:
    return generate_greeting(text)


async def forward_to_bot(query_type, user_text, wa_id=None, raw_message=None):
    # A tenant that switched the FAQ or KB substrate off gets the profile's
    # polite refusal instead of an answer from a pipeline it disabled. The
    # refusal is returned as a normal answer so callers send it unchanged;
    # no fallback to the other pipeline is attempted for a disabled feature.
    if wa_id:
        try:
            from shared.tenancy.gating import guard_result
            feature = "faq" if query_type == "faq" else "kb"
            blocked = guard_result(wa_id, feature)
        except Exception as exc:
            logger.debug(f"{query_type} gate unavailable: {exc}")
            blocked = None
        if blocked:
            logger.info(f"{feature.upper()}_BLOCKED | {wa_id} | {feature} off for tenant")
            return {
                "answer": blocked["message"],
                "media_url": None,
                "media_type": None,
                "whatsapp_sent": False,
                "interactive": None,
                "query_type": query_type,
                "disabled": feature,
            }

    if query_type == "faq":
        from backend.faq.service import handle_faq_query
        data = await handle_faq_query({"message": user_text, "wa_id": wa_id})
    else:
        from kb.service import handle_kb_query
        data = await handle_kb_query(
            wa_id=wa_id or "",
            message=user_text,
            sender_name="",
            update_session=True,
            raw_message=raw_message,
        )
    logger.info(f"{query_type} bot response keys: {list(data.keys())}, media_url={data.get('media_url')}, media_type={data.get('media_type')}, whatsapp_sent={data.get('whatsapp_sent')}")
    return data


async def process_message(user_text: str, wa_id: str = None, raw_message: dict = None):
    is_btn_reply = _is_button_reply(raw_message)
    query_type = classify_query(user_text)

    # Interactive button/list replies (that weren't handled by the button
    # registry in the webhook) carry structured IDs (prod_*, menu_*, action_*)
    # that the KB handler's state machine knows how to route.  The plain-text
    # classifier cannot interpret those IDs, so force interactive replies that
    # would otherwise be misclassified as "greeting" to the KB bot.
    if is_btn_reply and query_type in ("greeting", ""):
        query_type = "kb"
        logger.info(f"Interactive reply forced to KB: {user_text[:80]}")
    logger.info(f"Query classified as: {query_type}")

    result = {"answer": "", "media_url": None, "media_type": None, "whatsapp_sent": False, "interactive": None, "query_type": query_type}

    interactive_id = _interactive_reply_id(raw_message)
    if is_btn_reply and interactive_id in ("new_arrival", "menu_new_arrivals"):
        sent = _try_send_new_arrivals_pdf(wa_id)
        if sent:
            result["answer"] = "📄 Here is the latest new releases PDF."
            result["query_type"] = "new_arrivals_pdf"
            result["whatsapp_sent"] = True
            logger.info(f"NEW_ARRIVALS_PDF_SENT | {wa_id}")
            return result

    # ── B2B DISTRIBUTOR PRE-ROUTE ─────────────────────────────────────────
    # Recognized distributors go through the dedicated B2B flow (place order,
    # catalogue, price list, schemes, outstanding, tickets, etc.). The B2B flow
    # sends its own replies, so when it handles the message we stop here.
    if wa_id and _is_distributor(wa_id):
        b2b = await _handle_b2b_message(user_text, wa_id)
        if b2b is not None:
            return b2b

    # ── DIRECT CATALOGUE / NEW-ARRIVALS QUERY ─────────────────────────────
    # Bypass the LLM and land the user directly on the interactive product
    # list (with `product_<id>` rows). The webhook's list-menu branch picks
    # this up via `result["interactive"]`. In legacy "pdf" mode this returns
    # None and the webhook falls through to the original PDF behaviour.
    if not is_btn_reply and is_direct_media_query(user_text):
        if _wants_new_arrivals(user_text):
            sent = _try_send_new_arrivals_pdf(wa_id)
            if sent:
                result["answer"] = "📄 Here is the latest new releases PDF."
                result["query_type"] = "new_arrivals_pdf"
                result["whatsapp_sent"] = True
                logger.info(f"NEW_ARRIVALS_PDF_SENT_DIRECT | {wa_id}")
                return result

        summary = build_catalog_summary(user_text)
        if summary:
            result["answer"] = summary["text"]
            result["interactive"] = summary["interactive"]
            result["media_url"] = summary.get("media_url")
            result["media_type"] = summary.get("media_type")
            result["query_type"] = "catalog_list"
            logger.info(f"CATALOG_LIST | wa_id={wa_id} | sections={len(summary['interactive']['sections'])}")
            return result
        # No structured products (catalogue PDFs are no longer imported into
        # the products table). For a catalogue request, send the PDF directly.
        if _wants_catalogue(user_text) and not _wants_new_arrivals(user_text):
            try:
                from kb.services.whatsapp import send_catalogue_pdf
            except Exception as e:
                logger.debug(f"send_catalogue_pdf import failed: {e}")
                send_catalogue_pdf = None
            if send_catalogue_pdf is not None:
                sent = send_catalogue_pdf(wa_id)
                result["answer"] = "📄 Here is the latest brochure."
                result["query_type"] = "catalog_pdf"
                result["whatsapp_sent"] = bool(sent)
                logger.info(f"CATALOG_PDF_SENT_DIRECT | {wa_id} | sent={sent}")
                return result

    # ── CATALOGUE PDF FOLLOW-UP ────────────────────────────────────────────
    # Plain-text "PDF" / "catalogue pdf" / "send pdf" reply: send the catalogue
    # PDF document if one is registered. Used after the product list footer
    # prompt "Reply *PDF* for the full catalogue document."
    if not is_btn_reply and _wants_catalogue_pdf(user_text):
        try:
            from kb.services.whatsapp import send_catalogue_pdf
        except Exception as e:
            logger.debug(f"send_catalogue_pdf import failed: {e}")
            send_catalogue_pdf = None
        if send_catalogue_pdf is not None:
            sent = send_catalogue_pdf(wa_id)
            result["answer"] = "📄 Sending you the catalogue PDF…"
            result["query_type"] = "catalog_pdf"
            result["whatsapp_sent"] = bool(sent)
            logger.info(f"CATALOG_PDF_SENT | {wa_id} | sent={sent}")
            return result

    # ── PROFILE-DEFINED INFORMATIONAL INTENTS ─────────────────────────────
    # A typed query that clearly names an answered panel (technologies,
    # projects, careers, benefits...) replies from the tenant's own profile
    # text — no LLM and no corpus needed. Falls through untouched when the
    # tenant configured no answer for the matched intent.
    try:
        from backend.services import intent_answers
        intent_reply = intent_answers.answer_for_text(wa_id, user_text)
        if intent_reply:
            result["answer"] = intent_reply
            result["query_type"] = "intent"
            logger.info(f"INTENT_REPLY | {wa_id} | matched informational intent")
            return result
    except Exception as e:
        logger.debug(f"Intent answer lookup failed (continuing): {e}")

    if query_type == "greeting":
        # Show the main menu directly; no LLM greeting text is needed.
        result["answer"] = ""
        result["interactive"] = _get_greeting_menu(wa_id)
        return result

    data = await forward_to_bot(query_type, user_text, wa_id, raw_message)

    skip_fallback = query_type == "kb" and any(kw in user_text.lower() for kw in NO_FALLBACK_KB_QUERIES)

    if not skip_fallback and (not data.get("answer") or is_uncertain_answer(data.get("answer"))):
        fallback_type = "kb" if query_type == "faq" else "faq"
        logger.info(f"Falling back to {fallback_type} bot: primary returned empty/uncertain answer")
        data = await forward_to_bot(fallback_type, user_text, wa_id, raw_message)

    answer = data.get("answer", "")
    if not answer or is_uncertain_answer(answer):
        answer = (
            "Hmm, I couldn't find a solid answer for that one 🤔 "
            "Try rephrasing, or tap below and our team will jump in to help! 🙋"
        )
        data = {}

    result["answer"] = answer
    result["media_url"] = data.get("media_url")
    result["media_type"] = data.get("media_type")
    result["whatsapp_sent"] = bool(data.get("whatsapp_sent"))
    result["interactive"] = data.get("interactive")

    if not is_btn_reply:
        existing = result["interactive"]
        if existing and existing.get("type") == "button":
            buttons = list(existing.get("buttons") or [])
        elif existing is None:
            buttons = list(get_buttons_for_query(user_text) or [])
        else:
            buttons = None

        if buttons is not None:
            # Documents are no longer sent to customers. Drop any "View
            # Document" attachment button and the document media payload so
            # nothing attempts to send the file.
            buttons = [
                b for b in buttons
                if (b.get("reply") or {}).get("id") != DOCUMENT_BUTTON_ID
            ]
            if _media_is_document(result.get("media_type")):
                result["media_url"] = None
                result["media_type"] = None
            # WhatsApp allows max 3 buttons.
            if len(buttons) > 3:
                buttons = buttons[:3]
            result["interactive"] = {"type": "button", "buttons": buttons} if buttons else None

    return result
