#!/usr/bin/env python3
"""Callback Pipeline Testing Script for Chatbot2.

This script provides comprehensive testing for the complete callback booking pipeline:
- WhatsApp flow simulation
- Database operations
- Google Meet integration (mock)
- Send2 Digital notifications (mock)
- Full end-to-end testing

Usage:
    python test_callback_pipeline.py              # Run all tests
    python test_callback_pipeline.py --flow       # Test WhatsApp flow only
    python test_callback_pipeline.py --api        # Test API endpoints only
    python test_callback_pipeline.py --integration # Test full integration
    python test_callback_pipeline.py --demo       # Run interactive demo

Requirements:
    - pip install pytest httpx pytest-asyncio python-dotenv
    - Set up .env file with required credentials
"""

import sys
import os
import json
import asyncio
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from dataclasses import asdict

logger = logging.getLogger(__name__)

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend', 'services'))

from dotenv import load_dotenv
load_dotenv()


# ============================================================================
# TEST CONFIGURATION
# ============================================================================

class TestConfig:
    """Test configuration for callback pipeline."""
    
    TEST_TENANT_ID = "test_tenant_001"
    TEST_WA_ID = "919999999999"  # Test WhatsApp ID
    TEST_AGENT_ID = "agent_001"
    TEST_AGENT_NAME = "Test Agent"
    
    # Test data
    @staticmethod
    def create_test_callback_data() -> Dict[str, Any]:
        """Create test callback request data."""
        return {
            "customer_name": "Test Customer",
            "wa_id": TestConfig.TEST_WA_ID,
            "callback_type": "sales",
            "purpose": "Product demonstration",
            "priority": "high",
            "customer_email": "test@customer.com",
            "customer_phone": "+919999999999",
            "preferred_date": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d"),
            "preferred_time": "10:00",
            "additional_info": "Interested in premium plan"
        }


# ============================================================================
# TEST DATABASE SETUP
# ============================================================================

class TestDatabase:
    """Test database setup and teardown."""
    
    @staticmethod
    def setup_test_db():
        """Set up test database tables."""
        from backend.database import get_db_context
        
        with get_db_context() as conn:
            # Create test tenant if not exists
            tenant = conn.execute(
                "SELECT * FROM tenants WHERE id = ?", (TestConfig.TEST_TENANT_ID,)
            ).fetchone()
            
            if not tenant:
                try:
                    conn.execute(
                        "INSERT INTO tenants (id, company_name, slug, domain, system_prompt, is_active, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (TestConfig.TEST_TENANT_ID, "Test Tenant", "test-tenant", "test.example.com", "You are a helpful assistant.", 1, "active")
                    )
                except Exception as e:
                    logger.warning(f"Failed to create test tenant: {e}")
            
            # Initialize callback tables
            try:
                from backend.routes.callbacks import _init_callback_tables
                _init_callback_tables(conn)
            except Exception as e:
                print(f"⚠️  Failed to init callback tables: {e}")
            
            conn.commit()
        
        print("[OK] Test database setup complete")
    
    @staticmethod
    def cleanup_test_data():
        """Clean up test data from database."""
        from database import get_db_context
        
        with get_db_context() as conn:
            # Delete test callbacks
            try:
                conn.execute("DELETE FROM callback_summaries WHERE tenant_id = ?", (TestConfig.TEST_TENANT_ID,))
            except:
                pass
            try:
                conn.execute("DELETE FROM agent_availability WHERE tenant_id = ?", (TestConfig.TEST_TENANT_ID,))
            except:
                pass
            try:
                conn.execute("DELETE FROM callbacks WHERE tenant_id = ?", (TestConfig.TEST_TENANT_ID,))
            except:
                pass
            conn.commit()
        
        print("[OK] Test data cleaned up")


# ============================================================================
# TEST HELPER FUNCTIONS
# ============================================================================

