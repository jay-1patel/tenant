"""
Single source of truth for WhatsApp menu items.

This module defines the single main menu used by B2C, B2B, and KB flows.
It does NOT render menus — that is handled by services.menu_service. All
database lookups are lazy-imported inside functions to avoid circular
imports at startup.

CRITICAL: Existing row IDs must never be changed. Workflows in
bots/customer_b2c/workflows.py, bots/distributor_b2b/workflows.py, and
kb/services/kb_handler.py rely on these exact IDs.

┌─────────────────────────────────────────────────────────────────────────┐
│ MENU EDITOR BUG THIS FILE FIXES                                         │
│                                                                         │
│ The old _maybe_db_menu() was ALL-OR-NOTHING: if the `menus` table had   │
│ ANY row for a menu_key, the ENTIRE hard-coded default menu was replaced │
│ by just those DB rows. But the admin editor writes ONE row per edit     │
│ (per-item upserts), so:                                                 │
│                                                                         │
│   - Toggling ONE item inactive left the DB with a single inactive row   │
│     → 0 active rows → whole menu fell back to defaults (or collapsed    │
│     to one item when a single active row existed).                      │
│   - The editor's GET returned only the raw DB rows, so after the first  │
│     edit the other menu items vanished from the editor entirely.        │
│                                                                         │
│ FIX: DB rows are now PER-ITEM OVERRIDES merged on top of the code       │
│ defaults (title/description/section/icon/sort_order/is_active). The     │
│ runtime menu = defaults with overrides applied, inactive items removed. │
│ The admin editor always receives the full merged list.                  │
└─────────────────────────────────────────────────────────────────────────┘
"""

import logging
from typing import Dict, List, Optional

from .menu_service import MenuItem

logger = logging.getLogger("menu_catalog")

# ── DB-backed overrides ────────────────────────────────────────────────────
# Admin-editable menus live in the `menus` table (see database.py). Each row
# is a PER-ITEM override: menu_key + item_id + editable fields + is_active.
# item_id values are load-bearing for the FSM workflows and are never changed
# by the admin editor — only title/description/section/icon/order/visibility.

# Cache holds RAW DB rows per menu_key (not merged results), so every reader
# merges fresh. Cleared by invalidate_menu_cache() after every admin edit.
_MENU_CACHE: dict = {}


def invalidate_menu_cache() -> None:
    """Clear cached DB menus (called after admin edits)."""
    _MENU_CACHE.clear()


def _row_get(row, key: str, default=None):
    """Read a field from a sqlite3.Row or dict, tolerating missing columns."""
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if val is None else val


def _row_bool(row, key: str, default: bool = True) -> bool:
    """Read a boolean-ish field (0/1, '0'/'true', None → default)."""
    val = _row_get(row, key, None)
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("0", "false", "no", "off", ""):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return default


def _load_db_rows(menu_key: str) -> List[dict]:
    """ALL rows (active AND inactive) for menu_key from the DB (with cache)."""
    if menu_key in _MENU_CACHE:
        return _MENU_CACHE[menu_key]
    try:
        from database import get_menu_items  # lazy: avoid circular imports
        rows = [dict(r) for r in (get_menu_items(menu_key, active_only=False) or [])]
    except Exception as exc:
        logger.warning("Could not load DB menu rows for %r: %s", menu_key, exc)
        rows = []
    _MENU_CACHE[menu_key] = rows
    return rows


# ── Code defaults (pure — no DB access) ───────────────────────────────────

def _kb_main_defaults() -> List[MenuItem]:
    """Hard-coded default kb_main menu."""
    return [
        # 🛍️ Products
        MenuItem(
            id="menu_products",
            title="View Products",
            description="Browse all products",
            section="🛍️ Products",
            icon="🛍️",
        ),
        MenuItem(
            id="menu_catalogue",
            title="Brochure",
            description="Download the brochure PDF",
            section="🛍️ Products",
            icon="📄",
        ),
        MenuItem(
            id="menu_new_arrivals",
            title="New Releases",
            description="Fresh releases this month",
            section="🛍️ Products",
            icon="✨",
        ),
        # ℹ️ Info
        MenuItem(
            id="menu_about",
            title="Company Policies",
            description="About us & company policies",
            section="ℹ️ Info",
            icon="🏢",
        ),
        MenuItem(
            id="menu_discounts",
            title="Discounts & Offers",
            description="Current deals & bulk discounts",
            section="ℹ️ Info",
            icon="🎁",
        ),
        MenuItem(
            id="menu_gst",
            title="GST Info",
            description="GST number & tax invoice details",
            section="ℹ️ Info",
            icon="🧾",
        ),
        MenuItem(
            id="menu_credit_policy",
            title="Credit Policy",
            description="Credit period & payment terms",
            section="ℹ️ Info",
            icon="💳",
        ),
        # 🆘 Support
        MenuItem(
            id="menu_complaint",
            title="Raise Complaint",
            description="Report a problem with your order",
            section="🆘 Support",
            icon="📝",
        ),
        MenuItem(
            id="menu_view_cart",
            title="View Cart",
            description="See items in your cart",
            section="🆘 Support",
            icon="🛒",
        ),
        MenuItem(
            id="menu_human",
            title="Talk to Human",
            description="Chat with our support team",
            section="🆘 Support",
            icon="🙋",
        ),
    ]


