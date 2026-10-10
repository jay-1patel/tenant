"""Callback and Meeting Scheduling Service for Chatbot2.

This service handles the complete callback booking pipeline:
1. User requests callback through WhatsApp
2. Collect user information and preferences
3. Schedule meeting in Google Calendar
4. Create Google Meet link
5. Send notifications to user and agent
6. Manage reminders and follow-ups

The pipeline supports:
- Multiple callback types (sales, support, technical)
- Time slot selection
- Agent assignment
- Google Meet integration
- Email and WhatsApp notifications
- Rescheduling and cancellation
"""

import logging
import json
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class CallbackStatus(Enum):
    """Status of a callback request."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class CallbackType(Enum):
    """Type of callback request."""
    SALES = "sales"
    SUPPORT = "support"
    TECHNICAL = "technical"
    GENERAL = "general"
    FOLLOW_UP = "follow_up"


class Priority(Enum):
    """Priority level for callback requests."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class CallbackRequest:
    """Complete callback request data."""
    id: str
    tenant_id: str
    wa_id: str  # WhatsApp user ID
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    callback_type: str = "general"
    priority: str = "medium"
    preferred_time: Optional[str] = None  # ISO format timestamp
    preferred_date: Optional[str] = None  # YYYY-MM-DD
    time_slot: Optional[str] = None  # e.g., "10:00-11:00"
    timezone: str = "Asia/Kolkata"
    purpose: str = ""
    additional_info: str = ""
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    meet_link: Optional[str] = None
    calendar_event_id: Optional[str] = None
    status: str = "pending"
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reminder_sent: bool = False
    notification_sent: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
        
    def is_scheduled(self) -> bool:
        """Check if callback is scheduled with a meet link."""
        return self.status == CallbackStatus.SCHEDULED.value and bool(self.meet_link)
    
    def is_active(self) -> bool:
        """Check if callback is in active state."""
        active_statuses = [
            CallbackStatus.PENDING.value,
            CallbackStatus.CONFIRMED.value,
            CallbackStatus.SCHEDULED.value,
            CallbackStatus.IN_PROGRESS.value
        ]
        return self.status in active_statuses


@dataclass
class AvailableTimeSlot:
    """Available time slot for scheduling."""
    id: str
    start_time: str  # ISO format
    end_time: str  # ISO format
    is_available: bool = True
    agent_id: Optional[str] = None
    display_text: str = ""


@dataclass
class GoogleMeetConfig:
    """Google Meet API configuration."""
    enabled: bool = False
    service_account_json: Optional[str] = None
    calendar_id: str = "primary"
    default_duration_minutes: int = 30
    meeting_title_template: str = "Callback Meeting - {customer_name}"
    meeting_description_template: str = "Callback requested by {customer_name} ({wa_id})\nType: {callback_type}\nPurpose: {purpose}"


