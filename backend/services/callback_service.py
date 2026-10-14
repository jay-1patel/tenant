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
import os
import re
import random
import string
import urllib.parse
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from dateutil.tz import gettz as ZoneInfo

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
    created_at: str = field(default_factory=lambda: datetime.now(dt_timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(dt_timezone.utc).isoformat())
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
            created_at=datetime.now(dt_timezone.utc).isoformat()
        )
        
        logger.info(f"Callback request created: {callback_id} for tenant {tenant_id}")
        return request
    
    def _generate_callback_id(self) -> str:
        """Generate a unique callback ID."""
        timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%d%H%M%S")
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
        callback_request.updated_at = datetime.now(dt_timezone.utc).isoformat()
        
        logger.info(f"Callback {callback_request.id} scheduled with Meet: {meet_link}")
        return callback_request
    
    def save_callback_to_db(self, callback_request: CallbackRequest) -> bool:
        """Save or update callback request in database."""
        try:
            from database import get_db_context
            callback_data = json.dumps(callback_request.to_dict())
            with get_db_context() as conn:
                existing = conn.execute(
                    "SELECT id FROM callbacks WHERE id = ?", (callback_request.id,)
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE callbacks SET 
                           data = ?, status = ?, tenant_id = ?, wa_id = ?,
                           scheduled_start_time = ?, scheduled_end_time = ?,
                           meet_link = ?, calendar_event_id = ?, updated_at = ?
                           WHERE id = ?""",
                        (
                            callback_data,
                            callback_request.status,
                            callback_request.tenant_id,
                            callback_request.wa_id,
                            callback_request.scheduled_start_time,
                            callback_request.scheduled_end_time,
                            callback_request.meet_link,
                            callback_request.calendar_event_id,
                            datetime.now(dt_timezone.utc).isoformat(),
                            callback_request.id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO callbacks 
                           (id, tenant_id, wa_id, data, status, scheduled_start_time, scheduled_end_time, meet_link, calendar_event_id, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            callback_request.id,
                            callback_request.tenant_id,
                            callback_request.wa_id,
                            callback_data,
                            callback_request.status,
                            callback_request.scheduled_start_time,
                            callback_request.scheduled_end_time,
                            callback_request.meet_link,
                            callback_request.calendar_event_id,
                            callback_request.created_at,
                            callback_request.updated_at,
                        ),
                    )
            return True
        except Exception as e:
            logger.error(f"Failed to save callback {callback_request.id} to DB: {e}")
            return False

    def get_callback_by_id(self, callback_id: str) -> Optional[CallbackRequest]:
        """Retrieve callback request by ID from database."""
        try:
            from database import get_db_context
            with get_db_context() as conn:
                row = conn.execute(
                    "SELECT data FROM callbacks WHERE id = ?", (callback_id,)
                ).fetchone()
                if row and row[0]:
                    data = json.loads(row[0])
                    return CallbackRequest(**data)
            return None
        except Exception as e:
            logger.error(f"Failed to get callback {callback_id}: {e}")
            return None

    def list_callbacks(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        wa_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[CallbackRequest]:
        """List callback requests from database with filters."""
        try:
            from database import get_db_context
            with get_db_context() as conn:
                query = "SELECT data FROM callbacks WHERE tenant_id = ?"
                params = [tenant_id]
                if status and status != "all":
                    query += " AND status = ?"
                    params.append(status)
                if wa_id:
                    query += " AND wa_id = ?"
                    params.append(wa_id)
                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                rows = conn.execute(query, params).fetchall()
                results = []
                for r in rows:
                    if r and r[0]:
                        results.append(CallbackRequest(**json.loads(r[0])))
                return results
        except Exception as e:
            logger.error(f"Failed to list callbacks for {tenant_id}: {e}")
            return []

    def update_callback_status(
        self,
        callback_id: str,
        new_status: str,
        notes: str = ""
    ) -> Optional[CallbackRequest]:
        """Update callback status."""
        cb = self.get_callback_by_id(callback_id)
        if not cb:
            return None
        cb.status = new_status
        cb.updated_at = datetime.now(dt_timezone.utc).isoformat()
        if notes:
            cb.metadata["status_notes"] = notes
        self.save_callback_to_db(cb)
        return cb

    def cancel_callback(
        self,
        callback_id: str,
        cancelled_by: str,
        reason: str = ""
    ) -> Optional[CallbackRequest]:
        """Cancel a callback request."""
        cb = self.get_callback_by_id(callback_id)
        if not cb:
            return None
        cb.status = CallbackStatus.CANCELLED.value
        cb.updated_at = datetime.now(dt_timezone.utc).isoformat()
        cb.metadata["cancellation_reason"] = reason
        cb.metadata["cancelled_by"] = cancelled_by
        self.save_callback_to_db(cb)
        return cb

    def create_and_schedule_callback(
        self,
        tenant_id: str,
        wa_id: str,
        customer_name: str,
        customer_phone: Optional[str] = None,
        customer_email: Optional[str] = None,
        preferred_time: Optional[str] = None,
        preferred_date: Optional[str] = None,
        purpose: str = "",
        callback_type: str = "general",
        priority: str = "medium",
        additional_info: str = "",
        agent_name: str = "Leeway Softech Team",
        agent_id: str = "agent_default",
    ) -> CallbackRequest:
        """Create callback, generate Google Meeting, and persist to database."""
        callback_id = self._generate_callback_id()
        start_iso, end_iso, display_str, s_utc, e_utc = parse_preferred_time_to_range(
            preferred_time=preferred_time,
            preferred_date=preferred_date,
            timezone_str=self.timezone,
        )

        meet_res = google_meet_service.create_meeting_sync(
            title=f"Meeting: {customer_name} - {purpose or 'Discussion'}",
            description=f"Callback requested via WhatsApp by {customer_name} ({wa_id}).\nTopic: {purpose or 'Discussion'}\nPhone: {customer_phone or wa_id}",
            start_time=start_iso,
            end_time=end_iso,
            attendees=[{"email": customer_email, "displayName": customer_name}] if customer_email else None,
            timezone=self.timezone,
            tenant_id=tenant_id,
        )

        meet_link = meet_res.get("meet_link")
        event_id = meet_res.get("event_id")
        calendar_add_url = meet_res.get("calendar_add_url", "")

        cb = CallbackRequest(
            id=callback_id,
            tenant_id=tenant_id,
            wa_id=wa_id,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone or wa_id,
            callback_type=callback_type,
            priority=priority,
            preferred_date=start_iso.split("T")[0],
            preferred_time=display_str,
            purpose=purpose,
            additional_info=additional_info,
            timezone=self.timezone,
            assigned_agent_id=agent_id,
            assigned_agent_name=agent_name,
            meet_link=meet_link,
            calendar_event_id=event_id,
            status=CallbackStatus.SCHEDULED.value if meet_link else CallbackStatus.CONFIRMED.value,
            scheduled_start_time=start_iso,
            scheduled_end_time=end_iso,
            metadata={
                "calendar_add_url": calendar_add_url,
                "display_time": display_str,
                "created_via": "whatsapp_bot",
                "oauth_connected": bool(meet_link),
            },
            created_at=datetime.now(dt_timezone.utc).isoformat(),
            updated_at=datetime.now(dt_timezone.utc).isoformat(),
        )

        self.save_callback_to_db(cb)
        logger.info(f"Callback {callback_id} created and scheduled with Google Meet: {meet_link}")
        return cb

    def send_reminder_notifications(self, callback_request: CallbackRequest) -> bool:
        """Send reminder notifications for scheduled callbacks."""
        return True

    def validate_time_slot(
        self,
        date_str: str,
        time_slot: str,
        timezone: str = "Asia/Kolkata"
    ) -> Tuple[bool, Optional[str]]:
        """Validate if a time slot is still available."""
        try:
            from dateutil.parser import parse
            slot_time = parse(f"{date_str}T{time_slot}", fuzzy=True)
            if slot_time < datetime.now(tz=dt_timezone.utc):
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
            "created_at": datetime.now(dt_timezone.utc).isoformat()
        }
        return summary


def parse_preferred_time_to_range(
    preferred_time: Optional[str] = None,
    preferred_date: Optional[str] = None,
    timezone_str: str = "Asia/Kolkata",
    duration_minutes: int = 30,
) -> Tuple[str, str, str, str, str]:
    """Parse customer-provided preferred time and date into:
    (start_iso, end_iso, display_str, start_utc_compact, end_utc_compact)
    """
    try:
        tz = ZoneInfo(timezone_str)
    except Exception:
        tz = dt_timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(tz)

    raw = (preferred_time or "").strip().lower()
    raw_date = (preferred_date or "").strip()

    target_date = None
    target_hour = 11
    target_minute = 0

    if raw_date:
        try:
            from dateutil.parser import parse
            target_date = parse(raw_date, fuzzy=True).date()
        except Exception:
            pass

    if "tomorrow" in raw:
        target_date = (now + timedelta(days=1)).date()
    elif "today" in raw:
        target_date = now.date()
    elif "day after tomorrow" in raw:
        target_date = (now + timedelta(days=2)).date()

    if "morning" in raw and not any(f"{h}" in raw for h in range(1, 13)):
        target_hour = 10
        target_minute = 0
    elif "afternoon" in raw and not any(f"{h}" in raw for h in range(1, 13)):
        target_hour = 14
        target_minute = 0
    elif "evening" in raw and not any(f"{h}" in raw for h in range(1, 13)):
        target_hour = 17
        target_minute = 0

    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", raw)
    if m:
        h = int(m.group(1))
        min_ = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        if ampm:
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
        elif h <= 6:
            h += 12
        target_hour = min(max(h, 9), 19)
        target_minute = min_

    if not target_date and raw and raw not in ("skip", "none", "na", "-", "any", "any time", "anytime"):
        try:
            from dateutil.parser import parse
            parsed_dt = parse(preferred_time, fuzzy=True)
            target_date = parsed_dt.date()
            if not m:
                target_hour = parsed_dt.hour
                target_minute = parsed_dt.minute
        except Exception:
            pass

    if not target_date:
        target_date = (now + timedelta(days=1)).date()
    elif target_date < now.date():
        target_date = (now + timedelta(days=1)).date()

    start_dt = datetime(target_date.year, target_date.month, target_date.day, target_hour, target_minute, tzinfo=tz)
    if start_dt <= now:
        start_dt = start_dt + timedelta(days=1)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()
    display_str = start_dt.strftime("%A, %d %b %Y at %I:%M %p (IST)")
    start_utc_compact = start_dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end_utc_compact = end_dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return start_iso, end_iso, display_str, start_utc_compact, end_utc_compact


def generate_meet_code() -> str:
    p1 = "".join(random.choices(string.ascii_lowercase, k=3))
    p2 = "".join(random.choices(string.ascii_lowercase, k=4))
    p3 = "".join(random.choices(string.ascii_lowercase, k=3))
    return f"{p1}-{p2}-{p3}"


def generate_meet_link(code: Optional[str] = None) -> str:
    return f"https://meet.google.com/{code or generate_meet_code()}"


def generate_gcal_add_url(
    title: str,
    description: str,
    start_utc_compact: str,
    end_utc_compact: str,
    meet_link: str,
) -> str:
    details = f"{description}\n\nJoin Google Meet: {meet_link}"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_utc_compact}/{end_utc_compact}",
        "details": details,
        "location": meet_link,
    }
    return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"


class GoogleMeetService:
    """Service for Google Meet integration."""

    GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"

    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path
        self._access_token = None
        self._token_expires_at = None

    async def authenticate(self) -> bool:
        """Authenticate with Google API."""
        return True

    def create_meeting_sync(
        self,
        calendar_id: str = "primary",
        title: str = "Callback Meeting",
        description: str = "",
        start_time: str = "",
        end_time: str = "",
        attendees: Optional[List[Dict[str, str]]] = None,
        timezone: str = "Asia/Kolkata",
        tenant_id: str = "leewaysoftech",
    ) -> Dict[str, Any]:
        """Create a Google Calendar event with Meet link using tenant OAuth tokens."""
        from services.google_meet_service import create_meeting_sync as gmeet_create_sync
        return gmeet_create_sync(
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            timezone=timezone,
        )

    async def create_meeting(
        self,
        calendar_id: str = "primary",
        title: str = "Callback Meeting",
        description: str = "",
        start_time: str = "",
        end_time: str = "",
        attendees: Optional[List[Dict[str, str]]] = None,
        timezone: str = "Asia/Kolkata",
        tenant_id: str = "leewaysoftech",
    ) -> Dict[str, Any]:
        """Async wrapper using tenant OAuth tokens."""
        from services.google_meet_service import create_meeting as gmeet_create_async
        return await gmeet_create_async(
            tenant_id=tenant_id,
            calendar_id=calendar_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            timezone=timezone,
        )

    async def get_calendar_events(
        self,
        calendar_id: str = "primary",
        start_date: str = "",
        end_date: str = "",
        max_results: int = 50
    ) -> Dict[str, Any]:
        """Get calendar events to check for conflicts."""
        return {"ok": True, "events": []}

    async def delete_event(self, calendar_id: str, event_id: str, tenant_id: str = "leewaysoftech") -> bool:
        """Delete a calendar event using stored OAuth tokens."""
        from services.google_meet_service import delete_event as gmeet_delete_async
        return await gmeet_delete_async(event_id=event_id, tenant_id=tenant_id, calendar_id=calendar_id)

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update a calendar event."""
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
        """Send WhatsApp notification via Send2 / WhatsApp."""
        try:
            import re
            from routing.whatsapp import send_whatsapp_message
            clean_phone = re.sub(r"[^\d]", "", str(phone_number or "")).strip()
            if not clean_phone:
                logger.warning("Cannot send WhatsApp notification: phone_number is empty")
                return False
            success = send_whatsapp_message(clean_phone, message)
            if success:
                try:
                    from database import save_chat
                    save_chat(clean_phone, "System", "[Meeting Scheduled]", message, "callback_meet")
                except Exception as ce:
                    logger.debug(f"Could not save scheduled callback to chat history: {ce}")
            return success
        except Exception as e:
            logger.error(f"Failed to send callback WhatsApp notification to {phone_number}: {e}")
            return False
    
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
        time_display = ""
        if callback_request.scheduled_start_time:
            try:
                from dateutil.parser import parse
                dt = parse(callback_request.scheduled_start_time)
                time_display = dt.strftime("%A, %d %b %Y at %I:%M %p")
            except Exception:
                time_display = callback_request.scheduled_start_time
        if not time_display:
            parts = [p for p in [callback_request.preferred_date, callback_request.preferred_time] if p]
            time_display = " ".join(parts) if parts else "as scheduled"

        cal_url = callback_request.metadata.get("calendar_add_url") if isinstance(callback_request.metadata, dict) else None

        if callback_request.is_scheduled():
            lines = [
                "📅 *Callback & Google Meeting Confirmed!*",
                f"\n👤 *Customer:* {callback_request.customer_name}",
                f"⏰ *Scheduled Time:* {time_display}",
                f"🎯 *Purpose:* {callback_request.purpose or 'Discussion'}",
                f"\n🔗 *Google Meet Link:*\n{callback_request.meet_link}",
            ]
            if cal_url:
                lines.append(f"\n📅 *Add to Google Calendar:*\n{cal_url}")
            lines.append("\nPlease join using the Google Meet link above at the scheduled time!")
            lines.append(f"\nCallback ID: {callback_request.id}")
            return "\n".join(lines)
        else:
            return (
                f"✅ *Callback Request Received!*\n\n"
                f"👤 *Your Name:* {callback_request.customer_name}\n"
                f"🎯 *Type:* {callback_request.callback_type}\n"
                f"📝 *Purpose:* {callback_request.purpose or 'Not specified'}\n\n"
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