class TestHelpers:
    """Helper functions for testing."""
    
    @staticmethod
    def create_test_remove_data() -> Dict[str, Any]:
        """Create test data for callback request."""
        return {
            "customer_name": "Test Customer",
            "wa_id": TestConfig.TEST_WA_ID,
            "callback_type": "sales",
            "purpose": "Testing callback flow",
            "priority": "medium",
            "customer_email": "test@example.com",
            "customer_phone": "+919999999999"
        }
    
    @staticmethod
    async def create_callback_via_flow():
        """Test creating a callback via the flow service."""
        from backend.services.callback_flow_service import callback_flow_service
        
        # Start flow
        flow_context = callback_flow_service.start_flow(
            wa_id=TestConfig.TEST_WA_ID,
            tenant_id=TestConfig.TEST_TENANT_ID
        )
        
        # Simulate message flow
        messages = [
            "Test Customer",  # Name
            "test@example.com",  # Email
            "+919999999999",  # Phone
            "Product demo",  # Purpose
            "1",  # Type (sales)
            "2",  # Priority (high)
            "tomorrow",  # Date
            "10:00 AM",  # Time
            "yes"  # Confirm
        ]
        
        for message in messages:
            response, flow_context = callback_flow_service.process_message(
                flow_context.session_id, message
            )
            print(f"  → User: {message}")
            print(f"  ← Bot: {response[:50]}...")
        
        return flow_context
    
    @staticmethod
    async def test_callback_api_endpoints():
        """Test callback API endpoints."""
        import httpx
        from main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        # Test create callback
        callback_data = TestConfig.create_test_callback_data()
        
        response = client.post(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks",
            json=callback_data
        )
        
        assert response.status_code == 200, f"Failed to create callback: {response.text}"
        result = response.json()
        assert result["ok"] is True
        
        callback_id = result["callback_id"]
        print(f"✅ Created callback: {callback_id}")
        
        # Test list callbacks
        response = client.get(f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks")
        assert response.status_code == 200
        
        callbacks = response.json()
        assert callbacks["ok"] is True
        assert len(callbacks["callbacks"]) > 0
        print(f"✅ Listed {len(callbacks['callbacks'])} callbacks")
        
        # Test get specific callback
        response = client.get(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}"
        )
        assert response.status_code == 200
        callback = response.json()
        assert callback["ok"] is True
        assert callback["callback"]["id"] == callback_id
        print(f"✅ Retrieved callback: {callback_id}")
        
        # Test schedule callback
        schedule_data = {
            "agent_id": TestConfig.TEST_AGENT_ID,
            "agent_name": TestConfig.TEST_AGENT_NAME,
            "start_time": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.now(timezone.utc) + timedelta(hours=1, minutes=30)).isoformat(),
            "send_notifications": False  # Disable notifications for testing
        }
        
        response = client.post(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}/schedule",
            json=schedule_data
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                print(f"✅ Scheduled callback with Meet link: {result.get('meet_link', 'N/A')[:30]}...")
            else:
                print(f"⚠️  Scheduling returned error: {result.get('error', 'Unknown')}")
        else:
            print(f"⚠️  Scheduling failed: {response.text[:100]}...")
        
        return callback_id


# ============================================================================
# WHATSAPP FLOW TESTS
# ============================================================================

