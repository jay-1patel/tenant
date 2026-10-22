"""
Local WhatsApp Tester simulator.

Provides a ``POST /api/test-simulator`` endpoint used by the Admin Panel's
"WhatsApp Tester" page (src/components/tester/whatsapp-tester.tsx).

This endpoint drives the SAME message pipeline as a real WhatsApp connection:
it calls ``services.orchestrator.process_incoming_message`` which routes the
message to the correct B2B / B2C persona workflow, runs the state machine, and
persists the FSM state to ``user_states``.

The only difference from production is that outgoing messages are captured by
``services.whatsapp_sender`` (capture mode) instead of being sent over the
send2.digital API — so the tester can render exactly what a real WhatsApp
connection would send.

Request:
    {"wa_id": "test-user-001", "message": "Hello", "user_type": "b2c"}

    user_type is optional and may be "b2b", "b2c", or "auto" (default auto:
    routes as a distributor if the wa_id exists in the distributors table).

Response:
    {
        "messages": [
            {"type": "text", "text": "..."},
            {"type": "buttons", "text": "...", "buttons": [{"id","title"}]},
            {"type": "list", "header": "...", "body": "...",
             "button_text": "...", "sections": [...]}
        ],
        "new_state": "B2C_MAIN_MENU",
        "human_handover": false,
        "user_type": "b2c",
        "status": "processed"
    }
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("test_simulator")

router = APIRouter(prefix="/api/test-simulator", tags=["test-simulator"])


class SimulatorRequest(BaseModel):
    """Request body for the WhatsApp tester simulator."""
    wa_id: str = "test-user-001"
    message: str = ""
    user_type: Optional[Literal["b2b", "b2c", "auto"]] = "auto"
    tenant_id: Optional[str] = None


class MenuPreviewRequest(BaseModel):
    """Request body for rendering a menu preview."""
    wa_id: str = "test-user-001"
    user_type: Optional[Literal["b2b", "b2c"]] = "b2c"
    tier: Optional[str] = None
    outstanding: Optional[float] = None
    tenant_id: Optional[str] = None


def _ensure_user_type(wa_id: str, user_type: str) -> str:
    """Resolve 'auto' to 'b2b'/'b2c' and ensure a matching DB record exists.

    If the tester explicitly picks a persona, ensure the corresponding row
    exists (a distributor row for b2b) so routing matches a real connection.
    """
    from database import get_db_context

    with get_db_context() as conn:
        is_dist = conn.execute(
            "SELECT 1 FROM distributors WHERE wa_id=?", (wa_id,)
        ).fetchone()

    resolved = user_type
    if resolved == "auto":
        resolved = "b2b" if is_dist else "b2c"

    if resolved == "b2b" and not is_dist:
        # Simulate a real distributor registration so B2B routing works.
        with get_db_context() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO distributors (wa_id, name, outstanding_payments) "
                "VALUES (?, ?, 0)",
                (wa_id, "Test Distributor"),
            )
    return resolved


@router.post("")
async def simulate_message(request: SimulatorRequest):
    """Process a message through the real orchestrator and return what it sends."""
    from services.orchestrator import process_incoming_message

    wa_id = (request.wa_id or "").strip() or "test-user-001"
    message = (request.message or "").strip()
    logger.info(f"TEST_SIMULATOR | wa_id={wa_id} | tenant={request.tenant_id} | type={request.user_type} | message={message!r}")

    if request.tenant_id:
        try:
            from database import set_request_tenant
            from backend.services import state_manager as sm
            set_request_tenant(request.tenant_id)
            sm.set_tenant(wa_id, request.tenant_id)
        except Exception as exc:
            logger.debug(f"Could not stamp simulator tenant: {exc}")

    resolved_type = _ensure_user_type(wa_id, request.user_type)

    result = await process_incoming_message(wa_id, message)

    result["user_type"] = resolved_type
    return result


@router.post("/reset")
async def reset_conversation(request: SimulatorRequest):
    """Reset a tester user's conversation to a brand-new state.

    Clears the persisted FSM state and the human-handover flag (and any
    registered distributor row created by the tester), so the next message
    behaves like the very first message of a fresh WhatsApp chat.
    """
    from database import get_db_context

    wa_id = (request.wa_id or "").strip() or "test-user-001"
    logger.info(f"TEST_SIMULATOR_RESET | wa_id={wa_id}")

    with get_db_context() as conn:
        conn.execute("DELETE FROM user_states WHERE wa_id=?", (wa_id,))
        conn.execute("DELETE FROM distributors WHERE wa_id=?", (wa_id,))

    return {
        "wa_id": wa_id,
        "reset": True,
        "new_state": None,
        "human_handover": False,
        "status": "reset",
    }


def _ensure_distributor_for_preview(wa_id: str, tier: Optional[str], outstanding: Optional[float]):
    """Create or update a distributor row so the B2B menu preview is realistic."""
    from database import get_db_context

    name = "Test Distributor"
    tier = tier or "Bronze"
    outstanding = outstanding if outstanding is not None else 0.0

    with get_db_context() as conn:
        conn.execute(
            """INSERT INTO distributors (wa_id, name, tier, outstanding_payments)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(wa_id) DO UPDATE SET
                 name = excluded.name,
                 tier = excluded.tier,
                 outstanding_payments = excluded.outstanding_payments""",
            (wa_id, name, tier, outstanding),
        )


def _count_list_rows(menu: dict) -> int:
    """Count total rows across all sections in a list menu."""
    return sum(len(s.get("rows", [])) for s in menu.get("sections", []))


def _collect_ids(menu: dict) -> list:
    """Collect all row/button IDs from a rendered menu."""
    ids = []
    if menu.get("type") == "list":
        for section in menu.get("sections", []):
            for row in section.get("rows", []):
                ids.append(row.get("id"))
    elif menu.get("type") == "buttons":
        for btn in menu.get("buttons", []):
            reply = btn.get("reply", {})
            ids.append(reply.get("id"))
    return ids


@router.post("/menu-preview")
async def preview_menu(request: MenuPreviewRequest):
    """Render the unified main menu for a mock B2C or B2B user.

    Useful for verifying menu layout, IDs, and WhatsApp limits without running
    the full conversation pipeline.
    """
    from services.menu_service import build_list_menu, personalize_header, _b2b_menu_body
    from services.menu_catalog import get_b2c_main_menu, get_b2b_main_menu

    wa_id = (request.wa_id or "").strip() or "test-user-001"
    user_type = request.user_type or "b2c"

    if user_type == "b2b":
        _ensure_distributor_for_preview(wa_id, request.tier, request.outstanding)
        items = get_b2b_main_menu(wa_id)
        header = personalize_header(wa_id, "b2b")
        body = _b2b_menu_body(wa_id)
        button_text = "Distributor Menu"
    else:
        items = get_b2c_main_menu(wa_id)
        header = personalize_header(wa_id, "b2c")
        body = "What would you like to explore today?"
        button_text = "Show Options"

    menu = build_list_menu(header, body, button_text, items)

    # Validation / assertions
    section_count = len(menu.get("sections", []))
    row_count = _count_list_rows(menu)
    ids = _collect_ids(menu)

    issues = []
    if section_count > 3:
        issues.append(f"Too many sections: {section_count}")
    if row_count > 10:
        issues.append(f"Too many rows: {row_count}")

    return {
        "wa_id": wa_id,
        "user_type": user_type,
        "menu": menu,
        "meta": {
            "sections": section_count,
            "rows": row_count,
            "ids": ids,
            "issues": issues,
        },
    }
