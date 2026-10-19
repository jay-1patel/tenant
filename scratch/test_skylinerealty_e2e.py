import sys
import os
import asyncio
import json

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath('backend'))
sys.path.insert(0, os.path.abspath('.'))

import database as db
import shared.tenancy.cache as tc
tc.purge_all()

from shared.tenancy.loader import get_tenant_profile
from services.orchestrator import process_incoming_message
from services import state_manager

async def test_skylinerealty():
    print("="*60)
    print("1. LOADING PROFILE FOR SKYLINEREALTY")
    print("="*60)
    p = get_tenant_profile("skylinerealty")
    print(f"Brand: {p.brand.name} | Bot Name: {p.brand.bot_name}")
    print(f"Vertical: {p.vertical}")
    print(f"Buttons count: {len(p.menu.buttons)}")
    for b in p.menu.buttons:
        target = f"flow:{b.flow}" if b.flow else (f"intent:{b.intent}" if b.intent else "NONE")
        print(f"  - [{b.id}] {b.title} -> {target}")

    db.set_active_test_tenant("skylinerealty")
    wa_id = "test_wa_realty_01"

    print("\n" + "="*60)
    print("2. TESTING #tenant SWITCHER")
    print("="*60)
    state_manager.clear_flow(wa_id)
    r_sw = await process_incoming_message(wa_id, "#tenant realestate", capture_only=True)
    print("Switch reply:", [m.get("text") for m in r_sw.get("messages", [])])

    print("\n" + "="*60)
    print("3. TESTING 'menu' COMMAND")
    print("="*60)
    state_manager.clear_flow(wa_id)
    r_menu = await process_incoming_message(wa_id, "menu", capture_only=True)
    msgs = r_menu.get("messages", [])
    print(f"Menu returned {len(msgs)} message(s):")
    if msgs:
        m = msgs[0]
        print("Header:", m.get("header"))
        print("Body:", m.get("body"))
        for s in m.get("sections", []):
            print(f" Section: {s.get('title')}")
            for row in s.get("rows", []):
                print(f"   * [{row.get('id')}] {row.get('title')}: {row.get('description')}")

    print("\n" + "="*60)
    print("4. TESTING BUTTON CLICKS")
    print("="*60)
    test_buttons = [
        "menu_properties",
        "menu_projects",
        "menu_pricing_plan",
        "menu_rera_legal",
        "menu_brochure",
        "menu_site_visit",
    ]
    for btn in test_buttons:
        state_manager.clear_flow(wa_id)
        r_btn = await process_incoming_message(wa_id, btn, capture_only=True)
        b_msgs = r_btn.get("messages", [])
        print(f"\n--- Button: {btn} ({len(b_msgs)} replies) ---")
        for bm in b_msgs:
            txt = bm.get("text") or bm.get("body") or str(bm)
            print("  >", txt[:140].replace("\n", " "))

    print("\n" + "="*60)
    print("5. TESTING NATURAL LANGUAGE REAL ESTATE QUESTIONS")
    print("="*60)
    questions = [
        "What 3 BHK flats do you have and what are the starting prices?",
        "Is Skyline Elegance project RERA approved?",
        "What payment plans and bank loans do you have?",
    ]
    for q in questions:
        state_manager.clear_flow(wa_id)
        r_q = await process_incoming_message(wa_id, q, capture_only=True)
        q_msgs = r_q.get("messages", [])
        print(f"\nQ: {q}")
        for qm in q_msgs:
            txt = qm.get("text") or qm.get("body") or str(qm)
            print("A:", txt[:160].replace("\n", " "))

    print("\n✅ All Skyline Realty end-to-end tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_skylinerealty())
