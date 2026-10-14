import sys
import os
import time

sys.path.insert(0, "backend")
sys.path.insert(0, ".")

from services.token_storage import save_token, get_token, delete_token
from services.google_meet_service import (
    create_meeting_sync,
    generate_gcal_add_url,
    get_valid_access_token_sync,
)
from services.callback_service import callback_service, google_meet_service

print("--- 1. Testing token_storage functions ---")
test_tenant = "test_meet_tenant"
# Save mock token
ok = save_token(
    tenant_id=test_tenant,
    access_token="mock_access_token_12345",
    refresh_token="mock_refresh_token_67890",
    expires_at=int(time.time()) + 3600,
    token_type="Bearer",
    scope="https://www.googleapis.com/auth/calendar",
)
assert ok is True, "save_token failed"
token = get_token(test_tenant)
assert token is not None, "get_token failed"
assert token["access_token"] == "mock_access_token_12345", "token mismatch"
print("[PASS] Token storage save and get verified")

print("\n--- 2. Testing get_valid_access_token_sync ---")
valid_tok = get_valid_access_token_sync(test_tenant)
assert valid_tok == "mock_access_token_12345", "Valid token mismatch"
print(f"[PASS] Retrieved valid access token: {valid_tok[:10]}...")

print("\n--- 3. Testing Google Calendar add url generator ---")
url = generate_gcal_add_url(
    title="Test Meeting",
    description="Test discussion",
    start_utc_compact="20261015T100000Z",
    end_utc_compact="20261015T103000Z",
    meet_link="https://meet.google.com/abc-defg-hij",
)
assert "calendar.google.com" in url, "Malformed calendar url"
print(f"[PASS] Calendar URL generated: {url[:60]}...")

print("\n--- 4. Testing callback_service.create_and_schedule_callback ---")
cb = callback_service.create_and_schedule_callback(
    tenant_id=test_tenant,
    wa_id="919512777899",
    customer_name="Test Customer",
    customer_email="test@example.com",
    customer_phone="919512777899",
    preferred_time="tomorrow at 11am",
    purpose="Product Inquiry & Google Meet",
)
assert cb is not None, "Callback creation failed"
assert cb.id.startswith("CB-"), "Callback ID format mismatch"
print(f"[PASS] Callback created: ID={cb.id}, status={cb.status}, meet_link={cb.meet_link}")

print("\n--- 5. Cleanup test token ---")
del_ok = delete_token(test_tenant)
assert del_ok is True, "delete_token failed"
assert get_token(test_tenant) is None, "Token still exists after deletion"
print("[PASS] Test token cleaned up")

print("\nALL GOOGLE MEET INTEGRATION TESTS PASSED!")