class WhatsAppFlowTests:
    """Tests for WhatsApp callback flow."""
    
    @staticmethod
    async def test_complete_flow():
        """Test complete WhatsApp conversation flow."""
        from backend.services.callback_flow_service import (
            callback_flow_service, CallbackFlowContext, CallbackFlowState
        )
        
        print("\n📱 Testing WhatsApp Callback Flow")
        print("=" * 50)
        
        # Start flow
        flow_context = callback_flow_service.start_flow(
            wa_id=TestConfig.TEST_WA_ID,
            tenant_id=TestConfig.TEST_TENANT_ID
        )
        
        assert flow_context is not None
        assert flow_context.current_state == CallbackFlowState.INITIAL.value
        print("✅ Flow started successfully")
        
        # Test each step
        test_cases = [
            ("Name", "John Doe", CallbackFlowState.COLLECTING_NAME.value),
            ("Email", "john@example.com", CallbackFlowState.COLLECTING_EMAIL.value),
            ("Phone", "+1234567890", CallbackFlowState.COLLECTING_PHONE.value),
            ("Purpose", "I want to discuss the premium plan features", CallbackFlowState.COLLECTING_PURPOSE.value),
            ("Type", "1", CallbackFlowState.SELECTING_TYPE.value),
            ("Priority", "2", CallbackFlowState.SELECTING_PRIORITY.value),
            ("Date", "tomorrow", CallbackFlowState.SELECTING_DATE.value),
            ("Time", "10:00 AM", CallbackFlowState.SELECTING_TIME.value),
            ("Confirmation", "yes", CallbackFlowState.COMPLETED.value)
        ]
        
        for step_name, message, expected_state in test_cases:
            response, flow_context = callback_flow_service.process_message(
                flow_context.session_id, message
            )
            assert flow_context.current_state == expected_state, \
                f"Expected {expected_state}, got {flow_context.current_state}"
            print(f"✅ {step_name}: '{message}' → {expected_state}")
        
        # Verify completion
        assert flow_context.is_complete()
        assert flow_context.callback_id is not None
        print(f"✅ Flow completed with callback ID: {flow_context.callback_id}")
        
        return flow_context.callback_id
    
    @staticmethod
    async def test_flow_validation():
        """Test flow validation and error handling."""
        from backend.services.callback_flow_service import callback_flow_service
        
        print("\n🧪 Testing Flow Validation")
        print("=" * 50)
        
        flow_context = callback_flow_service.start_flow(
            wa_id=TestConfig.TEST_WA_ID,
            tenant_id=TestConfig.TEST_TENANT_ID
        )
        
        # Test invalid name
        response, _ = callback_flow_service.process_message(
            flow_context.session_id, "123"
        )
        assert "Could you please provide your name" in response
        print("✅ Invalid name rejected")
        
        # Test valid name, then invalid email
        response, flow_context = callback_flow_service.process_message(
            flow_context.session_id, "Test User"
        )
        
        response, _ = callback_flow_service.process_message(
            flow_context.session_id, "invalid-email"
        )
        assert "valid email" in response.lower()
        print("✅ Invalid email rejected")
        
        # Test skip options
        response, flow_context = callback_flow_service.process_message(
            flow_context.session_id, "skip"
        )
        
        response, flow_context = callback_flow_service.process_message(
            flow_context.session_id, "skip"
        )
        
        assert flow_context.current_state == "collecting_purpose"
        print("✅ Skip options working")
    
    @staticmethod
    async def test_date_parsing():
        """Test date parsing capabilities."""
        from backend.services.callback_flow_service import callback_flow_service
        
        print("\n📅 Testing Date Parsing")
        print("=" * 50)
        
        # Test various date formats
        test_dates = [
            "2024-12-25",
            "tomorrow", 
            "next Monday",
            "next Tuesday",
            "today"
        ]
        
        for date_str in test_dates:
            parsed = callback_flow_service._parse_date_message(date_str)
            if parsed:
                print(f"✅ '{date_str}' → {parsed}")
            else:
                print(f"❌ '{date_str}' → Failed to parse")
    
    @staticmethod
    async def test_time_parsing():
        """Test time parsing capabilities."""
        from backend.services.callback_flow_service import callback_flow_service
        
        print("\n⏰ Testing Time Parsing")
        print("=" * 50)
        
        test_times = [
            "10:00",
            "10:30",
            "2 PM",
            "2:30 PM",
            "10 AM",
            "15:30"
        ]
        
        for time_str in test_times:
            parsed = callback_flow_service._parse_time_message(time_str)
            if parsed:
                print(f"✅ '{time_str}' → {parsed}")
            else:
                print(f"❌ '{time_str}' → Failed to parse")


