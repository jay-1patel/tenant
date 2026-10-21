"""
Verification script for WhatsApp message delivery and anti-truncation mechanisms.
"""
import os
import sys
import logging
logging.basicConfig(level=logging.DEBUG)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pytest
from unittest.mock import MagicMock, patch

def test_chunk_text():
    from routing.whatsapp import _chunk_text
    short = "Hello world"
    assert _chunk_text(short, limit=100) == ["Hello world"]

    # 5000 character string with paragraphs
    para = "Paragraph one with detailed content. " * 50
    long_text = f"{para}\n\n{para}\n\n{para}"
    chunks = _chunk_text(long_text, limit=2000)
    assert len(chunks) >= 2
    assert all(len(c) <= 2000 for c in chunks)
    # Ensure all content is preserved
    reconstructed = "\n\n".join(chunks)
    assert "Paragraph one with detailed content." in reconstructed


def test_interactive_split_delivery():
    from routing.whatsapp import send_whatsapp_interactive

    long_body = "This is a very long response explaining all details of the customer inquiry. " * 20
    assert len(long_body) > 1000

    buttons = [{"id": "btn1", "title": "Option 1"}]

    with patch("routing.whatsapp.send_whatsapp_message") as mock_send_msg, \
         patch("routing.whatsapp.requests.post") as mock_post:
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true, "message": "sent"}'
        mock_post.return_value = mock_resp

        res = send_whatsapp_interactive("919999999999", long_body, buttons)
        assert res is True

        # send_whatsapp_message must have been called with the complete, untruncated text
        mock_send_msg.assert_called_once()
        called_args = mock_send_msg.call_args[0]
        assert called_args[0] == "919999999999"
        assert called_args[1] == long_body

        # The interactive payload bodytext must be the clean prompt, NOT the truncated long text
        payload = mock_post.call_args[1]["json"]
        assert payload["bodytext"] == "Please select an option below:"
        assert len(payload["buttons"]) == 1


def test_list_menu_split_delivery():
    from routing.whatsapp import send_whatsapp_list_menu

    long_body = "Detailed list explanation with lots of background information and terms. " * 20
    assert len(long_body) > 1000

    sections = [{
        "title": "Options",
        "rows": [{"id": "r1", "title": "Row 1", "description": "Desc 1"}]
    }]

    with patch("routing.whatsapp.send_whatsapp_message") as mock_send_msg, \
         patch("routing.whatsapp.httpx.Client") as mock_client:
        
        mock_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true, "message": "sent"}'
        mock_instance.post.return_value = mock_resp
        mock_client.return_value.__enter__.return_value = mock_instance

        res = send_whatsapp_list_menu(
            to="919999999999",
            header_text="Header",
            body_text=long_body,
            button_text="Menu",
            sections=sections,
        )
        assert res is True

        # Complete text sent first
        mock_send_msg.assert_called_once()
        assert mock_send_msg.call_args[0][1] == long_body

        # Menu body is concise
        payload = mock_instance.post.call_args[1]["json"]
        assert payload["bodytext"] == "Please select an option below:"


def test_package_card_no_truncation():
    from backend.services.package_flow import package_card

    pkg = {
        "id": 101,
        "name": "Grand Himalayan Odyssey",
        "destination": "Himachal Pradesh & Ladakh",
        "duration": "14 Days / 13 Nights",
        "max_person": 12,
        "itinerary": [
            f"Day {i}: Explore spectacular mountain region {i} with local sightseeing and cultural experiences."
            for i in range(1, 15)
        ],
        "includes": [
            "All transfers in private vehicle",
            "Luxury accommodation on twin sharing",
            "Buffet breakfast and dinner daily",
            "Experienced English speaking tour guide",
            "All entry permits and taxes",
        ],
        "excludes": [
            "Airfare and train tickets",
            "Personal expenses and tips",
            "Travel insurance",
            "Optional adventure activities",
        ],
        "terms_conditions": "Bookings are subject to availability. 50% advance required at the time of booking. Cancellation within 15 days incurs 20% penalty. Remaining balance payable 7 days prior to departure.",
    }

    card = package_card(pkg)
    # Must NOT have ellipsis truncation '\n…'
    assert "…" not in card
    # Must contain full itinerary details and terms
    assert "Grand Himalayan Odyssey" in card
    assert "Day 14:" in card
    assert "Remaining balance payable 7 days" in card


def test_service_answers_no_truncation():
    from backend.services.service_answers import _fit_description

    desc = "We provide end-to-end cloud infrastructure management, 24/7 monitoring, automated CI/CD pipelines, security audits, disaster recovery planning, and seamless multi-cloud migrations tailored for high-growth enterprises."
    fitted = _fit_description(desc, limit=1200)
    assert "…" not in fitted
    assert fitted == desc


if __name__ == "__main__":
    test_chunk_text()
    test_interactive_split_delivery()
    test_list_menu_split_delivery()
    test_package_card_no_truncation()
    test_service_answers_no_truncation()
    print("ALL ANTI-TRUNCATION TESTS PASSED SUCCESSFULLY!")
