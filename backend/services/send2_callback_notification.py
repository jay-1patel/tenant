"""Send2 Digital WhatsApp Notification Service for Callback Booking.

This module integrates with your existing Send2 Digital WhatsApp Business API
to send callback-related notifications, reminders, and confirmations.

Features:
- WhatsApp message templates for callback booking
- Confirmed scheduling notifications
- Reminder notifications (24h and 15min before)
- Cancellation notifications
- Rescheduling notifications
- Agent assignment notifications
- Uses your existing Send2 Digital integration
"""

import json
import logging
import httpx
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from backend.services.callback_service import CallbackRequest, callback_service, notification_service
from backend.database import get_db_context

logger = logging.getLogger(__name__)


class Send2CallbackNotificationService:
    """Service for sending callback notifications via Send2 Digital WhatsApp API."""
    
    def __init__(self):
        self.base_url = "https://api.send2.digital"
        self.api_key = None
        self.api_secret = None
        self._load_config()
    
    def _load_config(self):
        """Load Send2 Digital configuration from environment variables."""
        import os
        self.api_key = os.getenv("SEND2_API_KEY")
        self.api_secret = os.getenv("SEND2_API_SECRET")
        self.whatsapp_business_id = os.getenv("SEND2_WHA_BUSINESS_ID")
        self.phone_number_id = os.getenv("SEND2_PHONE_NUMBER_ID")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Send2 Digital API requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": self.api_key or "",
            "X-API-Secret": self.api_secret or ""
        }
    
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make HTTP request to Send2 Digital API."""
        url = f"{self.base_url}{endpoint}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                headers = self._get_headers()
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=data
                )
                
                response_data = response.json()
                
                if response.status_code != 200:
                    logger.error(f"Send2 API Error: {response.status_code} - {response_data}")
                    return {"ok": False, "error": response_data.get("message", "Unknown error")}
                
                return {"ok": True, **response_data}
                
            except httpx.TimeoutException:
                logger.error("Send2 API request timed out")
                return {"ok": False, "error": "Request timeout"}
            except httpx.RequestError as e:
                logger.error(f"Send2 API request failed: {e}")
                return {"ok": False, "error": str(e)}
            except Exception as e:
                logger.error(f"Send2 API error: {e}")
                return {"ok": False, "error": str(e)}
    
    async def send_callback_confirmation(self, callback_request: CallbackRequest) -> bool:
        """Send WhatsApp confirmation when callback is created."""
        if not callback_request.wa_id:
            logger.warning("No WhatsApp ID for callback confirmation")
            return False
        
        # Use template or direct message based on your Send2 setup
        message = self._format_callback_confirmation(callback_request)
        
        return await self._send_whatsapp_message(
            phone=callback_request.wa_id,
            message=message
        )
    
    async def send_cancellation_notification(self, callback_request: CallbackRequest, reason: str) -> bool:
        """Send WhatsApp notification when callback is cancelled."""
        if not callback_request.wa_id:
            return False
        
        message = self._format_cancellation_message(callback_request, reason)
        return await self._send_whatsapp_message(
            phone=callback_request.wa_id,
            message=message
        )
    
    async def send_reminder_notification(self, callback_request: CallbackRequest, minutes_before: int = 15) -> bool:
        """Send reminder notification before callback."""
        if not callback_request.wa_id or not callback_request.scheduled_start_time:
            return False
        
        message = self._format_reminder_message(callback_request, minutes_before)
        return await self._send_whatsapp_message(
            phone=callback_request.wa_id,
            message=message
        )
    
    async def send_scheduled_notification(self, callback_request: CallbackRequest) -> bool:
        """Send notification when callback is scheduled with Meet link."""
        if not callback_request.wa_id or not callback_request.meet_link:
            return False
        
        message = self._format_scheduled_message(callback_request)
        return await self._send_whatsapp_message(
            phone=callback_request.wa_id,
            message=message
        )
    
    async def send_reschedule_notification(self, callback_request: CallbackRequest, reason: str) -> bool:
        """Send notification when callback is rescheduled."""
        if not callback_request.wa_id:
            return False
        
        message = self._format_reschedule_message(callback_request, reason)
        return await self._send_whatsapp_message(
            phone=callback_request.wa_id,
            message=message
        )
    
    async def send_agent_assignment_notification(self, callback_request: CallbackRequest) -> bool:
        """Send notification to agent when assigned to callback."""
        if not callback_request.assigned_agent_id:
            return False
        
        # This would need agent's phone number - to be implemented based on your agent DB
        agent_phone = self._get_agent_phone(callback_request.assigned_agent_id)
        if not agent_phone:
            logger.warning(f"No phone number found for agent: {callback_request.assigned_agent_id}")
            return False
        
        message = self._format_agent_notification(callback_request)
        return await self._send_whatsapp_message(
            phone=agent_phone,
            message=message
        )
    
    async def _send_whatsapp_message(self, phone: str, message: str) -> bool:
        """Send a WhatsApp message through Send2 Digital."""
        # Implementation based on your Send2 Digital API
        # Adjust based on your actual Send2 Digital integration
        
        payload = {
            "recipient_phone": phone,
            "message_type": "text",
            "message": message,
            "business_id": self.whatsapp_business_id,
            "phone_number_id": self.phone_number_id
        }
        
        result = await self._make_request("POST", "/v1/messages", payload)
        return result.get("ok", False)
    
    def _format_callback_confirmation(self, callback_request: CallbackRequest) -> str:
        """Format callback confirmation message for customer."""
        return (
            f"✅ Thank you for your callback request!\n\n"
            f"📞 Your request has been received and we'll contact you shortly.\n\n"
            f"📝 Request ID: {callback_request.id}\n"
            f"🎯 Purpose: {callback_request.purpose or 'Not specified'}\n"
            f"📅 Preferred: {callback_request.preferred_date or 'ASAP'}\n"
            f"⏰ Time: {callback_request.preferred_time or 'Anytime'}\n\n"
            f"Our team will confirm the exact time and send you a Google Meet link."
        )
    
    def _format_scheduled_message(self, callback_request: CallbackRequest) -> str:
        """Format scheduled callback message with Meet link."""
        start_time = callback_request.scheduled_start_time
        if start_time:
            from dateutil.parser import parse
            dt = parse(start_time)
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%I:%M %p")
        else:
            date_str = callback_request.preferred_date or "TBD"
            time_str = callback_request.preferred_time or "TBD"
        
        return (
            f"📅 Callback Confirmed!\n\n"
            f"📆 Date: {date_str}\n"
            f"⏰ Time: {time_str} ({callback_request.timezone})\n"
            f"👤 Agent: {callback_request.assigned_agent_name or 'Our team'}\n"
            f"🎯 Purpose: {callback_request.purpose or 'Discussion'}\n\n"
            f"🔗 Join Meeting: {callback_request.meet_link}\n\n"
            f"🎫 Request ID: {callback_request.id}\n\n"
            f"You'll receive a reminder 15 minutes before the meeting.\n"
            f"If you need to change, reply with your request ID."
        )
    
    def _format_reminder_message(self, callback_request: CallbackRequest, minutes_before: int) -> str:
        """Format reminder message."""
        start_time = callback_request.scheduled_start_time
        if start_time:
            from dateutil.parser import parse
            dt = parse(start_time)
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%I:%M %p")
        else:
            date_str = callback_request.preferred_date or "TBD"
            time_str = callback_request.preferred_time or "TBD"
        
        return (
            f"⏰ REMINDER: Your callback starts soon!\n\n"
            f"📅 Date: {date_str}\n"
            f"⏰ Time: {time_str}\n"
            f"👤 Agent: {callback_request.assigned_agent_name or 'Our team'}\n"
            f"🔗 Join Now: {callback_request.meet_link}\n\n"
            f"Meeting starts in {minutes_before} minutes."
        )
    
    def _format_cancellation_message(self, callback_request: CallbackRequest, reason: str) -> str:
        """Format cancellation message."""
        date_str = callback_request.preferred_date or "N/A"
        time_str = callback_request.preferred_time or "N/A"
        
        return (
            f"❌ Callback Cancelled\n\n"
            f"📅 Date: {date_str}\n"
            f"⏰ Time: {time_str}\n"
            f"🎫 Request ID: {callback_request.id}\n"
            f"💬 Reason: {reason or 'Not specified'}\n\n"
            f"If you still need assistance, feel free to request a new callback."
        )
    
    def _format_reschedule_message(self, callback_request: CallbackRequest, reason: str) -> str:
        """Format reschedule message."""
        start_time = callback_request.scheduled_start_time
        if start_time:
            from dateutil.parser import parse
            dt = parse(start_time)
            new_date = dt.strftime("%Y-%m-%d")
            new_time = dt.strftime("%I:%M %p")
        else:
            new_date = callback_request.preferred_date or "TBD"
            new_time = callback_request.preferred_time or "TBD"
        
        return (
            f"🔄 Callback Rescheduled\n\n"
            f"📅 New Date: {new_date}\n"
            f"⏰ New Time: {new_time}\n"
            f"👤 Agent: {callback_request.assigned_agent_name or 'Our team'}\n"
            f"🔗 New Meet Link: {callback_request.meet_link}\n"
            f"🎫 Request ID: {callback_request.id}\n"
            f"💬 Reason: {reason}\n\n"
            f"Meeting starts in {new_time} on {new_date}."
        )
    
    def _format_agent_notification(self, callback_request: CallbackRequest) -> str:
        """Format notification message for assigned agent."""
        return (
            f"🔔 New Callback Assigned\n\n"
            f"📞 Customer: {callback_request.customer_name}\n"
            f"📱 WhatsApp: {callback_request.wa_id}\n"
            f"📧 Email: {callback_request.customer_email or 'N/A'}\n"
            f"🎯 Type: {callback_request.callback_type}\n"
            f"📅 Date: {callback_request.preferred_date or 'TBD'}\n"
            f"⏰ Time: {callback_request.preferred_time or 'TBD'}\n"
            f"📝 Purpose: {callback_request.purpose or 'Not specified'}\n"
            f"🔗 Meet Link: {callback_request.meet_link or 'To be created'}\n\n"
            f"🎫 Request ID: {callback_request.id}"
        )
    
    def _get_agent_phone(self, agent_id: str) -> Optional[str]:
        """Get agent phone number for WhatsApp notifications."""
        # This should be implemented based on your agent database
        # For now, return a placeholder
        return None
    
    def is_configured(self) -> bool:
        """Check if Send2 Digital is properly configured."""
        return bool(self.api_key and self.api_secret)


# Singleton instance
send2_callback_service = Send2CallbackNotificationService()