def get_menu_defaults(menu_key: str) -> List[MenuItem]:
    """Code defaults for a menu key (empty list for unknown keys)."""
    if menu_key == "kb_main":
        return _kb_main_defaults()
    return []


def get_menu_item_defaults(menu_key: str) -> Dict[str, dict]:
    """item_id -> default fields. Used by database.upsert_menu_item() to seed
    new override rows with sensible values instead of NULLs."""
    return {
        d.id: {
            "title": d.title,
            "description": d.description,
            "section": d.section,
            "icon": d.icon,
            "sort_order": pos,
            "is_active": 1,
        }
        for pos, d in enumerate(get_menu_defaults(menu_key))
    }


# ── Merge engine: defaults + per-item DB overrides ────────────────────────

def _merge_entries(menu_key: str) -> List[dict]:
    """
    Merge code defaults with DB overrides PER ITEM.

    - A DB row for a default item overrides only the fields it stores;
      NULL/missing fields fall back to the code default (self-healing for
      rows written by the old buggy upsert that stored NULLs).
    - DB rows with unknown item_ids are admin-created items → appended.
    - Result is sorted by sort_order (defaults keep their list position).
    - is_active filters happen in the callers (editor wants everything).
    """
    defaults = get_menu_defaults(menu_key)
    rows = _load_db_rows(menu_key)
    row_by_id = {str(_row_get(r, "item_id", "")): r for r in rows}

    entries: List[dict] = []
    seen: set = set()

    for pos, d in enumerate(defaults):
        seen.add(d.id)
        r = row_by_id.get(d.id)
        if r is not None:
            sort_order = _row_get(r, "sort_order", pos)
            try:
                sort_order = int(sort_order)
            except (TypeError, ValueError):
                sort_order = pos
            entries.append({
                "menu_key": menu_key,
                "item_id": d.id,
                "title": str(_row_get(r, "title", "") or d.title),
                "description": str(_row_get(r, "description", "") or ""),
                "section": str(_row_get(r, "section", "") or d.section),
                "icon": str(_row_get(r, "icon", "") or ""),
                "sort_order": sort_order,
                "is_active": 1 if _row_bool(r, "is_active", True) else 0,
                "is_default": True,
                "in_db": True,
                "_pos": pos,
            })
        else:
            entries.append({
                "menu_key": menu_key,
                "item_id": d.id,
                "title": d.title,
                "description": d.description,
                "section": d.section,
                "icon": d.icon,
                "sort_order": pos,
                "is_active": 1,
                "is_default": True,
                "in_db": False,
                "_pos": pos,
            })

    # DB-only items (admin-created, or defaults renamed to new ids)
    for r in rows:
        rid = str(_row_get(r, "item_id", "")).strip()
        if not rid or rid in seen:
            continue
        sort_order = _row_get(r, "sort_order", None)
        try:
            sort_order = int(sort_order)
        except (TypeError, ValueError):
            sort_order = 1000 + len(entries)
        entries.append({
            "menu_key": menu_key,
            "item_id": rid,
            "title": str(_row_get(r, "title", "") or rid),
            "description": str(_row_get(r, "description", "") or ""),
            "section": str(_row_get(r, "section", "") or "General"),
            "icon": str(_row_get(r, "icon", "") or ""),
            "sort_order": sort_order,
            "is_active": 1 if _row_bool(r, "is_active", True) else 0,
            "is_default": False,
            "in_db": True,
            "_pos": 1000 + len(entries),
        })

    entries.sort(key=lambda e: (e["sort_order"], e["_pos"]))
    return entries


def _strip_internal(entry: dict) -> dict:
    """Drop underscore-prefixed internal keys for API output."""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


