"""Callback Booking and Meeting Scheduling API Routes.

This module provides the complete pipeline for callback booking:
1. User initiates callback request through WhatsApp
2. Collect user requirements and preferences
3. Match with available agents and time slots
4. Schedule meeting in Google Calendar with Meet link
5. Send notifications to all parties
6. Manage rescheduling, cancellation, and follow-ups

Endpoints:
- POST /api/tenants/{tenant_id}/callbacks - Create new callback request
- GET /api/tenants/{tenant_id}/callbacks - List all callbacks
- GET /api/tenants/{tenant_id}/callbacks/{callback_id} - Get specific callback
- PUT /api/tenants/{tenant_id}/callbacks/{callback_id} - Update callback
- POST /api/tenants/{tenant_id}/callbacks/{callback_id}/schedule - Schedule callback
- POST /api/tenants/{tenant_id}/callbacks/{callback_id}/cancel - Cancel callback
- POST /api/tenants/{tenant_id}/callbacks/{callback_id}/complete - Mark as completed
- GET /api/tenants/{tenant_id}/callbacks/{callback_id}/summary - Get callback summary
- GET /api/tenants/{tenant_id}/callbacks/time-slots - Get available time slots
- POST /api/tenants/{tenant_id}/callbacks/meet-test - Test Google Meet integration
"""

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field