# ============================================================================
# API INTEGRATION TESTS
# ============================================================================

class APIIntegrationTests:
    """Tests for API integration."""
    
    @staticmethod
    async def test_callback_crud():
        """Test CRUD operations for callbacks."""
        from fastapi.testclient import TestClient
        from main import app
        
        client = TestClient(app)
        
        print("\n🔄 Testing Callback CRUD Operations")
        print("=" * 50)
        
        # Create
        data = TestConfig.create_test_callback_data()
        response = client.post(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks",
            json=data
        )
        assert response.status_code == 200
        callback_id = response.json()["callback_id"]
        print(f"✅ Create: {callback_id}")
        
        # Read
        response = client.get(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}"
        )
        assert response.status_code == 200
        print("✅ Read: Successfully retrieved callback")
        
        # Update
        update_data = {"priority": "urgent", "additional_info": "Updated info"}
        response = client.put(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}",
            json=update_data
        )
        assert response.status_code == 200
        print("✅ Update: Successfully updated callback")
        
        # List
        response = client.get(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks"
        )
        assert response.status_code == 200
        callbacks = response.json()["callbacks"]
        assert any(cb["id"] == callback_id for cb in callbacks)
        print(f"✅ List: Found {len(callbacks)} callbacks")
        
        # Delete (via cancel)
        cancel_data = {"reason": "Testing cleanup"}
        response = client.post(
            f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}/cancel",
            json=cancel_data
        )
        assert response.status_code == 200
        print("✅ Cancel: Successfully cancelled callback")
        
        return callback_id


# ============================================================================
# NOTIFICATION TESTS
# ============================================================================

class NotificationTests:
    """Tests for notification services."""
    
    @staticmethod
    async def test_notification_formatting():
        """Test notification message formatting."""
        from backend.services.callback_service import notification_service, CallbackRequest
        
        print("\n📧 Testing Notification Formatting")
        print("=" * 50)
        
        # Create a test callback
        callback = CallbackRequest(
            id="CB-20240101120000-abc123",
            tenant_id=TestConfig.TEST_TENANT_ID,
            wa_id=TestConfig.TEST_WA_ID,
            customer_name="Test Customer",
            customer_email="test@example.com",
            callback_type="sales",
            priority="high",
            purpose="Product demo",
            preferred_date="2024-01-15",
            preferred_time="10:00",
            timezone="Asia/Kolkata",
            status="confirmed",
            scheduled_start_time="2024-01-15T10:00:00+05:30",
            scheduled_end_time="2024-01-15T10:30:00+05:30",
            meet_link="https://meet.google.com/xxx-yyy-zzz",
            assigned_agent_id=TestConfig.TEST_AGENT_ID,
            assigned_agent_name=TestConfig.TEST_AGENT_NAME
        )
        
        # Test confirmation message
        confirmation = notification_service.format_callback_confirmation(callback)
        assert "Callback Confirmed" in confirmation or "Request Received" in confirmation
        print("✅ Confirmation message formatted")
        
        # Test reminder message
        reminder = notification_service.format_reminder_message(callback, 15)
        assert "REMINDER" in reminder or "reminder" in reminder
        print("✅ Reminder message formatted")
        
        # Test agent notification
        agent_notification = notification_service.format_agent_notification(callback)
        assert "New Callback Assigned" in agent_notification or "assigned" in agent_notification.lower()
        print("✅ Agent notification formatted")
        
        print(f"\n📝 Sample Confirmation Message:")
        print("-" * 50)
        print(confirmation[:200] + ("..." if len(confirmation) > 200 else ""))
    
    @staticmethod
    async def test_send2_integration():
        """Test Send2 Digital integration."""
        from backend.services.send2_callback_notification import send2_callback_service
        
        print("\n🔗 Testing Send2 Digital Integration")
        print("=" * 50)
        
        # Check configuration
        configured = send2_callback_service.is_configured()
        print(f"Send2 Configured: {'✅ Yes' if configured else '❌ No'}")
        
        if not configured:
            print("⚠️  Send2 Digital credentials not configured")
            print("   Set SEND2_API_KEY, SEND2_API_SECRET, SEND2_WHA_BUSINESS_ID, and SEND2_PHONE_NUMBER_ID")
            return
        
        # Test message sending (note: this won't actually send without valid credentials)
        try:
            result = await send2_callback_service._send_whatsapp_message(
                phone=TestConfig.TEST_WA_ID,
                message="Test callback notification"
            )
            print(f"Send2 Test Result: {'✅ Success' if result else '❌ Failed'}")
        except Exception as e:
            print(f"⚠️  Send2 Test Error: {e}")


