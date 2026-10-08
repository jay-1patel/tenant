"""
Unified WhatsApp menu rendering service.

This module is the single rendering engine for all WhatsApp list/button menus
in the project. It enforces WhatsApp's interactive limits and applies
consistent styling (emojis, truncation, section grouping) across B2C, B2B, and
KB flows.

All database access is lazy-imported inside functions to avoid circular
imports at startup.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


logger = logging.getLogger("menu_service")

# WhatsApp interactive message limits
LIST_ROW_TITLE_MAX = 24
LIST_ROW_DESC_MAX = 72
LIST_SECTION_TITLE_MAX = 24
LIST_HEADER_MAX = 60
LIST_BODY_MAX = 1024
LIST_MAX_ROWS = 10
LIST_MAX_SECTIONS = 3
BUTTON_TITLE_MAX = 20
BUTTON_MAX_COUNT = 3


@dataclass
class MenuItem:
    """A single menu option."""
    id: str
    title: str
    description: str = ""
    section: str = "General"
    icon: str = ""

    def display_title(self) -> str:
        """Return title with icon prepended when available."""
        if self.icon:
            return f"{self.icon} {self.title}".strip()
        return self.title


def _safe_truncate(text: str, limit: int, suffix: str = "…") -> str:
    """Truncate text to limit, preserving whole words when possible."""
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    # Leave room for suffix
    cut = text[: limit - len(suffix)]
    last_space = cut.rfind(" ")
    if last_space > limit // 2:
        cut = cut[:last_space]
    return cut.rstrip() + suffix


def build_list_menu(
    header: str,
    body: str,
    button_text: str,
    items: List[MenuItem],
) -> Dict[str, Any]:
    """
    Build a WhatsApp interactive list menu payload.

    Enforces WhatsApp limits:
      - ≤10 rows total
      - ≤3 sections
      - title ≤24 chars, description ≤72 chars, section title ≤24 chars

    Returns a dict matching the signature expected by
    routing/whatsapp.py::send_whatsapp_list_menu():
        {"header": ..., "body": ..., "button_text": ..., "sections": [...]}
    """
    # Filter invalid items
    valid_items = [
        item for item in items
        if item and str(item.id).strip() and str(item.title).strip()
    ]

    if len(valid_items) > LIST_MAX_ROWS:
        logger.warning(
            "List menu has %d items, truncating to %d", len(valid_items), LIST_MAX_ROWS
        )
        valid_items = valid_items[:LIST_MAX_ROWS]

    # Group by section
    sections_map: Dict[str, List[Dict[str, str]]] = {}
    for item in valid_items:
        section_name = (item.section or "General").strip()
        sections_map.setdefault(section_name, [])
        sections_map[section_name].append({
            "id": str(item.id).strip(),
            "title": _safe_truncate(item.display_title(), LIST_ROW_TITLE_MAX),
            "description": _safe_truncate(item.description, LIST_ROW_DESC_MAX) or "Tap to select",
        })

    sections = [
        {"title": _safe_truncate(name, LIST_SECTION_TITLE_MAX), "rows": rows}
        for name, rows in sections_map.items()
    ]

    if len(sections) > LIST_MAX_SECTIONS:
        logger.warning(
            "List menu has %d sections, merging extras into last section",
            len(sections),
        )
        keep = sections[: LIST_MAX_SECTIONS - 1]
        overflow_rows = []
        for sec in sections[LIST_MAX_SECTIONS - 1 :]:
            overflow_rows.extend(sec["rows"])
        keep.append({
            "title": _safe_truncate("More", LIST_SECTION_TITLE_MAX),
            "rows": overflow_rows,
        })
        sections = keep

    return {
        "type": "list",
        "header": _safe_truncate(header, LIST_HEADER_MAX),
        "body": _safe_truncate(body, LIST_BODY_MAX),
        "button_text": _safe_truncate(button_text, LIST_ROW_TITLE_MAX),
        "sections": sections,
    }


def build_button_menu(body: str, items: List[MenuItem]) -> Dict[str, Any]:
    """
    Build a WhatsApp interactive button menu payload.

    Enforces:
      - ≤3 buttons
      - button title ≤20 chars

    Returns {"type": "buttons", "body": ..., "buttons": [...]}.
    """
    valid_items = [
        item for item in items
        if item and str(item.id).strip() and str(item.title).strip()
    ]

    if len(valid_items) > BUTTON_MAX_COUNT:
        logger.warning(
            "Button menu has %d items, truncating to %d",
            len(valid_items),
            BUTTON_MAX_COUNT,
        )
        valid_items = valid_items[:BUTTON_MAX_COUNT]

    buttons = []
    for item in valid_items:
        buttons.append({
            "type": "reply",
            "reply": {
                "id": str(item.id).strip(),
                "title": _safe_truncate(item.display_title(), BUTTON_TITLE_MAX),
            },
        })

    return {
        "type": "buttons",
        "body": _safe_truncate(body, LIST_BODY_MAX),
        "buttons": buttons,
    }


def _get_brand_name(wa_id: str = "") -> str:
    """Brand name, from the tenant profile when one is available.

    Falls back to the legacy shared config so the pre-tenant stack is unchanged.
    """
    try:
        from .menu_catalog import get_profile_for

        profile = get_profile_for(wa_id)
        if profile is not None:
            name = (profile.brand.name or profile.display_name or "").strip()
            if name:
                return name
    except Exception as e:
        logger.debug("profile brand unavailable, using config: %s", e)

    # Tenancy store still resolves a default tenant even when this user has no
    # profile row (fresh deployments, untagged users) - prefer it over the
    # global env, which belongs to the legacy single-tenant stack.
    try:
        from shared.tenancy import loader
        from shared.tenancy.resolver import resolve_default_tenant

        profile = loader.get_tenant_profile(resolve_default_tenant())
        name = (getattr(profile.brand, "name", "") or profile.display_name or "").strip()
        if name:
            return name
    except Exception as e:
        logger.debug("default tenant brand unavailable, using config: %s", e)

    try:
        from routing.config import BRAND_NAME
        return BRAND_NAME or "TrooGood"
    except Exception:
        return "TrooGood"


def personalize_header(wa_id: str, user_type: str = "b2c") -> str:
    """
    Return a personalized greeting header for the given user type.

    - B2B: "Welcome back, {name}! 🏆 {tier} Tier"
    - B2C / fallback: "Hi there! 👋 Welcome to {brand}"

    Database lookups are performed lazily inside this function.
    """
    brand = _get_brand_name(wa_id)

    if user_type == "b2b" and wa_id:
        try:
            from database import get_db_context
            with get_db_context() as conn:
                row = conn.execute(
                    "SELECT name, tier FROM distributors WHERE wa_id = ?",
                    (wa_id,),
                ).fetchone()
            if row and row["name"]:
                tier = (row["tier"] or "Bronze").strip()
                return f"Welcome back, {row['name']}! 🏆 {tier} Tier"
        except Exception as e:
            logger.debug("Could not personalize B2B header: %s", e)

    # Try to fetch a name from user state context for B2C
    if wa_id:
        try:
            from database import get_user_state
            state = get_user_state(wa_id)
            ctx = state.get("context_json") or {}
            name = ctx.get("name") or ctx.get("customer_name")
            if name:
                return f"Hi {name}! 👋 Welcome to {brand}"
        except Exception as e:
            logger.debug("Could not personalize B2C header: %s", e)

    return f"Hi there! 👋 Welcome to {brand}"


def get_greeting_menu(wa_id: str) -> Dict[str, Any]:
    """
    Return the main menu for a user on first contact / greeting.

    Every user — B2C customer, B2B distributor, or first-time visitor — sees
    the same single KB menu.
    """
    from .menu_catalog import get_kb_main_menu, get_profile_for

    items = get_kb_main_menu(wa_id, user_type="b2c")
    header = personalize_header(wa_id, "b2c")
    body = "What would you like to explore today?"
    try:
        from database import get_menu_settings
        settings = get_menu_settings("kb_main")
        button_text = settings.get("button_text") or "Show Options"
    except Exception:
        button_text = "Show Options"

    # A tenant profile owns the wording of its own menu.
    profile = get_profile_for(wa_id)
    if profile is not None:
        menu = profile.menu
        if menu.body:
            body = menu.body
        if menu.button_text:
            button_text = menu.button_text

    return build_list_menu(header, body, button_text, items)