from database import get_db_context, record_admin_audit_event
from routes.auth import get_current_admin, has_permission, require_tenant_access
from services.callback_service import (
    CallbackRequest,
    CallbackService,
    CallbackStatus,
    CallbackType,
    Priority,
    callback_service,
    google_meet_service,
    notification_service
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants", tags=["callbacks"])


# ── Pydantic Models ──────────────────────────────────────────────────

class CallbackCreateRequest(BaseModel):
    """Request model for creating a new callback."""
    model_config = ConfigDict(extra="allow")
    
    customer_name: str = Field(..., description="Customer's name")
    wa_id: str = Field(..., description="WhatsApp user ID")
    callback_type: str = Field(default="general", description="Type of callback")
    purpose: str = Field(default="", description="Purpose of the callback")
    customer_email: Optional[str] = Field(default=None, description="Customer's email")
    customer_phone: Optional[str] = Field(default=None, description="Customer's phone number")
    priority: str = Field(default="medium", description="Priority level")
    preferred_date: Optional[str] = Field(default=None, description="Preferred date (YYYY-MM-DD)")
    preferred_time: Optional[str] = Field(default=None, description="Preferred time (HH:MM or HH:MM-HH:MM)")
    additional_info: str = Field(default="", description="Additional information from customer")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class CallbackUpdateRequest(BaseModel):
    """Request model for updating a callback."""
    model_config = ConfigDict(extra="allow")
    
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    callback_type: Optional[str] = None
    purpose: Optional[str] = None
    priority: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    additional_info: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ScheduleCallbackRequest(BaseModel):
    """Request model for scheduling a callback with Google Meet."""
    model_config = ConfigDict(extra="allow")
    
    agent_id: str = Field(..., description="Agent ID to assign")
    agent_name: str = Field(..., description="Agent name")
    start_time: str = Field(..., description="Start time (ISO format)")
    end_time: str = Field(..., description="End time (ISO format)")
    time_slot_id: Optional[str] = Field(default=None, description="Time slot ID")
    send_notifications: bool = Field(default=True, description="Send notifications to all parties")


class CancelCallbackRequest(BaseModel):
    """Request model for cancelling a callback."""
    model_config = ConfigDict(extra="allow")
    
    reason: str = Field(default="", description="Reason for cancellation")
    notify_customer: bool = Field(default=True, description="Notify customer about cancellation")
    notify_agent: bool = Field(default=True, description="Notify assigned agent")
    cancellation_notes: Optional[str] = None


class CompleteCallbackRequest(BaseModel):
    """Request model for completing a callback."""
    model_config = ConfigDict(extra="allow")
    
    meeting_notes: str = Field(default="", description="Meeting notes/summary")
    outcome: str = Field(default="success", description="Meeting outcome")
    follow_up_required: bool = Field(default=False, description="Follow-up required")
    follow_up_notes: Optional[str] = None


class TimeSlotRequest(BaseModel):
    """Request model for getting available time slots."""
    date: str = Field(..., description="Date to get slots for (YYYY-MM-DD)")
    agent_id: Optional[str] = Field(default=None, description="Filter by agent ID")
    duration_minutes: Optional[int] = Field(default=None, description="Slot duration in minutes")


class RescheduleCallbackRequest(BaseModel):
    """Request model for rescheduling a callback."""
    model_config = ConfigDict(extra="allow")
    
    new_start_time: str = Field(..., description="New start time (ISO format)")
    new_end_time: str = Field(..., description="New end time (ISO format)")
    new_date: Optional[str] = Field(default=None, description="New date (YYYY-MM-DD)")
    reason: str = Field(default="", description="Reason for rescheduling")
    notify_participants: bool = Field(default=True, description="Notify all participants")


# ── Database Functions ────────────────────────────────────────────────

def _save_callback_to_db(conn, callback_request: CallbackRequest) -> bool:
    """Save callback request to database."""
    try:
        # Convert callback to dict for JSON storage
        callback_data = json.dumps(callback_request.to_dict())
        
        # Check if callback already exists
        existing = conn.execute(
            "SELECT id FROM callbacks WHERE id = ?", 
            (callback_request.id,)
        ).fetchone()
        
        if existing:
            # Update existing callback
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
                    datetime.now(timezone.utc).isoformat(),
                    callback_request.id
                )
            )
        else:
            # Insert new callback
            conn.execute(
                """INSERT INTO callbacks 
                   (id, tenant_id, wa_id, data, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    callback_request.id,
                    callback_request.tenant_id,
                    callback_request.wa_id,
                    callback_data,
                    callback_request.status,
                    callback_request.created_at,
                    callback_request.updated_at
                )
            )
        return True
    except Exception as e:
        logger.error(f"Failed to save callback to DB: {e}")
        return False


def _get_callback_from_db(conn, callback_id: str) -> Optional[CallbackRequest]:
    """Retrieve callback request from database."""
    try:
        row = conn.execute(
            "SELECT data FROM callbacks WHERE id = ?",
            (callback_id,)
        ).fetchone()
        
        if row and row["data"]:
            data = json.loads(row["data"])
            return CallbackRequest(**data)
        return None
    except Exception as e:
        logger.error(f"Failed to get callback from DB: {e}")
        return None


def _list_callbacks_from_db(
    conn, 
    tenant_id: str, 
    status: Optional[str] = None,
    wa_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[CallbackRequest]:
    """List callback requests from database."""
    try:
        query = """
            SELECT data FROM callbacks 
            WHERE tenant_id = ?
        """
        params = [tenant_id]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if wa_id:
            query += " AND wa_id = ?"
            params.append(wa_id)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        
        callbacks = []
        for row in rows:
            if row and row["data"]:
                data = json.loads(row["data"])
                callbacks.append(CallbackRequest(**data))
        
        return callbacks
    except Exception as e:
        logger.error(f"Failed to list callbacks from DB: {e}")
        return []


def _init_callback_tables(conn):
    """Initialize callback-related database tables."""
    try:
        # Main callbacks table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS callbacks (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                wa_id TEXT NOT NULL,
                data TEXT NOT NULL,  -- JSON-serialized CallbackRequest
                status TEXT NOT NULL DEFAULT 'pending',
                scheduled_start_time TEXT,
                scheduled_end_time TEXT,
                meet_link TEXT,
                calendar_event_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """)
        
        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS ix_callbacks_tenant ON callbacks(tenant_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_callbacks_wa_id ON callbacks(wa_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_callbacks_status ON callbacks(status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_callbacks_scheduled ON callbacks(scheduled_start_time)")
        
        # Callback summaries table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS callback_summaries (
                id TEXT PRIMARY KEY,
                callback_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                meeting_notes TEXT,
                outcome TEXT,
                follow_up_required BOOLEAN DEFAULT FALSE,
                follow_up_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                FOREIGN KEY (callback_id) REFERENCES callbacks(id)
            )
        """)
        
        # Agent availability table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                date TEXT NOT NULL,  -- YYYY-MM-DD
                start_time TEXT NOT NULL,  -- HH:MM
                end_time TEXT NOT NULL,  -- HH:MM
                is_available BOOLEAN DEFAULT TRUE,
                UNIQUE(tenant_id, agent_id, date, start_time, end_time),
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
        """)
        
        logger.info("Callback database tables initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize callback tables: {e}")
        return False


# ── Background Tasks ──────────────────────────────────────────────────

async def _send_callback_confirmation_background(
    callback_request: CallbackRequest,
    current_admin: Optional[dict] = None
):
    """Send confirmation notifications in background."""
    try:
        # Format and send customer confirmation
        customer_message = notification_service.format_callback_confirmation(callback_request)
        if callback_request.wa_id:
            await notification_service.send_whatsapp_notification(
                phone_number=callback_request.wa_id,
                message=customer_message
            )
        
        # Send to customer email if available
        if callback_request.customer_email:
            subject = f"Callback Confirmed: {callback_request.id}"
            await notification_service.send_email_notification(
                to_email=callback_request.customer_email,
                subject=subject,
                body=customer_message
            )
        
        # Format and send agent notification if assigned
        if callback_request.assigned_agent_id:
            agent_message = notification_service.format_agent_notification(callback_request)
            # In production, this would be sent to the agent's configured contact method
            logger.info(f"Agent notification: {agent_message}")
        
        logger.info(f"Confirmation notifications sent for callback {callback_request.id}")
    except Exception as e:
        logger.error(f"Failed to send confirmation notifications: {e}")


async def _send_cancellation_notifications_background(
    callback_request: CallbackRequest,
    reason: str,
    current_admin: Optional[dict] = None
):
    """Send cancellation notifications in background."""
    try:
        # Format and send customer cancellation notification
        customer_message = notification_service.format_cancellation_message(callback_request, reason)
        if callback_request.wa_id:
            await notification_service.send_whatsapp_notification(
                phone_number=callback_request.wa_id,
                message=customer_message
            )
        
        # Send to customer email if available
        if callback_request.customer_email:
            subject = f"Callback Cancelled: {callback_request.id}"
            await notification_service.send_email_notification(
                to_email=callback_request.customer_email,
                subject=subject,
                body=customer_message
            )
        
        logger.info(f"Cancellation notifications sent for callback {callback_request.id}")
    except Exception as e:
        logger.error(f"Failed to send cancellation notifications: {e}")


async def _send_reminder_notifications_background(
    callback_request: CallbackRequest
):
    """Send reminder notifications in background."""
    try:
        # Send 24-hour reminder
        message_24h = notification_service.format_reminder_message(callback_request, 1440)
        if callback_request.wa_id:
            await notification_service.send_whatsapp_notification(
                phone_number=callback_request.wa_id,
                message=message_24h
            )
        
        if callback_request.customer_email:
            await notification_service.send_email_notification(
                to_email=callback_request.customer_email,
                subject=f"Reminder: Callback Tomorrow - {callback_request.id}",
                body=message_24h
            )
        
        # Send 15-minute reminder
        message_15min = notification_service.format_reminder_message(callback_request, 15)
        if callback_request.wa_id:
            await notification_service.send_whatsapp_notification(
                phone_number=callback_request.wa_id,
                message=message_15min
            )
        
        logger.info(f"Reminder notifications sent for callback {callback_request.id}")
    except Exception as e:
        logger.error(f"Failed to send reminder notifications: {e}")


# ── Routes ───────────────────────────────────────────────────────────

@router.post("/{tenant_id}/callbacks")
async def create_callback(
    tenant_id: str,
    body: CallbackCreateRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_admin: dict = Depends(require_tenant_access()),
):
    """Create a new callback request.
    
    This endpoint is called when a user requests a callback through WhatsApp.
    It creates the initial callback request and can immediately schedule it
    if all required information is provided.
    """
    # Validate callback type
    valid_types = [t.value for t in CallbackType]
    if body.callback_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid callback type. Must be one of: {valid_types}"
        )
    
    # Validate priority
    valid_priorities = [p.value for p in Priority]
    if body.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Must be one of: {valid_priorities}"
        )
    
    # Create callback request
    callback_request = callback_service.create_callback_request(
        tenant_id=tenant_id,
        wa_id=body.wa_id,
        customer_name=body.customer_name,
        callback_type=body.callback_type,
        purpose=body.purpose,
        preferred_date=body.preferred_date,
        preferred_time=body.preferred_time,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        priority=body.priority,
        additional_info=body.additional_info,
        metadata=body.metadata
    )
    
    # Save to database
    with get_db_context() as conn:
        _init_callback_tables(conn)
        if _save_callback_to_db(conn, callback_request):
            record_admin_audit_event(
                conn,
                action="callback_created",
                actor=current_admin,
                resource_type="callback",
                resource_id=callback_request.id,
                tenant_id=tenant_id,
                details={
                    "wa_id": callback_request.wa_id,
                    "customer_name": callback_request.customer_name,
                    "callback_type": callback_request.callback_type,
                    "priority": callback_request.priority,
                    "status": callback_request.status,
                    "preferred_date": callback_request.preferred_date,
                    "preferred_time": callback_request.preferred_time,
                },
            )
    
    # Send confirmation notifications in background
    if callback_request.status == CallbackStatus.CONFIRMED.value:
        background_tasks.add_task(
            _send_callback_confirmation_background,
            callback_request,
            current_admin
        )
    
    logger.info(f"Callback created: {callback_request.id} for tenant {tenant_id}")
    
    return {
        "ok": True,
        "callback_id": callback_request.id,
        "status": callback_request.status,
        "message": "Callback request received successfully"
    }