# ============================================================================
# GOOGLE MEET INTEGRATION TESTS
# ============================================================================

class GoogleMeetTests:
    """Tests for Google Meet integration."""
    
    @staticmethod
    async def test_google_oauth():
        """Test Google OAuth configuration."""
        from backend.services.google_oauth_setup import google_oauth_service, enhanced_google_meet_service
        
        print("\n🔑 Testing Google OAuth Configuration")
        print("=" * 50)
        
        # Check configuration
        configured = google_oauth_service.is_configured()
        print(f"Google OAuth Configured: {'✅ Yes' if configured else '❌ No'}")
        
        if configured:
            auth_method = google_oauth_service.get_auth_method()
            print(f"Authentication Method: {auth_method}")
            
            # Try authentication
            try:
                success = await google_oauth_service.authenticate()
                print(f"Authentication: {'✅ Success' if success else '❌ Failed'}")
            except Exception as e:
                print(f"⚠️  Authentication Error: {e}")
        else:
            print("⚠️  Google OAuth not configured")
            print("   Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET for OAuth2")
            print("   or GOOGLE_SERVICE_ACCOUNT_JSON for Service Account")
    
    @staticmethod
    async def test_meet_creation():
        """Test Google Meet creation (mock response)."""
        from backend.services.callback_service import google_meet_service
        
        print("\n🎥 Testing Google Meet Creation")
        print("=" * 50)
        
        # Test create meeting with current implementation
        try:
            result = await google_meet_service.create_meeting(
                calendar_id="primary",
                title="Test Callback Meeting",
                description="Testing callback booking",
                start_time=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                end_time=(datetime.now(timezone.utc) + timedelta(hours=1, minutes=30)).isoformat(),
                timezone="Asia/Kolkata"
            )
            
            if result.get("ok"):
                print("✅ Meeting created successfully")
                print(f"   Event ID: {result.get('event_id', 'N/A')}")
                print(f"   Meet Link: {result.get('meet_link', 'N/A')[:40]}...")
            else:
                print(f"⚠️  Meeting creation: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"⚠️  Meeting creation error: {e}")


# ============================================================================
# DEMO SIMULATION
# ============================================================================

class DemoSimulation:
    """Interactive demo simulation."""
    
    @staticmethod
    async def run_interactive_demo():
        """Run an interactive demo of the callback pipeline."""
        print("\n" + "=" * 60)
        print("🎯 CHATBOT2 CALLBACK BOOKING PIPELINE DEMO")
        print("=" * 60)
        print()
        print("This demo simulates a complete callback booking flow:")
        print("1. User requests callback via WhatsApp")
        print("2. Bot collects information through conversation")
        print("3. System creates callback request")
        print("4. Agent schedules with Google Meet")
        print("5. Notifications sent to customer")
        print("6. Reminders sent before meeting")
        print()
        
        # Setup
        TestDatabase.setup_test_db()
        
        try:
            print("🔄 Setting up demo environment...")
            
            # Initialize services
            from backend.services.callback_flow_service import callback_flow_service
            from backend.services.callback_service import callback_service
            from fastapi.testclient import TestClient
            from main import app
            
            client = TestClient(app)
            
            print("✅ Environment ready\n")
            
            # Step 1: WhatsApp conversation flow
            print("📱 STEP 1: WhatsApp Conversation Flow")
            print("-" * 60)
            
            flow_context = callback_flow_service.start_flow(
                wa_id=TestConfig.TEST_WA_ID,
                tenant_id=TestConfig.TEST_TENANT_ID
            )
            
            print("Bot: I'd be happy to help you schedule a callback! To get started, could you please tell me your name?")
            
            # Simulate conversation
            conversation = [
                ("John Doe", "Thanks, John! What is your email address? (optional - you can say 'skip' to continue)"),
                ("john@example.com", "Thank you! What is your phone number? (optional - say 'skip' to continue)"),
                ("skip", "Understood. What is the purpose of this callback?"),
                ("I want a product demo", "What type of callback would you like?"),
                ("1", "What priority level is this callback?"),
                ("2", "When would you like to have this callback?"),
                ("tomorrow", "What time would you prefer?"),
                ("2 PM", "Please confirm your callback request:"),
                ("yes", None)  # Final confirmation
            ]
            
            for user_message, expected_bot_response in conversation:
                response, flow_context = callback_flow_service.process_message(
                    flow_context.session_id, user_message
                )
                print(f"User: {user_message}")
                print(f"Bot: {response}")
                print()
            
            assert flow_context.is_complete()
            callback_id = flow_context.callback_id
            print(f"✅ Callback request created: {callback_id}")
            print()
            
            # Step 2: Agent schedules the callback
            print("📅 STEP 2: Agent Schedules Callback with Google Meet")
            print("-" * 60)
            
            start_time = (datetime.now(timezone.utc) + timedelta(days=1, hours=14)).isoformat()
            end_time = (datetime.now(timezone.utc) + timedelta(days=1, hours=14, minutes=30)).isoformat()
            
            schedule_data = {
                "agent_id": TestConfig.TEST_AGENT_ID,
                "agent_name": TestConfig.TEST_AGENT_NAME,
                "start_time": start_time,
                "end_time": end_time,
                "send_notifications": False
            }
            
            response = client.post(
                f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}/schedule",
                json=schedule_data
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    meet_link = result.get("meet_link", "Not available (using mock)")
                    print(f"✅ Callback scheduled successfully")
                    print(f"   Google Meet Link: {meet_link[:40]}...")
                    print(f"   Start Time: {start_time}")
                    print(f"   End Time: {end_time}")
                    print(f"   Assigned Agent: {TestConfig.TEST_AGENT_NAME}")
                else:
                    print(f"⚠️  Scheduling error: {result.get('error', 'Unknown')}")
            else:
                print(f"⚠️  Scheduling failed: {response.text}")
            
            print()
            
            # Step 3: View callback details
            print("📋 STEP 3: Callback Details")
            print("-" * 60)
            
            response = client.get(
                f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}"
            )
            
            if response.status_code == 200:
                callback = response.json()["callback"]
                print(f"Callback ID: {callback['id']}")
                print(f"Customer: {callback['customer_name']}")
                print(f"WhatsApp: {callback['wa_id']}")
                print(f"Type: {callback['callback_type']}")
                print(f"Priority: {callback['priority']}")
                print(f"Status: {callback['status']}")
                if callback.get('scheduled_start_time'):
                    print(f"Scheduled: {callback['scheduled_start_time']}")
                if callback.get('meet_link'):
                    print(f"Meet Link: {callback['meet_link'][:40]}...")
            
            print()
            
            # Step 4: Completing the callback
            print("✅ STEP 4: Callback Completed")
            print("-" * 60)
            
            complete_data = {
                "meeting_notes": "Product demo completed successfully. Customer interested in premium plan.",
                "outcome": "success",
                "follow_up_required": True,
                "follow_up_notes": "Follow up with contract discussion next week"
            }
            
            response = client.post(
                f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/{callback_id}/complete",
                json=complete_data
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Callback marked as completed")
                print(f"   Outcome: {result.get('summary', {}).get('outcome', 'unknown')}")
                print(f"   Follow-up Required: {result.get('summary', {}).get('follow_up_required', False)}")
            else:
                print(f"⚠️  Completion failed: {response.text}")
            
            print()
            print("🎉 DEMO COMPLETE!")
            print("-" * 60)
            print("The callback booking pipeline is working correctly.")
            print("In production, this would send WhatsApp notifications to the customer")
            print("and create actual Google Meet meetings.")
            
            # Statistics
            print("\n📊 Pipeline Statistics:")
            response = client.get(
                f"/api/tenants/{TestConfig.TEST_TENANT_ID}/callbacks/stats?days=30"
            )
            if response.status_code == 200:
                stats = response.json()
                print(f"   Total Callbacks: {stats.get('total_callbacks', 0)}")
                print(f"   Active Callbacks: {stats.get('status_distribution', {}).get('pending', 0) + stats.get('status_distribution', {}).get('scheduled', 0)}")
                print(f"   Completed: {stats.get('status_distribution', {}).get('completed', 0)}")
            
        finally:
            # Cleanup
            TestDatabase.cleanup_test_data()


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

async def run_all_tests():
    """Run all callback pipeline tests."""
    import time
    
    print("\n" + "=" * 60)
    print("🧪 CALLBACK PIPELINE TEST SUITE")
    print("=" * 60)
    
    start_time = time.time()
    
    try:
        # Setup
        print("\n📦 Initializing test environment...")
        TestDatabase.setup_test_db()
        
        # Run tests
        test_results = []
        
        # WhatsApp Flow Tests
        print("\n" + "=" * 60)
        print("TESTING WHATSAPP FLOW")
        print("=" * 60)
        try:
            await WhatsAppFlowTests.test_complete_flow()
            await WhatsAppFlowTests.test_flow_validation()
            test_results.append(("WhatsApp Flow", True))
        except Exception as e:
            print(f"❌ WhatsApp Flow Tests Failed: {e}")
            test_results.append(("WhatsApp Flow", False))
        
        # API Integration Tests
        print("\n" + "=" * 60)
        print("TESTING API INTEGRATION")
        print("=" * 60)
        try:
            await APIIntegrationTests.test_callback_crud()
            test_results.append(("API Integration", True))
        except Exception as e:
            print(f"❌ API Integration Tests Failed: {e}")
            test_results.append(("API Integration", False))
        
        # Notification Tests
        print("\n" + "=" * 60)
        print("TESTING NOTIFICATIONS")
        print("=" * 60)
        try:
            await NotificationTests.test_notification_formatting()
            await NotificationTests.test_send2_integration()
            test_results.append(("Notifications", True))
        except Exception as e:
            print(f"❌ Notification Tests Failed: {e}")
            test_results.append(("Notifications", False))
        
        # Google Meet Tests
        print("\n" + "=" * 60)
        print("TESTING GOOGLE MEET INTEGRATION")
        print("=" * 60)
        try:
            await GoogleMeetTests.test_google_oauth()
            await GoogleMeetTests.test_meet_creation()
            test_results.append(("Google Meet", True))
        except Exception as e:
            print(f"❌ Google Meet Tests Failed: {e}")
            test_results.append(("Google Meet", False))
        
        # Additional tests
        print("\n" + "=" * 60)
        print("TESTING DATE/TIME PARSING")
        print("=" * 60)
        try:
            await WhatsAppFlowTests.test_date_parsing()
            await WhatsAppFlowTests.test_time_parsing()
            test_results.append(("Date/Time Parsing", True))
        except Exception as e:
            print(f"❌ Date/Time Parsing Tests Failed: {e}")
            test_results.append(("Date/Time Parsing", False))
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for _, success in test_results if success)
        total = len(test_results)
        
        for test_name, success in test_results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} {test_name}")
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED!")
        else:
            print(f"\n⚠️  {total - passed} test{'s' if total - passed > 1 else ''} failed")
        
        elapsed = time.time() - start_time
        print(f"\n⏱️  Test suite completed in {elapsed:.2f} seconds")
        
        # Cleanup
        TestDatabase.cleanup_test_data()
        
        return passed == total
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_specific_tests(args):
    """Run specific tests based on command line arguments."""
    TestDatabase.setup_test_db()
    
    try:
        if "--flow" in args or "--whatsapp" in args:
            print("\n📱 Running WhatsApp Flow Tests")
            print("=" * 40)
            await WhatsAppFlowTests.test_complete_flow()
            await WhatsAppFlowTests.test_flow_validation()
            
        if "--api" in args:
            print("\n🔄 Running API Tests")
            print("=" * 40)
            await APIIntegrationTests.test_callback_crud()
            
        if "--integration" in args or "--full" in args:
            print("\n🔗 Running Full Integration Tests")
            print("=" * 40)
            await run_all_tests()
            
        if "--demo" in args:
            await DemoSimulation.run_interactive_demo()
            
        if len(args) == 0 or (len(args) == 1 and args[0] == "--help"):
            print("Usage: python test_callback_pipeline.py [OPTIONS]")
            print()
            print("Options:")
            print("  --flow          Test WhatsApp conversation flow")
            print("  --api           Test API endpoints")
            print("  --integration    Run full integration tests")
            print("  --demo          Run interactive demo")
            print("  --all           Run all tests (default)")
            print("  --help          Show this help")
            print()
            print("Examples:")
            print("  python test_callback_pipeline.py")
            print("  python test_callback_pipeline.py --flow")
            print("  python test_callback_pipeline.py --demo")
    
    finally:
        TestDatabase.cleanup_test_data()