@dataclass
class CallbackSettings:
    """Tenant-specific callback configuration."""
    enabled: bool = True
    callback_types: List[str] = field(default_factory=lambda: [t.value for t in CallbackType])
    business_hours: Dict[str, Any] = field(default_factory=dict)
    default_priority: str = Priority.MEDIUM.value
    default_duration_minutes: int = 30
    max_future_days: int = 7
    time_slots: List[Dict[str, str]] = field(default_factory=list)
    meet_config: GoogleMeetConfig = field(default_factory=GoogleMeetConfig)
    notification_settings: Dict[str, Any] = field(default_factory=dict)
    
    def get_available_slots(self, date_str: str, timezone: str = "Asia/Kolkata") -> List[AvailableTimeSlot]:
        """Generate available time slots for a given date."""
        # Implementation to generate time slots based on configuration
        slots = []
        start_hour = int(self.business_hours.get("open_hour", 9))
        end_hour = int(self.business_hours.get("close_hour", 18))
        slot_duration = min(self.default_duration_minutes, 60)
        
        for hour in range(start_hour, end_hour):
            for minute in [0, 30] if slot_duration == 30 else [0]:
                start = f"{hour:02d}:{minute:02d}"
                end_hour_offset = hour + (slot_duration // 60)
                end_minute = (minute + (slot_duration % 60)) % 60
                if end_minute == 0:
                    end_hour_offset += 1
                end = f"{end_hour_offset:02d}:{end_minute:02d}"
                
                if end_hour_offset <= end_hour:
                    slot_id = f"{date_str}_{start}_{end}"
                    slots.append(AvailableTimeSlot(
                        id=slot_id,
                        start_time=f"{date_str}T{start}:00",
                        end_time=f"{date_str}T{end}:00",
                        is_available=True,
                        display_text=f"{start} - {end}"
                    ))
        
        return slots


class CallbackService:
    """Main callback service handling all callback operations."""
    
    def __init__(self):
        self.timezone = "Asia/Kolkata"
    
    def create_callback_request(
        self,
        tenant_id: str,
        wa_id: str,
        customer_name: str,
        callback_type: str = "general",
        purpose: str = "",
        preferred_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None,
        priority: str = "medium",
        additional_info: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> CallbackRequest:
        """Create a new callback request."""
        callback_id = self._generate_callback_id()
        
        # Determine status based on information provided
        if preferred_date and preferred_time:
            status = CallbackStatus.CONFIRMED.value
        else:
            status = CallbackStatus.PENDING.value
        
        request = CallbackRequest(
            id=callback_id,
            tenant_id=tenant_id,
            wa_id=wa_id,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            callback_type=callback_type,
            priority=priority,
            preferred_date=preferred_date,
            preferred_time=preferred_time,
            purpose=purpose,
            additional_info=additional_info,
            timezone=self.timezone,
            status=status,
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc).isoformat()
        )
        
        logger.info(f"Callback request created: {callback_id} for tenant {tenant_id}")
        return request
    
    def _generate_callback_id(self) -> str:
        """Generate a unique callback ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        random_part = secrets.token_hex(4)
        return f"CB-{timestamp}-{random_part}"
    
    def schedule_callback_with_meet(
        self,
        callback_request: CallbackRequest,
        agent_id: str,
        agent_name: str,
        start_time: str,
        end_time: str,
        calendar_event_id: str,
        meet_link: str
    ) -> CallbackRequest:
        """Schedule a callback with Google Meet link."""
        callback_request.status = CallbackStatus.SCHEDULED.value
        callback_request.assigned_agent_id = agent_id
        callback_request.assigned_agent_name = agent_name
        callback_request.scheduled_start_time = start_time
        callback_request.scheduled_end_time = end_time
        callback_request.calendar_event_id = calendar_event_id
        callback_request.meet_link = meet_link
        callback_request.updated_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"Callback {callback_request.id} scheduled with Meet: {meet_link}")
        return callback_request
    
    def get_callback_by_id(self, callback_id: str) -> Optional[CallbackRequest]:
        """Retrieve callback request by ID (to be implemented with DB)."""
        # This will be implemented with database access
        return None
    
    def list_callbacks(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        wa_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[CallbackRequest]:
        """List callback requests with filters."""
        # This will be implemented with database access
        return []
    
    def update_callback_status(
        self,
        callback_id: str,
        new_status: str,
        notes: str = ""
    ) -> Optional[CallbackRequest]:
        """Update callback status."""
        # This will be implemented with database access
        return None
    
    def cancel_callback(
        self,
        callback_id: str,
        cancelled_by: str,
        reason: str = ""
    ) -> Optional[CallbackRequest]:
        """Cancel a callback request."""
        # This will be implemented with database access
        return None
    
    def send_reminder_notifications(self, callback_request: CallbackRequest) -> bool:
        """Send reminder notifications for scheduled callbacks."""
        # Implementation to send reminders via email/WhatsApp
        return True
    
    def validate_time_slot(
        self,
        date_str: str,
        time_slot: str,
        timezone: str = "Asia/Kolkata"
    ) -> Tuple[bool, Optional[str]]:
        """Validate if a time slot is still available."""
        # Check if slot is in the future
        try:
            from dateutil.parser import parse
            slot_time = parse(f"{date_str}T{time_slot}", fuzzy=True)
            if slot_time < datetime.now(timezone=timezone.utc):
                return False, "Time slot is in the past"
            return True, None
        except Exception as e:
            return False, f"Invalid time slot: {e}"
    
    def create_meeting_summary(
        self,
        callback_request: CallbackRequest,
        meeting_notes: str = ""
    ) -> Dict[str, Any]:
        """Create a summary after completed callback meeting."""
        summary = {
            "callback_id": callback_request.id,
            "tenant_id": callback_request.tenant_id,
            "customer_name": callback_request.customer_name,
            "wa_id": callback_request.wa_id,
            "agent_name": callback_request.assigned_agent_name or "Unknown",
            "start_time": callback_request.scheduled_start_time,
            "end_time": callback_request.scheduled_end_time,
            "meet_link": callback_request.meet_link,
            "meeting_notes": meeting_notes,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        return summary


class GoogleMeetService:
    """Service for Google Meet integration."""
    
    GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"
    
    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path
        self._access_token = None
        self._token_expires_at = None
    
    async def authenticate(self) -> bool:
        """Authenticate with Google API."""
        # Implementation for OAuth2 or service account authentication
        return True
    
    async def create_meeting(
        self,
        calendar_id: str = "primary",
        title: str = "Callback Meeting",
        description: str = "",
        start_time: str = "",
        end_time: str = "",
        attendees: List[Dict[str, str]] = None,
        timezone: str = "Asia/Kolkata"
    ) -> Dict[str, Any]:
        """Create a Google Calendar event with Meet link."""
        try:
            # This will be implemented with actual Google API calls
            # For now, return mock response for simulation
            meet_link = f"https://meet.google.com/xxx-yyyy-zzz"
            event_id = f"event_{secrets.token_hex(8)}"
            
            return {
                "ok": True,
                "event_id": event_id,
                "meet_link": meet_link,
                "html_link": f"https://calendar.google.com/calendar/event?action=VIEW&eid={event_id}",
                "start": start_time,
                "end": end_time
            }
        except Exception as e:
            logger.error(f"Failed to create Google Meet: {e}")
            return {"ok": False, "error": str(e)}
    
    async def get_calendar_events(
        self,
        calendar_id: str = "primary",
        start_date: str = "",
        end_date: str = "",
        max_results: int = 50
    ) -> Dict[str, Any]:
        """Get calendar events to check for conflicts."""
        # Implementation to get existing events
        return {"ok": True, "events": []}
    
    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """Delete a calendar event."""
        # Implementation to delete event
        return True
    
    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update a calendar event."""
        # Implementation to update event
        return True


class NotificationService:
    """Service for sending notifications related to callbacks."""
    
    def __init__(self, whatsapp_service=None):
        self.whatsapp_service = whatsapp_service
    
    async def send_whatsapp_notification(
        self,
        phone_number: str,
        message: str,
        template_id: Optional[str] = None,
        template_params: Optional[Dict[str, str]] = None
    ) -> bool:
        """Send WhatsApp notification via official WhatsApp Business API."""
        # Implementation to send WhatsApp messages
        return True
    
    async def send_email_notification(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False
    ) -> bool:
        """Send email notification."""
        # Implementation to send emails
        return True
    
    async def send_sms_notification(
        self,
        phone_number: str,
        message: str
    ) -> bool:
        """Send SMS notification."""
        # Implementation to send SMS
        return True
    
    def format_callback_confirmation(
        self,
        callback_request: CallbackRequest
    ) -> str:
        """Format callback confirmation message for customer."""
        date_str = callback_request.preferred_date or "soon"
        time_str = callback_request.preferred_time or "as available"
        
        if callback_request.is_scheduled():
            date_str = callback_request.scheduled_start_time.split("T")[0]
            time_str = callback_request.scheduled_start_time.split("T")[1].split(":")[0:2]
            time_str = f"{time_str[0]}:{time_str[1]}"
            
            return (
                f"📅 Callback Confirmed!\n\n"
                f"📅 Date: {date_str}\n"
                f"⏰ Time: {time_str} {callback_request.timezone}\n"
                f"👤 Agent: {callback_request.assigned_agent_name or 'Our team'}\n"
                f"🎯 Purpose: {callback_request.purpose or 'Discussion'}\n\n"
                f"🔗 Join Meeting: {callback_request.meet_link}\n\n"
                f"You'll receive a reminder 15 minutes before the meeting.\n"
                f"Callback ID: {callback_request.id}"
            )
        else:
            return (
                f"✅ Callback Request Received!\n\n"
                f"👤 Your Name: {callback_request.customer_name}\n"
                f"🎯 callback Type: {callback_request.callback_type}\n"
                f"📝 Purpose: {callback_request.purpose or 'Not specified'}\n\n"
                f"👥 Our team will contact you shortly to confirm a time.\n"
                f"Callback ID: {callback_request.id}"
            )
    
    def format_agent_notification(
        self,
        callback_request: CallbackRequest
    ) -> str:
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
            f"Callback ID: {callback_request.id}"
        )
    
    def format_reminder_message(
        self,
        callback_request: CallbackRequest,
        minutes_before: int = 15
    ) -> str:
        """Format reminder message."""
        start_time = callback_request.scheduled_start_time
        if start_time:
            from dateutil.parser import parse
            meeting_time = parse(start_time)
            reminder_time = meeting_time - timedelta(minutes=minutes_before)
            
            return (
                f"⏰ Reminder: Your callback is starting soon!\n\n"
                f"📅 Date: {start_time.split('T')[0]}\n"
                f"⏰ Time: {start_time.split('T')[1].split(':')[0:2]}\n"
                f"👤 Agent: {callback_request.assigned_agent_name or 'Our team'}\n"
                f"🔗 Join Meeting: {callback_request.meet_link}\n\n"
                f"Meeting starts in {minutes_before} minutes."
            )
        return ""  
    
    def format_cancellation_message(
        self,
        callback_request: CallbackRequest,
        reason: str = ""
    ) -> str:
        """Format callback cancellation message."""
        return (
            f"❌ Callback Cancelled\n\n"
            f"Callback ID: {callback_request.id}\n"
            f"📅 Date: {callback_request.preferred_date or 'N/A'}\n"
            f"⏰ Time: {callback_request.preferred_time or 'N/A'}\n"
            f"💬 Reason: {reason or 'Not specified'}"
        )


# Singleton instances
callback_service = CallbackService()
google_meet_service = GoogleMeetService()
notification_service = NotificationService()