@router.get("/{tenant_id}/callbacks")
async def list_callbacks(
    tenant_id: str,
    status: Optional[str] = None,
    wa_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_admin: dict = Depends(require_tenant_access()),
):
    """List all callback requests for a tenant with filters."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        
        # Get callbacks from DB
        callbacks = _list_callbacks_from_db(conn, tenant_id, status, wa_id, limit, offset)
        
        # Apply additional filters (agent_id, date_from, date_to)
        if agent_id:
            callbacks = [cb for cb in callbacks if cb.assigned_agent_id == agent_id]
        
        if date_from:
            try:
                from dateutil.parser import parse
                from_parts = date_from.split("T")
                from_date = from_parts[0] if len(from_parts) > 0 else date_from
                
                if len(from_parts) > 1:
                    from_time = from_parts[1].split(".")[0] if "." in from_parts[1] else from_parts[1]
                    cut_off = parse(f"{from_date}T{from_time}")
                else:
                    cut_off = parse(f"{from_date}T00:00:00")
                
                callbacks = [
                    cb for cb in callbacks 
                    if parse(cb.created_at).replace(tzinfo=None) >= cut_off.replace(tzinfo=None)
                ]
            except Exception as e:
                logger.warning(f"Invalid date_from filter: {e}")
        
        if date_to:
            try:
                from dateutil.parser import parse
                to_parts = date_to.split("T")
                to_date = to_parts[0] if len(to_parts) > 0 else date_to
                
                if len(to_parts) > 1:
                    to_time = to_parts[1].split(".")[0] if "." in to_parts[1] else to_parts[1]
                    cut_off = parse(f"{to_date}T{to_time}")
                else:
                    cut_off = parse(f"{to_date}T23:59:59")
                
                callbacks = [
                    cb for cb in callbacks 
                    if parse(cb.created_at).replace(tzinfo=None) <= cut_off.replace(tzinfo=None)
                ]
            except Exception as e:
                logger.warning(f"Invalid date_to filter: {e}")
        
        # Sort by creation date (newest first)
        callbacks.sort(key=lambda cb: cb.created_at, reverse=True)
    
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "callbacks": [cb.to_dict() for cb in callbacks],
        "total_count": len(callbacks),
        "limit": limit,
        "offset": offset
    }


@router.get("/{tenant_id}/callbacks/{callback_id}")
async def get_callback(
    tenant_id: str,
    callback_id: str,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Get detailed information about a specific callback request."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        callback_request = _get_callback_from_db(conn, callback_id)
        
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
    
    return {
        "ok": True,
        "callback": callback_request.to_dict()
    }


@router.put("/{tenant_id}/callbacks/{callback_id}")
async def update_callback(
    tenant_id: str,
    callback_id: str,
    body: CallbackUpdateRequest,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Update a callback request."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        callback_request = _get_callback_from_db(conn, callback_id)
        
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
        
        # Apply updates
        if body.customer_name:
            callback_request.customer_name = body.customer_name
        if body.customer_email:
            callback_request.customer_email = body.customer_email
        if body.customer_phone:
            callback_request.customer_phone = body.customer_phone
        if body.callback_type:
            callback_request.callback_type = body.callback_type
        if body.purpose:
            callback_request.purpose = body.purpose
        if body.priority:
            callback_request.priority = body.priority
        if body.preferred_date:
            callback_request.preferred_date = body.preferred_date
        if body.preferred_time:
            callback_request.preferred_time = body.preferred_time
        if body.additional_info:
            callback_request.additional_info = body.additional_info
        if body.assigned_agent_id:
            callback_request.assigned_agent_id = body.assigned_agent_id
        if body.assigned_agent_name:
            callback_request.assigned_agent_name = body.assigned_agent_name
        if body.status:
            callback_request.status = body.status
        if body.metadata:
            callback_request.metadata = body.metadata
            
        callback_request.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Save updated callback
        if _save_callback_to_db(conn, callback_request):
            record_admin_audit_event(
                conn,
                action="callback_updated",
                actor=current_admin,
                resource_type="callback",
                resource_id=callback_id,
                tenant_id=tenant_id,
                details={
                    "status": callback_request.status,
                    "assigned_agent_id": callback_request.assigned_agent_id,
                    "changes": {k: v for k, v in body.model_dump().items() if v is not None}
                },
            )
    
    logger.info(f"Callback updated: {callback_id}")
    
    return {
        "ok": True,
        "callback_id": callback_id,
        "status": callback_request.status,
        "message": "Callback updated successfully"
    }


@router.post("/{tenant_id}/callbacks/{callback_id}/schedule")
async def schedule_callback(
    tenant_id: str,
    callback_id: str,
    body: ScheduleCallbackRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_admin: dict = Depends(require_tenant_access()),
):
    """Schedule a callback by creating Google Meet and adding to calendar.
    
    This endpoint:
    1. Creates Google Calendar event with Google Meet
    2. Updates callback with event details
    3. Sends notifications to all parties
    """
    with get_db_context() as conn:
        _init_callback_tables(conn)
        callback_request = _get_callback_from_db(conn, callback_id)
        
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
        
        if callback_request.status in [CallbackStatus.SCHEDULED.value, CallbackStatus.COMPLETED.value]:
            raise HTTPException(
                status_code=400,
                detail=f"Callback is already {callback_request.status}"
            )
    
    # Create Google Meet event
    meet_result = await google_meet_service.create_meeting(
        calendar_id="primary",
        title=f"Callback: {callback_request.customer_name} - {callback_request.callback_type}",
        description=f"""
        Callback requested via WhatsApp
        Customer: {callback_request.customer_name}
        WhatsApp ID: {callback_request.wa_id}
        Purpose: {callback_request.purpose or 'Not specified'}
        Type: {callback_request.callback_type}
        Priority: {callback_request.priority}
        Additional Info: {callback_request.additional_info or 'None'}
        """,
        start_time=body.start_time,
        end_time=body.end_time,
        attendees=[
            {"email": callback_request.customer_email, "displayName": callback_request.customer_name}
        ] if callback_request.customer_email else [],
        timezone=callback_request.timezone
    )
    
    if not meet_result.get("ok"):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create Google Meet: {meet_result.get('error', 'Unknown error')}"
        )
    
    # Update callback with meeting details
    callback_request = callback_service.schedule_callback_with_meet(
        callback_request=callback_request,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        start_time=body.start_time,
        end_time=body.end_time,
        calendar_event_id=meet_result.get("event_id", ""),
        meet_link=meet_result.get("meet_link", "")
    )
    
    # Save updated callback
    with get_db_context() as conn:
        if _save_callback_to_db(conn, callback_request):
            record_admin_audit_event(
                conn,
                action="callback_scheduled",
                actor=current_admin,
                resource_type="callback",
                resource_id=callback_id,
                tenant_id=tenant_id,
                details={
                    "meet_link": callback_request.meet_link,
                    "calendar_event_id": callback_request.calendar_event_id,
                    "agent_id": body.agent_id,
                    "agent_name": body.agent_name,
                    "start_time": body.start_time,
                    "end_time": body.end_time
                },
            )
    
    # Send notifications in background
    if body.send_notifications:
        background_tasks.add_task(
            _send_callback_confirmation_background,
            callback_request,
            current_admin
        )
    
    logger.info(f"Callback scheduled with Meet: {callback_id}")
    
    return {
        "ok": True,
        "callback_id": callback_id,
        "meet_link": callback_request.meet_link,
        "calendar_event_id": callback_request.calendar_event_id,
        "status": callback_request.status,
        "start_time": callback_request.scheduled_start_time,
        "end_time": callback_request.scheduled_end_time,
        "agent": {
            "id": body.agent_id,
            "name": body.agent_name
        },
        "message": "Callback scheduled successfully with Google Meet"
    }


@router.post("/{tenant_id}/callbacks/{callback_id}/cancel")
async def cancel_callback(
    tenant_id: str,
    callback_id: str,
    body: CancelCallbackRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_admin: dict = Depends(require_tenant_access()),
):
    """Cancel a callback request."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        callback_request = _get_callback_from_db(conn, callback_id)
        
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
        
        if callback_request.status in [CallbackStatus.CANCELLED.value, CallbackStatus.COMPLETED.value]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel a callback that is already {callback_request.status}"
            )
        
        # Update callback status
        callback_request.status = CallbackStatus.CANCELLED.value
        callback_request.updated_at = datetime.now(timezone.utc).isoformat()
        
        if _save_callback_to_db(conn, callback_request):
            record_admin_audit_event(
                conn,
                action="callback_cancelled",
                actor=current_admin,
                resource_type="callback",
                resource_id=callback_id,
                tenant_id=tenant_id,
                details={"reason": body.reason, "notes": body.cancellation_notes},
            )
    
    # Send cancellation notifications in background
    if body.notify_customer or body.notify_agent:
        background_tasks.add_task(
            _send_cancellation_notifications_background,
            callback_request,
            body.reason,
            current_admin
        )
    
    # Clean up Google Calendar event if it exists
    if callback_request.calendar_event_id:
        try:
            await google_meet_service.delete_event(
                calendar_id="primary",
                event_id=callback_request.calendar_event_id
            )
            logger.info(f"Calendar event deleted: {callback_request.calendar_event_id}")
        except Exception as e:
            logger.warning(f"Failed to delete calendar event: {e}")
    
    logger.info(f"Callback cancelled: {callback_id}")
    
    return {
        "ok": True,
        "callback_id": callback_id,
        "status": callback_request.status,
        "message": "Callback cancelled successfully"
    }


