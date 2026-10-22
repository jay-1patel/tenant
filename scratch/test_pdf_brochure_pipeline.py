import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))

from backend.services.brochure_service import get_relevant_brochure, send_relevant_brochure
from kb.services.whatsapp import resolve_public_media_url, send_document, send_document_with_caption
import backend.services.whatsapp_sender as sender

print("="*60)
print("1. VERIFY BROCHURE RELEVANCE MATCHING (TENANT 'dlf')")
print("="*60)
cases = [
    ("Button Click", None, "menu_brochure"),
    ("Query: Dahlias", "Can you send the Dahlias brochure?", None),
    ("Query: The Arbour", "I want details and brochure for The Arbour", None),
    ("Query: Privana", "Send Privana south project deck", None),
    ("Query: Midtown Delhi", "One midtown brochure please", None),
    ("Query: Independent floors", "Independent floors luxury brochure", None),
    ("Query: NRI Legal handbook", "NRI investment and legal handbook", None),
]

for label, query, btn_id in cases:
    b = get_relevant_brochure(query=query, tenant_id="dlf", button_id=btn_id)
    if b:
        resolved = resolve_public_media_url(b.url)
        print(f"[{label}] -> Name: {b.name} | Module: {b.module}")
        print(f"   Raw URL: {b.url}")
        print(f"   Resolved Public URL: {resolved}")
    else:
        print(f"[{label}] -> FAILED: No brochure matched!")

print("\n" + "="*60)
print("2. VERIFY WHATSAPP SENDER COMPATIBILITY (MOCKING SEND2 DISPATCH)")
print("="*60)

captured_payloads = []

def fake_post(url, *args, **kwargs):
    payload = kwargs.get("json", {})
    captured_payloads.append({"url": url, "payload": payload})
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"success": true, "message": "message sent successfully"}'
    return resp

with patch("requests.post", side_effect=fake_post), patch("httpx.post", side_effect=fake_post):
    test_contact = "919999999999"
    
    # Test A: Direct send_document
    print("Testing direct send_document:")
    sent_a = send_document(test_contact, "/uploaded_files/kb/DLF_Master_Residential_Portfolio.pdf", "DLF_Master.pdf")
    print("  send_document result:", sent_a)
    
    # Test B: send_relevant_brochure
    print("Testing send_relevant_brochure for 'the dahlias':")
    sent_b = send_relevant_brochure(test_contact, query="Dahlias brochure", tenant_id="dlf")
    print("  send_relevant_brochure result:", sent_b)

print(f"\nCaptured {len(captured_payloads)} outbound HTTP payloads:")
for idx, p in enumerate(captured_payloads, 1):
    print(f"\nPayload #{idx} to {p['url']}:")
    payload = p["payload"]
    msg_type = payload.get("message_type")
    print(f"  message_type: {msg_type}")
    if msg_type == "document":
        print(f"  media_url: {payload.get('media_url')}")
    elif msg_type == "interactive":
        header = payload.get("interactive", {}).get("header", {})
        print(f"  interactive header: {header}")
        buttons = payload.get("interactive", {}).get("action", {}).get("buttons", [])
        print(f"  interactive buttons: {len(buttons)} button(s)")

print("\n" + "="*60)
print("ALL CHECKS COMPLETED!")
print("="*60)