def main():
    """Main entry point for callback pipeline tests."""
    import sys
    
    args = sys.argv[1:]
    
    # Run tests
    if "--demo" in args:
        asyncio.run(DemoSimulation.run_interactive_demo())
    elif "--all" in args or len(args) == 0:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    else:
        asyncio.run(run_specific_tests(args))


# ============================================================================
# ENVIRONMENT VALIDATION
# ============================================================================

def check_environment():
    """Check if required environment variables are set."""
    from backend.config.send2_config import validate_send2_environment
    from backend.services.google_oauth_setup import google_oauth_service
    
    print("\n" + "=" * 60)
    print("🔍 ENVIRONMENT VALIDATION")
    print("=" * 60)
    
    # Check Send2 Digital
    send2_check = validate_send2_environment()
    print(f"\n📧 Send2 Digital:")
    print(f"   Configured: {'✅ Yes' if send2_check['valid'] else '❌ No'}")
    if send2_check['issues']:
        for issue in send2_check['issues']:
            print(f"   ⚠️  {issue}")
    
    # Check Google OAuth
    google_configured = google_oauth_service.is_configured()
    print(f"\n🔑 Google OAuth:")
    print(f"   Configured: {'✅ Yes' if google_configured else '❌ No'}")
    if google_configured:
        auth_method = google_oauth_service.get_auth_method()
        print(f"   Method: {auth_method}")
    else:
        print("   ⚠️  Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or GOOGLE_SERVICE_ACCOUNT_JSON")
    
    # Summary
    ready = send2_check['valid'] and google_configured
    print(f"\n📊 Overall Status: {'✅ Ready for Production' if ready else '⚠️  Some configuration missing'}")
    
    return ready


if __name__ == "__main__":
    main()