@router.post("/{tenant_id}/callbacks/{callback_id}/complete")
async def complete_callback(
    tenant_id: str,
    callback_id: str,
    body: CompleteCallbackRequest,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Mark a callback as completed and save summary."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        callback_request = _get_callback_from_db(conn, callback_id)
        
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
        
        if callback_request.status == CallbackStatus.COMPLETED.value:
            raise HTTPException(
                status_code=400,
                detail="Callback is already completed"
            )
        
        # Mark as completed
        callback_request.status = CallbackStatus.COMPLETED.value
        callback_request.updated_at = datetime.now(timezone.utc).isoformat()
        
        if _save_callback_to_db(conn, callback_request):
            # Save meeting summary
            conn.execute(
                """INSERT INTO callback_summaries 
                   (id, callback_id, tenant_id, meeting_notes, outcome, follow_up_required, follow_up_notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    secrets.token_hex(12),
                    callback_id,
                    tenant_id,
                    body.meeting_notes,
                    body.outcome,
                    1 if body.follow_up_required else 0,
                    body.follow_up_notes
                )
            )
            
            record_admin_audit_event(
                conn,
                action="callback_completed",
                actor=current_admin,
                resource_type="callback",
                resource_id=callback_id,
                tenant_id=tenant_id,
                details={
                    "outcome": body.outcome,
                    "follow_up_required": body.follow_up_required,
                    "meeting_notes_length": len(body.meeting_notes or "")
                },
            )
    
    logger.info(f"Callback completed: {callback_id}")
    
    return {
        "ok": True,
        "callback_id": callback_id,
        "status": callback_request.status,
        "message": "Callback marked as completed",
        "summary": {
            "meeting_notes": body.meeting_notes,
            "outcome": body.outcome,
            "follow_up_required": body.follow_up_required,
            "follow_up_notes": body.follow_up_notes
        }
    }


@router.get("/{tenant_id}/callbacks/{callback_id}/summary")
async def get_callback_summary(
    tenant_id: str,
    callback_id: str,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Get summary of a completed callback meeting."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        
        # Get callback
        callback_request = _get_callback_from_db(conn, callback_id)
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
        
        # Get summary
        summary_row = conn.execute(
            """SELECT * FROM callback_summaries 
               WHERE callback_id = ? ORDER BY created_at DESC LIMIT 1""",
            (callback_id,)
        ).fetchone()
        
        callback_summary = None
        if summary_row:
            callback_summary = dict(summary_row)
        
        # Create comprehensive summary
        summary = callback_service.create_meeting_summary(
            callback_request=callback_request,
            meeting_notes=callback_summary.get("meeting_notes", "") if callback_summary else ""
        )
        
        if callback_summary:
            summary.update({
                "outcome": callback_summary.get("outcome"),
                "follow_up_required": bool(callback_summary.get("follow_up_required")),
                "follow_up_notes": callback_summary.get("follow_up_notes"),
                "summary_created_at": callback_summary.get("created_at")
            })
    
    return {
        "ok": True,
        "callback_id": callback_id,
        "summary": summary
    }


@router.get("/{tenant_id}/callbacks/time-slots")
async def get_time_slots(
    tenant_id: str,
    date: str,
    agent_id: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Get available time slots for scheduling callbacks."""
    try:
        from dateutil.parser import parse
        parse(date)  # Validate date format
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # For now, return generic time slots
    # In production, this would check agent availability, calendar conflicts, etc.
    default_duration = duration_minutes or 30
    
    time_slots = []
    start_hour = 9
    end_hour = 18
    
    for hour in range(start_hour, end_hour):
        for minute in [0, 30] if default_duration <= 30 else [0]:
            start = f"{hour:02d}:{minute:02d}"
            end_hour_offset = hour + (default_duration // 60)
            end_minute = (minute + (default_duration % 60)) % 60
            if end_minute == 0:
                end_hour_offset += 1
            end = f"{end_hour_offset:02d}:{end_minute:02d}"
            
            if end_hour_offset <= end_hour:
                slot_id = f"{date}_{start}_{end}"
                time_slots.append({
                    "id": slot_id,
                    "date": date,
                    "start_time": start,
                    "end_time": end,
                    "display_text": f"{start} - {end}",
                    "available": True,
                    "duration_minutes": default_duration
                })
    
    return {
        "ok": True,
        "date": date,
        "agent_id": agent_id,
        "time_slots": time_slots,
        "total_available": len(time_slots)
    }


@router.post("/{tenant_id}/callbacks/{callback_id}/reschedule")
async def reschedule_callback(
    tenant_id: str,
    callback_id: str,
    body: RescheduleCallbackRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_admin: dict = Depends(require_tenant_access()),
):
    """Reschedule an existing callback."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        callback_request = _get_callback_from_db(conn, callback_id)
        
        if not callback_request:
            raise HTTPException(status_code=404, detail="Callback not found")
        
        if callback_request.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, 
                detail="Callback does not belong to the specified tenant"
            )
        
        if callback_request.status in [CallbackStatus.CANCELLED.value, CallbackStatus.COMPLETED.value]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reschedule a callback that is {callback_request.status}"
            )
        
        # Delete old calendar event if it exists
        if callback_request.calendar_event_id:
            try:
                await google_meet_service.delete_event(
                    calendar_id="primary",
                    event_id=callback_request.calendar_event_id
                )
            except Exception as e:
                logger.warning(f"Failed to delete old calendar event: {e}")
        
        # Create new Google Meet event
        meet_result = await google_meet_service.create_meeting(
            calendar_id="primary",
            title=f"Callback (Rescheduled): {callback_request.customer_name} - {callback_request.callback_type}",
            description=f"""
            Rescheduled Callback (Original: {callback_request.scheduled_start_time or 'N/A'})
            Customer: {callback_request.customer_name}
            WhatsApp ID: {callback_request.wa_id}
            Purpose: {callback_request.purpose or 'Not specified'}
            Type: {callback_request.callback_type}
            Priority: {callback_request.priority}
            Additional Info: {callback_request.additional_info or 'None'}
            Reschedule Reason: {body.reason or 'Not specified'}
            """,
            start_time=body.new_start_time,
            end_time=body.new_end_time,
            attendees=[
                {"email": callback_request.customer_email, "displayName": callback_request.customer_name}
            ] if callback_request.customer_email else [],
            timezone=callback_request.timezone
        )
        
        if not meet_result.get("ok"):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create Google Meet for rescheduled callback: {meet_result.get('error', 'Unknown error')}"
            )
        
        # Update callback with new meeting details
        callback_request = callback_service.schedule_callback_with_meet(
            callback_request=callback_request,
            agent_id=callback_request.assigned_agent_id or "",
            agent_name=callback_request.assigned_agent_name or "",
            start_time=body.new_start_time,
            end_time=body.new_end_time,
            calendar_event_id=meet_result.get("event_id", ""),
            meet_link=meet_result.get("meet_link", "")
        )
        
        # Save updated callback
        if _save_callback_to_db(conn, callback_request):
            record_admin_audit_event(
                conn,
                action="callback_rescheduled",
                actor=current_admin,
                resource_type="callback",
                resource_id=callback_id,
                tenant_id=tenant_id,
                details={
                    "old_start_time": callback_request.scheduled_start_time,
                    "old_end_time": callback_request.scheduled_end_time,
                    "new_start_time": body.new_start_time,
                    "new_end_time": body.new_end_time,
                    "new_meet_link": callback_request.meet_link,
                    "reason": body.reason
                },
            )
    
    # Send new notifications in background
    if body.notify_participants:
        background_tasks.add_task(
            _send_callback_confirmation_background,
            callback_request,
            current_admin
        )
    
    logger.info(f"Callback rescheduled: {callback_id}")
    
    return {
        "ok": True,
        "callback_id": callback_id,
        "meet_link": callback_request.meet_link,
        "calendar_event_id": callback_request.calendar_event_id,
        "new_start_time": callback_request.scheduled_start_time,
        "new_end_time": callback_request.scheduled_end_time,
        "message": "Callback rescheduled successfully"
    }


@router.get("/{tenant_id}/callbacks/upcoming")
async def list_upcoming_callbacks(
    tenant_id: str,
    days_ahead: int = 7,
    limit: int = 50,
    current_admin: dict = Depends(require_tenant_access()),
):
    """List upcoming callbacks that need reminders or attention."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        
        from dateutil.parser import parse
        cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
        
        rows = conn.execute(
            """SELECT data FROM callbacks 
               WHERE tenant_id = ? 
               AND status IN ('pending', 'confirmed', 'scheduled')
               AND scheduled_start_time <= ?
               ORDER BY scheduled_start_time ASC LIMIT ?""",
            (tenant_id, cutoff_date, limit)
        ).fetchall()
        
        upcoming = []
        for row in rows:
            if row and row["data"]:
                data = json.loads(row["data"])
                callback_request = CallbackRequest(**data)
                
                if callback_request.scheduled_start_time:
                    start_time = parse(callback_request.scheduled_start_time)
                    now = datetime.now(timezone.utc)
                    
                    # Convert to same timezone for comparison
                    if start_time.tzinfo:
                        now = now.replace(tzinfo=start_time.tzinfo)
                    
                    if start_time > now:
                        upcoming.append(callback_request)
    
    # Sort by scheduled start time
    upcoming.sort(key=lambda cb: cb.scheduled_start_time or "")
    
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "upcoming_callbacks": [cb.to_dict() for cb in upcoming],
        "total": len(upcoming),
        "days_ahead": days_ahead
    }


@router.post("/{tenant_id}/callbacks/meet-test")
async def test_google_meet(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Test Google Meet integration."""
    test_event = await google_meet_service.create_meeting(
        calendar_id="primary",
        title="Test Meeting - Chatbot2 Callback System",
        description="This is a test meeting to verify Google Meet integration.",
        start_time=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        end_time=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        timezone="Asia/Kolkata"
    )
    
    if not test_event.get("ok"):
        raise HTTPException(
            status_code=500,
            detail=f"Google Meet integration test failed: {test_event.get('error', 'Unknown error')}"
        )
    
    return {
        "ok": True,
        "test_successful": True,
        "event_id": test_event.get("event_id"),
        "meet_link": test_event.get("meet_link"),
        "message": "Google Meet integration is working correctly"
    }


# ── Agent Availability Management ──────────────────────────────────────

@router.post("/{tenant_id}/agents/{agent_id}/availability")
async def save_agent_availability(
    tenant_id: str,
    agent_id: str,
    date: str,
    start_time: str,
    end_time: str,
    is_available: bool = True,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Save agent availability for a specific date and time."""
    try:
        # Validate date format
        from dateutil.parser import parse
        parse(date)
        
        # Validate time format (HH:MM)
        if not (len(start_time) == 5 and start_time[2] == ':') or \
           not (len(end_time) == 5 and end_time[2] == ':'):
            raise HTTPException(status_code=400, detail="Time must be in HH:MM format")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date or time format")
    
    with get_db_context() as conn:
        _init_callback_tables(conn)
        
        agent_name = ""  # Could be retrieved from agent table in real implementation
        
        conn.execute(
            """INSERT INTO agent_availability 
               (tenant_id, agent_id, agent_name, date, start_time, end_time, is_available)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, agent_id, date, start_time, end_time) DO UPDATE SET
                 is_available = excluded.is_available,
                 agent_name = excluded.agent_name""",
            (
                tenant_id,
                agent_id,
                agent_name,
                date,
                start_time,
                end_time,
                1 if is_available else 0
            )
        )
        
        record_admin_audit_event(
            conn,
            action="agent_availability_saved",
            actor=current_admin,
            resource_type="agent_availability",
            resource_id=f"{agent_id}/{date}",
            tenant_id=tenant_id,
            details={
                "agent_id": agent_id,
                "date": date,
                "time_range": f"{start_time}-{end_time}",
                "is_available": is_available
            },
        )
    
    return {
        "ok": True,
        "agent_id": agent_id,
        "date": date,
        "time": f"{start_time}-{end_time}",
        "is_available": is_available,
        "message": "Agent availability saved successfully"
    }


@router.get("/{tenant_id}/agents/{agent_id}/availability")
async def get_agent_availability(
    tenant_id: str,
    agent_id: str,
    date: str,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Get agent availability for a specific date."""
    try:
        from dateutil.parser import parse
        parse(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    with get_db_context() as conn:
        _init_callback_tables(conn)
        
        rows = conn.execute(
            """SELECT * FROM agent_availability 
               WHERE tenant_id = ? AND agent_id = ? AND date = ?
               ORDER BY start_time ASC""",
            (tenant_id, agent_id, date)
        ).fetchall()
        
        availability = []
        for row in rows:
            availability.append({
                "id": row["id"],
                "agent_id": row["agent_id"],
                "agent_name": row["agent_name"],
                "date": row["date"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "is_available": bool(row["is_available"])
            })
    
    return {
        "ok": True,
        "agent_id": agent_id,
        "date": date,
        "availability": availability
    }


# ── Statistics and Analytics ────────────────────────────────────────────

@router.get("/{tenant_id}/callbacks/stats")
async def get_callback_stats(
    tenant_id: str,
    days: int = 30,
    current_admin: dict = Depends(require_tenant_access()),
):
    """Get callback statistics for a tenant."""
    with get_db_context() as conn:
        _init_callback_tables(conn)
        
        from dateutil.parser import parse
        
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Get counts by status
        status_counts = {}
        all_statuses = [s.value for s in CallbackStatus]
        
        for status in all_statuses:
            row = conn.execute(
                """SELECT COUNT(*) as count FROM callbacks 
                   WHERE tenant_id = ? AND status = ? 
                   AND created_at >= ?""",
                (tenant_id, status, start_date.isoformat())
            ).fetchone()
            
            status_counts[status] = row["count"] if row else 0
        
        # Get callback types distribution
        type_counts = {}
        valid_types = [t.value for t in CallbackType]
        
        for cb_type in valid_types:
            row = conn.execute(
                """SELECT COUNT(*) as count FROM callbacks 
                   WHERE tenant_id = ? AND data LIKE ?""",
                (tenant_id, f'%"callback_type":"{cb_type}"%')
            ).fetchone()
            
            type_counts[cb_type] = row["count"] if row else 0
        
        # Get daily callback counts
        daily_counts = []
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            row = conn.execute(
                """SELECT COUNT(*) as count FROM callbacks 
                   WHERE tenant_id = ? AND date(created_at) = ?""",
                (tenant_id, date_str)
            ).fetchone()
            
            daily_counts.append({
                "date": date_str,
                "count": row["count"] if row else 0
            })
            
            current_date += timedelta(days=1)
        
        # Get average resolution time
        avg_resolution = None
        row = conn.execute(
            """SELECT AVG(julianday(updated_at) - julianday(created_at)) as days
               FROM callbacks 
               WHERE tenant_id = ? AND status = ? AND scheduled_start_time IS NOT NULL""",
            (tenant_id, CallbackStatus.COMPLETED.value)
        ).fetchone()
        
        if row and row["days"]:
            avg_resolution = float(row["days"])
    
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "period": {
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        },
        "total_callbacks": sum(status_counts.values()),
        "status_distribution": status_counts,
        "type_distribution": type_counts,
        "daily_counts": daily_counts,
        "average_resolution_time_days": avg_resolution,
        "completion_rate": (
            (status_counts.get(CallbackStatus.COMPLETED.value, 0) / max(sum(status_counts.values()), 1)) * 100
        ),
        "cancelation_rate": (
            (status_counts.get(CallbackStatus.CANCELLED.value, 0) / max(sum(status_counts.values()), 1)) * 100
        )
    }