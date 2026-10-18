"""
B2C WhatsApp menu definitions with dynamic multi-tenant profile resolution
and Smart Switch between Quick Reply buttons (<= 3 options) and List drawers (> 3 options).
"""

import logging
from typing import Optional
from services.menu_catalog import get_kb_main_menu
from services.menu_service import MenuItem, build_list_menu, personalize_header

logger = logging.getLogger("b2c_menus")


def get_main_menu(wa_id: str = "", tenant_id: Optional[str] = None) -> dict:
    """Dynamic main menu for B2C customers.

    1. Resolves active tenant (testing override -> request context -> user mapping -> default).
    2. Loads the tenant's published profile menu buttons.
    3. Smart Switch:
       - <= 3 active options -> returns interactive Quick Reply buttons format (single tap).
       - > 3 active options -> returns full WhatsApp List Menu drawer.
    """
    # 1. Resolve tenant
    resolved_tid = str(tenant_id or "").strip()
    if not resolved_tid:
        try:
            from database import get_active_test_tenant
            resolved_tid = get_active_test_tenant() or ""
        except Exception:
            pass

    if not resolved_tid:
        try:
            from database import get_current_tenant
            resolved_tid = get_current_tenant() or ""
        except Exception:
            pass

    if not resolved_tid and wa_id:
        try:
            from shared.tenancy.resolver import resolve_tenant_for_user
            resolved_tid = resolve_tenant_for_user(wa_id) or ""
        except Exception:
            pass

    if not resolved_tid:
        try:
            from shared.tenancy.resolver import resolve_default_tenant
            resolved_tid = str(resolve_default_tenant())
        except Exception:
            resolved_tid = "default"

    # 2. Extract tenant-specific profile menu
    items = []
    header_title = "Options"
    body_text = "What would you like to explore today?"

    try:
        from shared.tenancy.loader import get_tenant_profile
        p = get_tenant_profile(resolved_tid)
        if p:
            if p.brand and p.brand.name:
                header_title = p.brand.name
            if p.menu and p.menu.body:
                body_text = p.menu.body
            if p.menu and p.menu.buttons:
                sorted_buttons = sorted(p.menu.buttons, key=lambda b: getattr(b, "sort_order", 0))
                for b in sorted_buttons:
                    if getattr(b, "enabled", True):
                        title = (getattr(b, "title", None) or "").strip()[:24]
                        desc = (getattr(b, "description", None) or "").strip()[:72]
                        section = (getattr(b, "section", None) or "General").strip()[:24]
                        icon = (getattr(b, "icon", None) or "").strip()
                        bid = getattr(b, "id", None) or f"menu_{title.lower().replace(' ', '_')}"
                        if title:
                            items.append(MenuItem(id=bid, title=title, description=desc, section=section, icon=icon))
    except Exception as e:
        logger.warning(f"Could not load profile menu for tenant '{resolved_tid}': {e}")

    # Fallback to code defaults if tenant has no buttons
    if not items:
        items = get_kb_main_menu(wa_id)
        header_title = personalize_header(wa_id, user_type="b2c")

    # 3. Smart Switch
    # When 1 to 3 items exist, send high-conversion single-tap Quick Reply buttons
    if 1 <= len(items) <= 3:
        quick_buttons = []
        for it in items[:3]:
            btn_title = (it.display_title() if it.icon else it.title)[:20]
            quick_buttons.append({"id": it.id, "title": btn_title})
        return {
            "type": "buttons",
            "text": f"*{header_title}*\n\n{body_text}" if header_title else body_text,
            "buttons": quick_buttons,
            "tenant_id": resolved_tid,
        }

    # When > 3 items exist, render structured WhatsApp List menu (up to 10 rows)
    menu = build_list_menu(
        header=header_title[:60],
        body=body_text[:1024],
        button_text="Show Options",
        items=items[:10],
    )
    menu["type"] = "list"
    menu["tenant_id"] = resolved_tid
    return menu