# ── Public API ─────────────────────────────────────────────────────────────

def get_profile_for(wa_id: str = "", tenant_id: Optional[str] = None):
    """The tenant profile that should drive this user's menu, or None.

    Returns None whenever tenancy is unavailable - an unmigrated database, a
    missing shared package, a load failure. Callers then fall back to the
    hard-coded menu, so the pre-tenant stack keeps working untouched.
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[2])
        if root not in _sys.path:
            _sys.path.insert(0, root)

        from shared.tenancy import loader
        from shared.tenancy.resolver import resolve_tenant_for_user

        return loader.get_tenant_profile(tenant_id or resolve_tenant_for_user(wa_id))
    except Exception as exc:  # pragma: no cover - defensive by design
        logger.debug("profile menu unavailable, using code defaults: %s", exc)
        return None


def profile_button_status(button_id: str, wa_id: str = "", tenant_id: Optional[str] = None):
    """Return (exists, enabled) for a profile menu button and its feature gate."""
    profile = get_profile_for(wa_id, tenant_id)
    if profile is None:
        return False, False
    button = next((b for b in profile.menu.buttons if b.id == button_id), None)
    if button is None:
        return False, False
    enabled = button.enabled and (
        not button.requires_feature or profile.features.is_on(button.requires_feature)
    )
    if button.intent:
        intent = profile.intent(button.intent)
        enabled = enabled and bool(
            intent and intent.enabled
            and (not intent.requires_feature or profile.features.is_on(intent.requires_feature))
        )
    return True, enabled


def get_profile_menu(
    profile, *, in_business_hours: bool = True
) -> List[MenuItem]:
    """Menu items for a tenant, from the profile's own button list.

    Disabled buttons and buttons whose feature flag is off are omitted. These
    are presentation rules only: each service still enforces its own entitlement.
    """
    buttons = profile.menu.visible_buttons(
        profile.features, in_business_hours=in_business_hours
    )
    return [
        MenuItem(
            id=b.id,
            title=b.title,
            description=b.description,
            section=b.section,
            icon=b.icon,
        )
        for b in buttons
    ]


def get_kb_main_menu(
    wa_id: str = "", user_type: str = "b2c", tenant_id: Optional[str] = None
) -> List[MenuItem]:
    """
    Single main menu used by every persona — B2C customers, B2B
    distributors, and the KB bot/greeting path. All users see the same menu.

    Renders from the tenant profile when one is available (Phase 4), otherwise
    from the hard-coded defaults with admin DB overrides applied per item
    (titles, descriptions, sections, icons, order), skipping items the admin
    set inactive. Admin-created items are appended in their sort order.
    """
    profile = get_profile_for(wa_id, tenant_id)
    if profile is not None:
        # The resolved profile already includes vertical defaults. Never revive
        # legacy defaults when this tenant intentionally has no visible rows.
        return get_profile_menu(profile)

    entries = [e for e in _merge_entries("kb_main") if e["is_active"]]

    if not entries:
        # Safety net: the admin deactivated every item. Rendering an empty
        # WhatsApp list menu would break the bot, so fall back to defaults.
        logger.warning("kb_main menu has zero active items — falling back to code defaults")
        return _kb_main_defaults()

    return [
        MenuItem(
            id=e["item_id"],
            title=e["title"],
            description=e["description"],
            section=e["section"],
            icon=e["icon"],
        )
        for e in entries
    ]


def get_menu_editor_items(menu_key: str) -> List[dict]:
    """
    Full merged item list for the admin editor: every default item (even
    ones never edited) plus admin-created items, with DB override values
    applied and is_active reflecting the DB (defaults = active).

    THE FIX for "toggling one item wipes the whole menu from the editor":
    the editor now always receives the complete structure.
    """
    return [_strip_internal(e) for e in _merge_entries(menu_key)]


def get_effective_item(menu_key: str, item_id: str) -> Optional[dict]:
    """One merged item (DB overrides over defaults), or None if unknown.

    Used by the admin editor so renaming/editing an item that has never
    been saved to the DB still works (it used to 404).
    """
    item_id = str(item_id or "").strip()
    for e in _merge_entries(menu_key):
        if e["item_id"] == item_id:
            return _strip_internal(e)
    return None


def get_main_menu_buttons() -> List[MenuItem]:
    """Small fallback buttons attached to text replies."""
    return [
        MenuItem(id="main_menu", title="Main Menu", icon="🏠"),
        MenuItem(id="menu_ai", title="Ask AI", icon="🤖"),
    ]
