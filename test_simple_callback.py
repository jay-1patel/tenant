#!/usr/bin/env python3
"""Simple Callback Pipeline Test Script for Chatbot2.

This script provides basic testing for the callback booking pipeline.
Run: python test_simple_callback.py
"""

import sys
import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend', 'services'))

from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_whatsapp_flow():
    """Test the WhatsApp callback flow."""
    print("\n[TEST] WhatsApp Callback Flow")
    print("-" * 40)
    
    from backend.services.callback_flow_service import callback_flow_service
    
    # Start a new flow
    flow_context = callback_flow_service.start_flow(
        wa_id="919999999999",
        tenant_id="test_tenant"
    )
    
    assert flow_context is not None
    print("[OK] Flow started")
    
    # Test the flow with messages - use valid email
    messages = [
        "John Doe",           # Name
        "skip",              # Skip email
        "+919876543210",     # Valid phone with country code
        "Product demo for our new software",       # Purpose (needs to be at least 10 chars)
        "1",                 # Type (sales)
        "2",                 # Priority (high)
        "tomorrow",          # Date
        "10:00 AM",          # Time
        "yes"                # Confirm
    ]
    
    for i, message in enumerate(messages):
        response, flow_context = callback_flow_service.process_message(
            flow_context.session_id, message
        )
        # Remove emojis for Windows console compatibility
        import re
        clean_response = re.sub(r'[\U0001f300-\U0001f6ff\U0001f900-\U0001f9ff]', '', response)
        print(f"[MSG {i+1}] User: {message}")
        print(f"       Bot: {clean_response[:60]}...")
    
    # Verify completion
    if flow_context.is_complete():
        print(f"[OK] Flow completed with callback ID: {flow_context.callback_id}")
        return True
    else:
        print(f"[FAIL] Flow not completed. State: {flow_context.current_state}")
        return False


async def test_callback_service():
    """Test the callback service directly."""
    print("\n[TEST] Callback Service")
    print("-" * 40)
    
    from backend.services.callback_service import callback_service, CallbackRequest
    
    # Create a callback request
    callback = callback_service.create_callback_request(
        tenant_id="test_tenant",
        wa_id="919999999999",
        customer_name="Test Customer",
        callback_type="sales",
        purpose="Testing callback",
        customer_email="test@example.com",
        preferred_date="2024-12-25",
        preferred_time="10:00"
    )
    
    assert callback.id.startswith("CB-")
    assert callback.status == "confirmed"
    print(f"[OK] Callback created: {callback.id}")
    print(f"[OK] Status: {callback.status}")
    print(f"[OK] Type: {callback.callback_type}")
    
    return True


async def test_notification_service():
    """Test the notification service."""
    print("\n[TEST] Notification Service")
    print("-" * 40)
    
    from backend.services.callback_service import (
        callback_service, notification_service, CallbackRequest
    )
    
    # Create a test callback
    callback = callback_service.create_callback_request(
        tenant_id="test_tenant",
        wa_id="919999999999",
        customer_name="Test Customer",
        callback_type="sales",
        purpose="Product demo",
        customer_email="test@example.com",
        preferred_date="2024-12-25",
        preferred_time="10:00"
    )
    
    # Manually set scheduled properties for testing
    callback.scheduled_start_time = "2024-12-25T10:00:00+05:30"
    callback.meet_link = "https://meet.google.com/test-link"
    callback.assigned_agent_name = "Test Agent"
    
    # Test message formatting
    confirmation = notification_service.format_callback_confirmation(callback)
    assert "Callback" in confirmation
    print("[OK] Confirmation message formatted")
    
    reminder = notification_service.format_reminder_message(callback, 15)
    assert "REMINDER" in reminder or "reminder" in reminder
    print("[OK] Reminder message formatted")
    
    return True


async def test_api_endpoints():
    """Test the API endpoints."""
    print("\n[TEST] API Endpoints")
    print("-" * 40)
    
    from fastapi.testclient import TestClient
    from backend.main import app
    
    client = TestClient(app)
    
    # Create callback
    test_data = {
        "customer_name": "API Test Customer",
        "wa_id": "919999999998",
        "callback_type": "sales",
        "purpose": "API testing",
        "priority": "medium"
    }
    
    try:
        response = client.post("/api/tenants/test_tenant/callbacks", json=test_data)
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        callback_id = result["callback_id"]
        print(f"[OK] Callback created via API: {callback_id}")
        
        # List callbacks
        response = client.get("/api/tenants/test_tenant/callbacks")
        assert response.status_code == 200
        callbacks = response.json()
        assert len(callbacks["callbacks"]) > 0
        print(f"[OK] Retrieved {len(callbacks['callbacks'])} callbacks")
        
        return True
    except Exception as e:
        print(f"[FAIL] API test failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("SIMPLE CALLBACK PIPELINE TEST")
    print("=" * 60)
    
    all_passed = True
    
    # Run all tests
    tests = [
        ("Callbacks Service", test_callback_service),
        ("WhatsApp Flow", test_whatsapp_flow),
        ("Notification Service", test_notification_service),
        ("API Endpoints", test_api_endpoints),
    ]
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            if result:
                print(f"\n[PASS] {test_name}")
            else:
                print(f"\n[FAIL] {test_name}")
                all_passed = False
        except Exception as e:
            print(f"\n[FAIL] {test_name}: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)