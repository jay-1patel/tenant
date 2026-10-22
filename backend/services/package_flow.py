"""Tour package browsing on WhatsApp, built on the send2.digital list menu.

The tours vertical keeps its tour packages in the ``products`` table — one row
per package, with the package metadata in ``attrs_json`` (``package_name``,
``destination``, ``duration``, ``itinerary``, ``includes``, ``excludes``,
``terms_conditions``). This service turns those rows into a browsing
experience:

    "Tour Packages"   -> WhatsApp list menu of the packages
    a package row     -> the package card + a "Book This Package" button
    that button       -> the ``book_package`` flow (name, package, phone)
    the flow          -> a lead + a handoff that floats into the live inbox

Three quirks drive the design:

* send2.digital delivers a tapped list row as the row TITLE, not as its id, so
  every lookup matches the title first and only then the id.
* the profile menu button that opens the catalogue is a *button*, so tapping it
  also arrives as plain text — the title match has to cover "Tour Packages".
* WhatsApp truncates a row title to 24 characters, and that truncated string
  is what comes back on the tap. The title is matched in both forms.

Prices are deliberately NOT shown: the tours profile lists "package prices"
under ``never_state`` — pricing varies by date and group size, so the card
points at the team instead of quoting a number.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("package_flow")

# Row ids we mint for the list menu.
PACKAGE_ROW_PREFIX = "pkg_"
BOOK_ROW_PREFIX = "pkg_book_"

# The booking button on the package card. send2 delivers the tap as this
# title, so it doubles as the "the user wants to book" signal.
BOOK_BUTTON_TITLE = "Book This Package"

# CTA shown on the list menu itself.
LIST_BUTTON_TEXT = "Select Package"

# The flow that captures the booking enquiry.
BOOK_FLOW_NAME = "book_package"

# WhatsApp limits (the send2 wrapper clamps again on its side).
ROW_TITLE_MAX = 24
ROW_DESC_MAX = 72
SECTION_TITLE_MAX = 24
MAX_ROWS = 10
MAX_SECTIONS = 10

# Card budget. The card is a text message that can be up to WhatsApp text limits (4096 chars).
CARD_MAX_CHARS = 3800
ITINERARY_MAX_LINES = 30
INCLUDES_MAX_BULLETS = 25
EXCLUDES_MAX_BULLETS = 25
TERMS_MAX_CHARS = 1200

# Phrases that ask for the package catalogue.
LIST_PHRASES = {
    "package", "packages", "tour package", "tour packages", "package list",
    "tour package list", "packages list", "list packages", "show packages",
    "show me packages", "see packages", "all packages", "our packages",
    "available packages", "browse packages", "packages available",
    "holiday package", "holiday packages", "package details",
}

# The tap on the booking button of a package card.
BOOK_BUTTON_ALIASES = {
    "book this package", "book this tour", "enquire this package",
    "enquire about this package",
}

# Booking phrasing — only used to decide that a named package should go
# straight into the booking flow instead of the details card.
BOOK_VERBS = (
    "book", "booked", "booking", "reserve", "reservation", "enquire",
    "enquiry", "inquire", "inquiry", "interested",
)


# ── helpers ────────────────────────────────────────────────────────────────

def _db():
    # `database` (backend/database.py) resolves when backend/ is on sys.path —
    # the style used by state_manager and the services layer.
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
    """Lowercase, drop punctuation and emoji, collapse whitespace."""
    if not text:
        return ""
    cleaned = re.sub(
        r"[\u2190-\u21FF\u2300-\u27BF\uFE0E\uFE0F\U0001F000-\U0001FAFF]", " ",
        str(text),
    )
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _package_by_id(packages: list, product_id) -> Optional[dict]:
    if product_id in (None, ""):
        return None
    for pkg in packages:
        if str(pkg.get("id")) == str(product_id):
            return pkg
    return None


def _package_by_name(packages: list, name: str) -> Optional[dict]:
    needle = _normalize(name)
    if not needle:
        return None
    for pkg in packages:
        if _normalize(package_name(pkg)) == needle:
            return pkg
    return None


# ── the catalogue ──────────────────────────────────────────────────────────

def tour_packages(tenant_id: str = None) -> list:
    """Active tour packages for a tenant.

    A "tour package" is a product row carrying travel metadata
    (``package_name`` / ``destination``). A tenant that sells ordinary
    products never matches, so the package UI stays out of its way.
    """
    try:
        rows = _db().list_products(active_only=True, limit=100, tenant_id=tenant_id)
    except Exception as e:
        logger.warning("package catalogue unavailable: %s", e)
        return []

    packages = []
    for row in rows or []:
        attrs = row.get("attrs_json")
        if not isinstance(attrs, dict):
            attrs = {}
        if not (attrs.get("package_name") or attrs.get("destination")):
            continue
        merged = dict(row)
        merged["attrs_json"] = attrs
        packages.append(merged)
    return packages


def package_name(pkg: dict) -> str:
    attrs = pkg.get("attrs_json") or {}
    return str(attrs.get("package_name") or pkg.get("name") or "").strip()


def package_attrs(pkg: dict) -> dict:
    attrs = pkg.get("attrs_json")
    if isinstance(attrs, dict) and attrs:
        return attrs
    return pkg if isinstance(pkg, dict) else {}


def package_row_id(pkg: dict) -> str:
    return f"{PACKAGE_ROW_PREFIX}{pkg.get('id')}"


def package_row_title(pkg: dict) -> str:
    """The title as WhatsApp will show it — and as it comes back on a tap."""
    return package_name(pkg)[:ROW_TITLE_MAX]


def _row_description(pkg: dict) -> str:
    attrs = package_attrs(pkg)
    bits = []
    destination = str(attrs.get("destination") or "").strip()
    if destination:
        bits.append(destination)
    duration = str(attrs.get("duration") or "").strip()
    if duration:
        bits.append(duration)
    return " • ".join(bits)[:ROW_DESC_MAX]


def package_sections(packages: list) -> list:
    """Group the packages into list-menu sections, one per destination."""
    grouped = {}
    order = []
    for pkg in packages:
        name = package_name(pkg)
        if not name:
            continue
        destination = str(package_attrs(pkg).get("destination") or "").strip()
        destination = destination or "Tour Packages"
        if destination not in grouped:
            grouped[destination] = []
            order.append(destination)
        grouped[destination].append({
            "id": package_row_id(pkg),
            "title": name[:ROW_TITLE_MAX],
            "description": _row_description(pkg),
        })

    sections = []
    total = 0
    for destination in order:
        if len(sections) >= MAX_SECTIONS or total >= MAX_ROWS:
            break
        rows = []
        for row in grouped[destination]:
            if total >= MAX_ROWS:
                break
            rows.append(row)
            total += 1
        if rows:
            sections.append({
                "title": destination[:SECTION_TITLE_MAX],
                "rows": rows,
            })
    return sections


# ── the package card ───────────────────────────────────────────────────────

def _bullets(raw, limit: int, item_limit: int = 300) -> list:
    if not raw:
        return []
    parts = re.split(r"[\n\r]+|(?<=\s)•", str(raw))
    out = []
    for part in parts:
        text = part.strip(" \t\r\n•-–—*")
        if not text:
            continue
        out.append("• " + text[:item_limit])
        if len(out) >= limit:
            break
    return out


def _itinerary_lines(raw, limit: int = ITINERARY_MAX_LINES, item_limit: int = 500) -> list:
    if not raw:
        return []
    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
    # Some catalogue rows lost their newlines on import. Put them back by
    # splitting on the "Day 01 :" marker that starts every line.
    text = re.sub(r"(?<!^)(?=Day\s*\d+\s*:)", "\n", text)
    out = []
    for part in text.split("\n"):
        line = part.strip(" \t\r\n•-–—*")
        if not line:
            continue
        out.append("• " + line[:item_limit])
        if len(out) >= limit:
            break
    return out


def package_card(pkg: dict) -> str:
    """The human-readable package details shown on a tap."""
    attrs = package_attrs(pkg)
    name = package_name(pkg)
    lines = [f"🎒 *{name}*", ""]

    destination = str(attrs.get("destination") or "").strip()
    if destination:
        lines.append(f"📍 *Destination:* {destination}")
    duration = str(attrs.get("duration") or "").strip()
    if duration:
        lines.append(f"🗓️ *Duration:* {duration}")
    max_person = attrs.get("max_person")
    if max_person:
        lines.append(f"👥 *Max guests:* {max_person}")
    # "package prices" is on the tours never_state list: point at the team.
    lines.append("💰 *Price:* varies by date and group size — our team confirms the quote")

    itinerary = _itinerary_lines(attrs.get("itinerary"))
    if itinerary:
        lines += ["", "🗺️ *Itinerary*", *itinerary]

    includes = _bullets(attrs.get("includes"), INCLUDES_MAX_BULLETS)
    if includes:
        lines += ["", "✅ *Included*", *includes]

    excludes = _bullets(attrs.get("excludes"), EXCLUDES_MAX_BULLETS)
    if excludes:
        lines += ["", "❌ *Not included*", *excludes]

    terms = str(attrs.get("terms_conditions") or "").strip()
    if terms:
        if len(terms) > TERMS_MAX_CHARS:
            terms = terms[:TERMS_MAX_CHARS].rsplit(" ", 1)[0]
        lines += ["", f"📄 *Terms (summary)*: {terms}"]

    card = "\n".join(lines).strip()
    if len(card) > CARD_MAX_CHARS:
        card = card[:CARD_MAX_CHARS].rsplit("\n", 1)[0]
    return card


# ── pending package (which card the user is looking at) ───────────────────

def remember_package(wa_id: str, pkg: dict) -> None:
    """Remember the package the user is currently looking at.

    The tap on "Book This Package" carries no id, so this is what identifies
    the package the user wants to book.
    """
    if not pkg:
        return
    payload = {
        "id": pkg.get("id"),
        "name": package_name(pkg),
        "destination": str(package_attrs(pkg).get("destination") or ""),
    }
    sm = _state()
    try:
        sm.ensure_conversation_row(wa_id)

        def apply(ctx):
            ctx["pending_package"] = payload

        sm.update_context_with_retry(wa_id, apply)
    except Exception as e:
        logger.warning("could not remember package for %s: %s", wa_id, e)


def pending_package(wa_id: str) -> dict:
    sm = _state()
    try:
        ctx, _version = sm.read_user_context(wa_id)
    except Exception as e:
        logger.debug("could not read pending package for %s: %s", wa_id, e)
        return {}
    pending = ctx.get("pending_package")
    return pending if isinstance(pending, dict) else {}


# ── matching ───────────────────────────────────────────────────────────────

def find_package(tenant_id: str, text: str, packages: list = None) -> Optional[dict]:
    """Find the tour package a message refers to.

    send2 hands back the row TITLE, so the truncated title is matched first
    and the full name second. A whole-word mention inside a sentence counts
    too ("details of Best of Gujarat").
    """
    needle = _normalize(text)
    if not needle:
        return None
    if packages is None:
        packages = tour_packages(tenant_id)
    if not packages:
        return None

    for pkg in packages:
        if needle == _normalize(package_row_title(pkg)):
            return pkg
    for pkg in packages:
        if needle == _normalize(package_name(pkg)):
            return pkg
    for pkg in packages:
        title = _normalize(package_row_title(pkg))
        if len(title) >= 4 and re.search(rf"\b{re.escape(title)}\b", needle):
            return pkg
    return None


def _package_button_keys(tenant_id: str) -> set:
    """Ids and titles of the profile menu button that opens the catalogue."""
    keys = set()
    try:
        from shared.tenancy.loader import get_tenant_profile
        profile = get_tenant_profile(tenant_id)
    except Exception as e:
        logger.debug("could not read profile menu for %s: %s", tenant_id, e)
        return keys
    for button in profile.menu.buttons:
        if button.intent == "package_details" or button.id == "menu_packages":
            if button.id:
                keys.add(button.id)
            if button.title:
                keys.add(button.title)
                keys.add(_normalize(button.title))
    return keys


def is_package_list_request(tenant_id: str, text: str, pressed_id: str = "") -> bool:
    """True when the message is asking for the package catalogue."""
    raw = (text or "").strip()
    if (pressed_id or "").strip() in ("menu_packages", "menu_tour_packages"):
        return True
    if raw in ("menu_packages", "menu_tour_packages"):
        return True
    needle = _normalize(raw)
    if not needle:
        return False
    if needle in LIST_PHRASES:
        return True
    keys = _package_button_keys(tenant_id)
    return needle in {_normalize(k) for k in keys if k}


def _has_book_verb(text: str) -> bool:
    needle = f" {_normalize(text)} "
    return any(f" {verb}" in needle or needle.endswith(f" {verb}") for verb in BOOK_VERBS)


def _is_book_button_tap(text: str) -> bool:
    return _normalize(text) in BOOK_BUTTON_ALIASES


QUESTION_CUES_RE = re.compile(
    r"\b(where|which|why|who|whom|whose|when|how|what|can\s+i|can\s+we|is\s+there|are\s+there|will\s+there|will\s+we|will\s+i|do\s+you|do\s+we|could\s+you|tell\s+me\s+about\s+the)\b",
    re.IGNORECASE,
)

PACKAGE_ATTR_RE = re.compile(
    r"\b(pickup|pick\s*up|drop|drop\s*off|dropoff|hotel|hotels|stay|staying|room|rooms|resort|resorts|food|meal|meals|lunch|dinner|breakfast|veg|jain|flight|flights|airfare|train|ticket|tickets|transport|transportation|vehicle|cab|car|tempo|innova|suv|sedan|refund|cancel|cancellation|luggage|baggage|guide|driver|timing|timings|allocated|allocation|customise|customize|customization|discount|offer|coupon|itinerary\s+details|day\s*\d+)\b",
    re.IGNORECASE,
)


def _is_specific_package_question(text: str, pkg: dict) -> bool:
    """Return True if `text` is asking a specific question about package logistics/attributes
    (e.g. pickup, hotel, food, timings) rather than simply asking to view
    the package card/brochure."""
    if not text:
        return False
    raw = text.strip()
    has_qmark = "?" in raw
    has_attr = bool(PACKAGE_ATTR_RE.search(raw))
    has_question_cue = bool(QUESTION_CUES_RE.search(raw))

    if has_attr:
        return True
    if has_qmark and has_question_cue:
        return True

    clean = _normalize(raw)
    pkg_title = _normalize(package_name(pkg))
    words = clean.split()
    if len(words) > len(pkg_title.split()) + 3 and has_question_cue:
        return True

    return False


# ── sending ────────────────────────────────────────────────────────────────

def _brand_name(tenant_id: str) -> str:
    try:
        from shared.tenancy.loader import get_tenant_profile
        profile = get_tenant_profile(tenant_id)
        if profile and profile.brand and profile.brand.name:
            return profile.brand.name
    except Exception as e:
        logger.debug("could not read brand for %s: %s", tenant_id, e)
    return "Tour Packages"


async def send_package_list(wa_id: str, tenant_id: str = None) -> bool:
    """Send the package catalogue as a WhatsApp list menu."""
    packages = tour_packages(tenant_id)
    sections = package_sections(packages)
    if not sections:
        return False

    header = f"{_brand_name(tenant_id)} — Tour Packages"[:60]
    body = ("Here are our tour packages. Tap one to see the full itinerary, "
            "what's included and what's not.")
    sender = _sender()
    return await sender.send_list_menu(
        wa_id, header, body, LIST_BUTTON_TEXT, sections, tenant_id=tenant_id,
    )


async def send_package_details(wa_id: str, pkg: dict, tenant_id: str = None) -> bool:
    """Send the package card plus the booking button."""
    remember_package(wa_id, pkg)
    sender = _sender()
    card_ok = await sender.send_text_message(wa_id, package_card(pkg))
    buttons = [{
        "type": "reply",
        "reply": {
            "id": f"{BOOK_ROW_PREFIX}{pkg.get('id')}",
            "title": BOOK_BUTTON_TITLE,
        },
    }]
    body = (f"Would you like to book *{package_name(pkg)}*? "
            "Share your details and our travel team will confirm availability.")
    button_ok = await sender.send_button_message(
        wa_id, body, buttons, tenant_id=tenant_id,
    )
    return bool(card_ok and button_ok)


# ── the booking hand-off ───────────────────────────────────────────────────

async def _start_booking(wa_id: str, pkg: Optional[dict], tenant_id: str) -> dict:
    """Start the ``book_package`` flow, seeded with the package when known."""
    try:
        from services import flow_runner
    except ImportError:
        from backend.services import flow_runner

    seed = {}
    if pkg:
        seed["package"] = package_name(pkg)

    outcome = flow_runner.start_flow(
        wa_id, BOOK_FLOW_NAME, tenant_id=tenant_id, seed=seed,
    )
    if not outcome.get("handled"):
        logger.warning("book_package flow not started: %s", outcome.get("error"))
        return {"handled": False, "action": "booking", "error": outcome.get("error")}

    sender = _sender()
    for msg in outcome.get("messages") or []:
        if isinstance(msg, dict) and msg.get("type") == "buttons":
            await sender.send_button_message(
                wa_id, msg.get("text", ""), msg.get("buttons", []), tenant_id=tenant_id,
            )
        else:
            await sender.send_text_message(wa_id, msg)

    return {
        "handled": True,
        "action": "booking",
        "package": package_name(pkg) if pkg else "",
    }


# ── the entry point ────────────────────────────────────────────────────────

async def handle_package_action(wa_id: str, text: str, tenant_id: str = None,
                                pressed_id: str = "") -> Optional[dict]:
    """Handle a tour-package interaction.

    Returns ``None`` when the message is not about packages, so the caller
    falls through to the normal intent/flow routing. Otherwise returns a
    result dict describing what was done.
    """
    packages = tour_packages(tenant_id)
    if not packages:
        return None

    raw_id = (pressed_id or "").strip()
    raw_text = (text or "").strip()

    # 1. Explicit row / button ids we minted.
    if raw_id.startswith(BOOK_ROW_PREFIX):
        pkg = _package_by_id(packages, raw_id[len(BOOK_ROW_PREFIX):])
        if pkg:
            return await _start_booking(wa_id, pkg, tenant_id)
    if raw_id.startswith(PACKAGE_ROW_PREFIX):
        pkg = _package_by_id(packages, raw_id[len(PACKAGE_ROW_PREFIX):])
        if pkg:
            await send_package_details(wa_id, pkg, tenant_id)
            return {"handled": True, "action": "package_details",
                    "package": package_name(pkg)}

    # 2. The booking button of the card that was just shown.
    if _is_book_button_tap(raw_text):
        pending = pending_package(wa_id)
        pkg = _package_by_id(packages, pending.get("id")) if pending else None
        return await _start_booking(wa_id, pkg, tenant_id)

    # 3. "Show me the packages" -> the list menu.
    if is_package_list_request(tenant_id, raw_text, raw_id):
        if await send_package_list(wa_id, tenant_id):
            return {"handled": True, "action": "package_list"}
        return None

    # 4. A package named in free text.
    pkg = find_package(tenant_id, raw_text, packages)
    if pkg:
        remember_package(wa_id, pkg)
        if _has_book_verb(raw_text):
            return await _start_booking(wa_id, pkg, tenant_id)
        if _is_specific_package_question(raw_text, pkg):
            logger.info("PACKAGE_SPECIFIC_QUESTION | wa_id=%s | pkg=%s | falling through to FAQ/RAG",
                        wa_id, package_name(pkg))
            return None
        await send_package_details(wa_id, pkg, tenant_id)
        return {"handled": True, "action": "package_details",
                "package": package_name(pkg)}

    return None
