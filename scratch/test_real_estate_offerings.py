import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backend')
sys.path.insert(0, '.')
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.offerings_flow import (
    get_vertical_offerings_button,
    handle_offerings_action,
    send_offerings_list,
    product_card,
)
from backend import database as db

async def test_offerings():
    print("=== TESTING REAL ESTATE OFFERINGS FLOW ===")

    # 1. Test DLF (tenant_id = 11)
    print("\n--- 1. DLF Limited (Tenant 11) ---")
    dlf_btn = get_vertical_offerings_button(tenant_id="dlf")
    print("DLF Offerings Button:", dlf_btn)
    assert dlf_btn is not None
    assert dlf_btn["title"] == "🏢 View Properties"
    assert dlf_btn["id"] == "menu_properties"

    dlf_count = db.count_products(tenant_id="dlf", active_only=True)
    print(f"DLF Active Products Count: {dlf_count}")
    assert dlf_count == 48

    mock_sender = MagicMock()
    mock_sender.send_list_menu = AsyncMock(return_value=True)

    with patch("backend.services.offerings_flow._sender", return_value=mock_sender):
        res = await handle_offerings_action("919999999999", "view properties", tenant_id="dlf", pressed_id="menu_properties")
        assert res is not None
        assert res.get("handled") is True
        assert mock_sender.send_list_menu.called
        call_args = mock_sender.send_list_menu.call_args[0]
        header, body, btn_text, sections = call_args[1], call_args[2], call_args[3], call_args[4]
        print("DLF List Header:", header)
        print("DLF Button Text:", btn_text)
        print("DLF Sections Count:", len(sections))
        print("DLF Category Rows:", [r["title"] for r in sections[0]["rows"][:5]])
        assert "Category" in btn_text or "Select" in btn_text

    # 2. Test Skyline Realty (tenant_id = 10)
    print("\n--- 2. Skyline Realty (Tenant 10) ---")
    sky_btn = get_vertical_offerings_button(tenant_id="skylinerealty")
    print("Skyline Offerings Button:", sky_btn)
    assert sky_btn is not None
    assert sky_btn["title"] == "🏢 View Properties"
    assert sky_btn["id"] == "menu_properties"

    sky_count = db.count_products(tenant_id="skylinerealty", active_only=True)
    print(f"Skyline Active Products Count: {sky_count}")
    assert sky_count == 8

    mock_sender = MagicMock()
    mock_sender.send_list_menu = AsyncMock(return_value=True)

    with patch("backend.services.offerings_flow._sender", return_value=mock_sender):
        res = await handle_offerings_action("919888888888", "view properties", tenant_id="skylinerealty", pressed_id="menu_properties")
        assert res is not None
        assert res.get("handled") is True
        assert mock_sender.send_list_menu.called
        call_args = mock_sender.send_list_menu.call_args[0]
        header, body, btn_text, sections = call_args[1], call_args[2], call_args[3], call_args[4]
        print("Skyline List Header:", header)
        print("Skyline Button Text:", btn_text)
        total_prods = sum(len(s["rows"]) for s in sections)
        print(f"Skyline Grouped Categories: {len(sections)}, Total Offerings in List: {total_prods}")
        for s in sections:
            print(f"  Category [{s['title']}]:")
            for r in s["rows"]:
                print(f"    * {r['title']} | {r['description']}")
        assert total_prods == 8

    # 3. Test Detail Card for Skyline 3 BHK & DLF The Dahlias
    print("\n--- 3. Detail Cards Formatting ---")
    sky_3bhk = db.get_product_by_slug("skyline-elegance-3bhk", tenant_id="skylinerealty")
    card_sky = product_card(sky_3bhk, vertical="real_estate")
    print("Skyline 3 BHK Card:\n", card_sky)
    assert "Ahmedabad" in card_sky
    assert "₹96 Lakhs" in card_sky
    assert "RERA" in card_sky

    dlf_dahlias = db.get_product_by_slug("dlf-the-dahlias", tenant_id="dlf")
    card_dlf = product_card(dlf_dahlias, vertical="real_estate")
    print("\nDLF The Dahlias Card:\n", card_dlf)
    assert "Gurugram" in card_dlf
    assert "RERA" in card_dlf

    print("\n=== ALL REAL ESTATE OFFERINGS TESTS PASSED! ===")

if __name__ == "__main__":
    asyncio.run(test_offerings())
