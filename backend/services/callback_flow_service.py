"""Callback Flow Service for WhatsApp Chatbot Integration.

This service provides the conversational flow for callback booking through WhatsApp:

Flow States:
1. INITIAL: User expresses interest in booking a callback
2. INFO_COLLECTION: Collect user details (name, purpose, etc.)
3. TYPE_SELECTION: User selects callback type
4. TIME_SELECTION: User selects preferred date/time
5. CONFIRMATION: Show summary and ask for confirmation
6. SCHEDULING: Create Google Meet and save to database
7. NOTIFICATION: Send confirmations to user and agent
8. COMPLETED: Callback process finished

The service handles:
- Managing conversation state in WhatsApp
- Validating user input
- Integrating with Google Meet
- Sending notifications
- Handling errors and edge cases (out of hours, no agents available, etc.)
"""

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, asdict, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.services.callback_service import (
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


class CallbackFlowState(Enum):
    """States in the callback booking flow."""
    # Initial state - user has shown interest in callback
    INITIAL = "initial"
    
    # Collecting user information
    COLLECTING_NAME = "collecting_name"
    COLLECTING_EMAIL = "collecting_email"
    COLLECTING_PHONE = "collecting_phone"
    COLLECTING_PURPOSE = "collecting_purpose"
    
    # Selecting callback type
    SELECTING_TYPE = "selecting_type"
    
    # Selecting date and time
    SELECTING_DATE = "selecting_date"
    SELECTING_TIME = "selecting_time"
    
    # Priority selection
    SELECTING_PRIORITY = "selecting_priority"
    
    # Confirmation before submission
    CONFIRMATION = "confirmation"
    
    # Completed
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class CallbackFlowContext:
    """Context for a callback booking flow conversation."""
    # Conversation metadata
    wa_id: str
    tenant_id: str
    session_id: str
    current_state: str
    
    # Collected user data
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    purpose: str = ""
    callback_type: str = "general"
    priority: str = "medium"
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    
    # System/orchestration data
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attempts: Dict[str, int] = field(default_factory=dict)
    last_message: Optional[str] = None
    
    # Final result
    callback_id: Optional[str] = None
    meet_link: Optional[str] = None
    calendar_event_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def is_complete(self) -> bool:
        return self.current_state in [CallbackFlowState.COMPLETED.value, CallbackFlowState.CANCELLED.value]
    
    def get_missing_required_fields(self) -> List[str]:
        """Get list of required fields that are missing."""
        missing = []
        if not self.user_name:
            missing.append("user_name")
        if self.current_state == CallbackFlowState.COLLECTING_NAME.value and not self.user_name:
            missing.append("user_name")
        return missing
    
    def get_collected_data_summary(self) -> str:
        """Get a summary of collected data for confirmation."""
        lines = []
        lines.append(f"Name: {self.user_name or 'Not provided'}")
        lines.append(f"Type: {self.callback_type or 'general'}")
        lines.append(f"Priority: {self.priority or 'medium'}")
        if self.purpose:
            lines.append(f"Purpose: {self.purpose}")
        if self.preferred_date:
            lines.append(f"Preferred Date: {self.preferred_date}")
        if self.preferred_time:
            lines.append(f"Preferred Time: {self.preferred_time}")
        
        return "\n".join(lines)


class CallbackFlowService:
    """Service for managing callback booking flows in WhatsApp conversations."""
    
    # Timeout for flow completion (24 hours)
    FLOW_TIMEOUT_HOURS = 24
    
    # Maximum attempts for each field
    MAX_ATTEMPTS = 3
    
    def __init__(self, storage_backend: Optional[Callable] = None):
        self.storage_backend = storage_backend
        self.flow_sessions: Dict[str, CallbackFlowContext] = {}
        self.timezone = "Asia/Kolkata"
    
    def _generate_session_id(self, wa_id: str, tenant_id: str) -> str:
        """Generate a unique session ID for this callback flow."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        random_part = secrets.token_hex(4)
        return f"cbflow_{wa_id}_{tenant_id}_{timestamp}_{random_part}"
    
    def start_flow(self, wa_id: str, tenant_id: str) -> CallbackFlowContext:
        """Start a new callback booking flow."""
        session_id = self._generate_session_id(wa_id, tenant_id)
        
        context = CallbackFlowContext(
            wa_id=wa_id,
            tenant_id=tenant_id,
            session_id=session_id,
            current_state=CallbackFlowState.INITIAL.value
        )
        
        self.flow_sessions[session_id] = context
        logger.info(f"Callback flow started: {session_id} for wa_id {wa_id}")
        
        return context
    
    def get_flow_context(self, session_id: str) -> Optional[CallbackFlowContext]:
        """Get the flow context for a given session."""
        return self.flow_sessions.get(session_id)
    
    def get_flow_context_by_wa_id(self, wa_id: str) -> Optional[CallbackFlowContext]:
        """Find active flow context for a WhatsApp ID."""
        for context in self.flow_sessions.values():
            if context.wa_id == wa_id and not context.is_complete():
                return context
        return None
    
    def process_message(self, session_id: str, message: str) -> Tuple[str, CallbackFlowContext]:
        """Process an incoming message and update flow state.
        
        Returns: (response_message, updated_context)
        """
        context = self.flow_sessions.get(session_id)
        if not context:
            return "I couldn't find your callback request. Please start over.", None
        
        if context.is_complete():
            return "Your callback request has already been completed. Is there anything else I can help you with?", context
        
        # Update last message and updated timestamp
        context.last_message = message
        context.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Process based on current state
        response = self._handle_state(context, message)
        return response, context
    
    def _handle_state(self, context: CallbackFlowContext, message: str) -> str:
        """Handle message based on current state."""
        state = context.current_state
        
        if state == CallbackFlowState.INITIAL.value:
            return self._handle_initial(context, message)
        elif state == CallbackFlowState.COLLECTING_NAME.value:
            return self._handle_collecting_name(context, message)
        elif state == CallbackFlowState.COLLECTING_EMAIL.value:
            return self._handle_collecting_email(context, message)
        elif state == CallbackFlowState.COLLECTING_PHONE.value:
            return self._handle_collecting_phone(context, message)
        elif state == CallbackFlowState.COLLECTING_PURPOSE.value:
            return self._handle_collecting_purpose(context, message)
        elif state == CallbackFlowState.SELECTING_TYPE.value:
            return self._handle_selecting_type(context, message)
        elif state == CallbackFlowState.SELECTING_DATE.value:
            return self._handle_selecting_date(context, message)
        elif state == CallbackFlowState.SELECTING_TIME.value:
            return self._handle_selecting_time(context, message)
        elif state == CallbackFlowState.SELECTING_PRIORITY.value:
            return self._handle_selecting_priority(context, message)
        elif state == CallbackFlowState.CONFIRMATION.value:
            return self._handle_confirmation(context, message)
        else:
            return "I'm sorry, I didn't understand that. Let's start over with your callback request."
    
    def _handle_initial(self, context: CallbackFlowContext, message: str) -> str:
        """Handle initial message - transition to collecting user name."""
        context.current_state = CallbackFlowState.COLLECTING_NAME.value
        
        # If the user provided a name in their initial message, process it
        stripped = message.strip()
        if len(stripped) >= 2 and not any(char.isdigit() for char in stripped):
            context.user_name = stripped
            context.current_state = CallbackFlowState.COLLECTING_EMAIL.value
            return f"Thanks, {context.user_name}! What is your email address? (optional - you can say 'skip' to continue)"
        else:
            return "I'd be happy to help you schedule a callback! To get started, could you please tell me your name?"
    
    def _handle_collecting_name(self, context: CallbackFlowContext, message: str) -> str:
        """Handle name collection."""
        # Increment attempt counter
        context.attempts['name'] = context.attempts.get('name', 0) + 1
        
        if context.attempts['name'] > self.MAX_ATTEMPTS:
            return "I'm having trouble understanding. Could you please just tell me your name?"
        
        # Simple validation - name should be at least 2 characters
        stripped = message.strip()
        if len(stripped) >= 2 and not any(char.isdigit() for char in stripped):
            context.user_name = stripped
            context.current_state = CallbackFlowState.COLLECTING_EMAIL.value
            return f"Thanks, {context.user_name}! What is your email address? (optional - you can say 'skip' to continue)"
        else:
            return "Could you please provide your name? (At least 2 letters, no numbers)"
    
    def _handle_collecting_email(self, context: CallbackFlowContext, message: str) -> str:
        """Handle email collection."""
        stripped = message.strip().lower()
        
        if stripped == 'skip' or stripped == 'no':
            context.user_email = None
            context.current_state = CallbackFlowState.COLLECTING_PHONE.value
            return "No problem! What is your phone number? (optional - say 'skip' to continue)"
        
        # Basic email validation
        if self._is_valid_email(message.strip()):
            context.user_email = message.strip()
            context.current_state = CallbackFlowState.COLLECTING_PHONE.value
            return "Thank you! What is your phone number? (optional - say 'skip' to continue)"
        else:
            return "That doesn't look like a valid email. Please provide a valid email or say 'skip' to continue."
    
    def _handle_collecting_phone(self, context: CallbackFlowContext, message: str) -> str:
        """Handle phone collection."""
        stripped = message.strip()
        
        if stripped.lower() == 'skip' or stripped.lower() == 'no':
            context.user_phone = None
            context.current_state = CallbackFlowState.COLLECTING_PURPOSE.value
            return "Understood. What is the purpose of this callback? (e.g., product demo, technical support, etc.)"
        
        # Basic phone validation
        if self._is_valid_phone(message.strip()):
            context.user_phone = message.strip()
            context.current_state = CallbackFlowState.COLLECTING_PURPOSE.value
            return "Got it! What is the purpose of this callback? (e.g., product demo, technical support, etc.)"
        else:
            return "That doesn't look like a valid phone number. Please provide a valid number or say 'skip' to continue."
    
    def _handle_collecting_purpose(self, context: CallbackFlowContext, message: str) -> str:
        """Handle purpose collection."""
        stripped = message.strip()
        
        if len(stripped) < 10:
            return "Could you please provide a bit more detail about the purpose? (At least 10 characters)"
        
        context.purpose = stripped
        context.current_state = CallbackFlowState.SELECTING_TYPE.value
        return self._get_type_selection_message()
    
    def _handle_selecting_type(self, context: CallbackFlowContext, message: str) -> str:
        """Handle callback type selection."""
        message_lower = message.strip().lower()
        
        # Try to match with callback types
        type_mapping = {
            '1': 'sales', 'first': 'sales', 'one': 'sales',
            '2': 'support', 'second': 'support', 'two': 'support',
            '3': 'technical', 'third': 'technical', 'three': 'technical',
            '4': 'general', 'fourth': 'general', 'four': 'general',
            'general': 'general', 'other': 'general',
            'sales': 'sales', 'purchase': 'sales', 'buy': 'sales',
            'support': 'support', 'help': 'support',
            'technical': 'technical', 'demo': 'technical', 'integration': 'technical'
        }
        
        matched_type = None
        for key, value in type_mapping.items():
            if key in message_lower:
                matched_type = value
                break
        
        if matched_type:
            context.callback_type = matched_type
            context.current_state = CallbackFlowState.SELECTING_PRIORITY.value
            return self._get_priority_selection_message()
        
        # Check for valid type directly
        valid_types = [t.value for t in CallbackType]
        if message_lower in valid_types:
            context.callback_type = message_lower
            context.current_state = CallbackFlowState.SELECTING_PRIORITY.value
            return self._get_priority_selection_message()
        
        return self._get_type_selection_message(retry=True)
    
    def _handle_selecting_priority(self, context: CallbackFlowContext, message: str) -> str:
        """Handle priority selection."""
        message_lower = message.strip().lower()
        
        # Try to match with priority levels
        priority_mapping = {
            '1': 'urgent', 'urgent': 'urgent', 'highest': 'urgent', 'critical': 'urgent',
            '2': 'high', 'high': 'high',
            '3': 'medium', 'medium': 'medium', 'normal': 'medium',
            '4': 'low', 'low': 'low'
        }
        
        matched_priority = None
        for key, value in priority_mapping.items():
            if key in message_lower:
                matched_priority = value
                break
        
        if matched_priority:
            context.priority = matched_priority
            context.current_state = CallbackFlowState.SELECTING_DATE.value
            return "Great! When would you like to have this callback? Please provide a date (e.g., tomorrow, next Monday, 2024-01-15)."
        
        # Check for valid priority directly
        valid_priorities = [p.value for p in Priority]
        if message_lower in valid_priorities:
            context.priority = message_lower
            context.current_state = CallbackFlowState.SELECTING_DATE.value
            return "When would you like to have this callback? Please provide a date (e.g., tomorrow, next Monday, 2024-01-15)."
        
        return self._get_priority_selection_message(retry=True)
    
    def _handle_selecting_date(self, context: CallbackFlowContext, message: str) -> str:
        """Handle date selection."""
        date_str = self._parse_date_message(message.strip())
        
        if not date_str:
            return "I couldn't understand that date. Please provide a date like 'tomorrow', 'next Monday', or '2024-01-15'."
        
        # Validate that date is in the future and within reasonable range
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
            today = datetime.now(timezone.utc).date()
            
            if parsed_date.date() < today:
                return "That date is in the past. Please choose a future date."
            
            # Don't allow dates too far in the future
            max_future_date = today + timedelta(days=30)
            if parsed_date.date() > max_future_date:
                return f"I can only schedule up to 30 days in advance. Please choose a date before {max_future_date.strftime('%Y-%m-%d')}"
            
            context.preferred_date = date_str
            context.current_state = CallbackFlowState.SELECTING_TIME.value
            return "What time would you prefer? (e.g., 10:00 AM, 2 PM, 15:30)"
        except ValueError:
            return "There was an error with that date. Please try again with a format like '2024-01-15'."
    
    def _handle_selecting_time(self, context: CallbackFlowContext, message: str) -> str:
        """Handle time selection."""
        time_str = self._parse_time_message(message.strip())
        
        if not time_str:
            return "I couldn't understand that time. Please provide a time like '10:00 AM', '2 PM', or '15:30'."
        
        # Validate time is within business hours (9 AM - 6 PM)
        try:
            if ':' in time_str:
                hours, minutes = time_str.split(':')
                hour = int(hours)
                minute = int(minutes)
            else:
                # Handle formats like "2 PM", "10 AM"
                time_parts = time_str.upper().split()
                if len(time_parts) >= 2 and time_parts[1] in ['AM', 'PM']:
                    hour = int(time_parts[0])
                    minute = 0
                    if time_parts[1] == 'PM' and hour != 12:
                        hour += 12
                    elif time_parts[1] == 'AM' and hour == 12:
                        hour = 0
                else:
                    hour = int(time_parts[0])
                    minute = 0
            
            if hour < 9 or hour >= 18:
                return "Our callback hours are between 9:00 AM and 6:00 PM. Please choose a time within this range."
            
            context.preferred_time = f"{hour:02d}:{minute:02d}"
            context.current_state = CallbackFlowState.CONFIRMATION.value
            return self._get_confirmation_message(context)
        except (ValueError, IndexError):
            return "I couldn't understand that time. Please try again with a format like '10:00 AM' or '15:30'."
    
    def _handle_confirmation(self, context: CallbackFlowContext, message: str) -> str:
        """Handle final confirmation."""
        confirm_lower = message.strip().lower()
        
        if confirm_lower in ['yes', 'yep', 'yeah', 'confirm', 'ok', 'okay', 'sure']:
            return self._finalize_callback(context)
        elif confirm_lower in ['no', 'cancel', 'stop', 'nevermind']:
            context.current_state = CallbackFlowState.CANCELLED.value
            return "Your callback request has been cancelled. If you change your mind, feel free to start over!"
        else:
            return self._get_confirmation_message(context, retry=True)
    
    def _finalize_callback(self, context: CallbackFlowContext) -> str:
        """Finalize the callback request and create Google Meet if possible."""
        # Create callback request
        callback_request = callback_service.create_callback_request(
            tenant_id=context.tenant_id,
            wa_id=context.wa_id,
            customer_name=context.user_name or "Unknown",
            callback_type=context.callback_type,
            purpose=context.purpose or "",
            preferred_date=context.preferred_date,
            preferred_time=context.preferred_time,
            customer_email=context.user_email,
            customer_phone=context.user_phone,
            priority=context.priority,
            additional_info=context.purpose or ""
        )
        
        context.callback_id = callback_request.id
        context.current_state = CallbackFlowState.COMPLETED.value
        
        logger.info(f"Callback request created via flow: {callback_request.id}")
        
        # For now, just confirm creation. In production, this would trigger:
        # 1. Google Meet creation if date/time is provided
        # 2. Agent assignment
        # 3. Notifications to all parties
        
        if callback_request.status == 'confirmed' and callback_request.preferred_date and callback_request.preferred_time:
            return (
                f"🎉 Excellent! Your callback request has been confirmed.\n\n"
                f"📅 Date: {callback_request.preferred_date}\n"
                f"⏰ Time: {callback_request.preferred_time}\n"
                f"🎯 Type: {callback_request.callback_type}\n"
                f"📝 Purpose: {callback_request.purpose}\n\n"
                f"🎫 Your callback ID is: {callback_request.id}\n\n"
                f"Our team will contact you shortly to set up a Google Meet link. "
                f"You'll receive a confirmation once the meeting is scheduled."
            )
        else:
            return (
                f"✅ Thank you! Your callback request has been received.\n\n"
                f"🎫 Your callback ID is: {callback_request.id}\n\n"
                f"🎯 Type: {callback_request.callback_type}\n"
                f"📝 Purpose: {callback_request.purpose}\n\n"
                f"Our team will contact you shortly to confirm a suitable time "
                f"and provide a Google Meet link for your callback."
            )
    
    def _get_type_selection_message(self, retry: bool = False) -> str:
        """Get message for type selection."""
        if retry:
            return (
                "Please choose the type of callback from these options:\n\n"
                "1. Sales consultation\n"
                "2. Technical support\n"
                "3. Technical discussion\n"
                "4. General inquiry\n\n"
                "Reply with the number or type name."
            )
        else:
            return (
                "What type of callback would you like?\n\n"
                "1. Sales consultation\n"
                "2. Technical support\n"
                "3. Technical discussion\n"
                "4. General inquiry\n\n"
                "Just reply with the number."
            )
    
    def _get_priority_selection_message(self, retry: bool = False) -> str:
        """Get message for priority selection."""
        if retry:
            return (
                "Please select the priority level:\n\n"
                "1. Urgent (within 24 hours)\n"
                "2. High (within 2-3 days)\n"
                "3. Medium (within 1 week)\n"
                "4. Low (flexible timing)\n\n"
                "Reply with the number or priority word."
            )
        else:
            return (
                "What priority level is this callback?\n\n"
                "1. Urgent (within 24 hours)\n"
                "2. High (within 2-3 days)\n"
                "3. Medium (within 1 week)\n"
                "4. Low (flexible timing)"
            )
    
    def _get_confirmation_message(self, context: CallbackFlowContext, retry: bool = False) -> str:
        """Get confirmation message with collected data."""
        message = f"Please confirm your callback request:\n\n"
        message += f"Callback Type: {context.callback_type}\n"
        message += f"Priority: {context.priority}\n"
        message += f"Purpose: {context.purpose}\n"
        if context.preferred_date:
            message += f"Date: {context.preferred_date}\n"
        if context.preferred_time:
            message += f"Time: {context.preferred_time}\n"
        message += "\nReply 'yes' to confirm or 'no' to cancel."
        
        return message
    
    def _parse_date_message(self, message: str) -> Optional[str]:
        """Parse date from user message."""
        import re
        from dateutil.parser import parse
        from dateutil.relativedelta import relativedelta
        from dateutil.parser import ParserError
        
        today = datetime.now(timezone.utc).date()
        
        try:
            # Try to parse as date
            if re.match(r'^\d{4}-\d{2}-\d{2}$', message):
                # Already in YYYY-MM-DD format
                return message
            
            # Try to parse natural language
            parsed = parse(message, fuzzy=True)
            
            if parsed.date() < today:
                # If in the past, try to interpret as "next X"
                message_lower = message.lower()
                if any(word in message_lower for word in ['next', 'coming']):
                    # This suggests next occurrence
                    if 'monday' in message_lower:
                        days_ahead = (7 - today.weekday()) % 7
                        if days_ahead == 0:
                            days_ahead = 7
                    elif 'tuesday' in message_lower:
                        days_ahead = (0 - today.weekday()) % 7
                        if days_ahead <= 0:
                            days_ahead += 7
                    elif 'wednesday' in message_lower:
                        days_ahead = (1 - today.weekday()) % 7
                        if days_ahead <= 0:
                            days_ahead += 7
                    elif 'thursday' in message_lower:
                        days_ahead = (2 - today.weekday()) % 7
                        if days_ahead <= 0:
                            days_ahead += 7
                    elif 'friday' in message_lower:
                        days_ahead = (3 - today.weekday()) % 7
                        if days_ahead <= 0:
                            days_ahead += 7
                    elif 'saturday' in message_lower:
                        days_ahead = (4 - today.weekday()) % 7
                        if days_ahead <= 0:
                            days_ahead += 7
                    elif 'sunday' in message_lower:
                        days_ahead = (5 - today.weekday()) % 7
                        if days_ahead <= 0:
                            days_ahead += 7
                    else:
                        return None
                    
                    new_date = today + timedelta(days=days_ahead)
                    return new_date.strftime('%Y-%m-%d')
                else:
                    return None
            
            return parsed.strftime('%Y-%m-%d')
        except (ParserError, ValueError):
            pass
        
        # Try to match relative dates
        today_str = today.strftime('%Y-%m-%d')
        message_lower = message.lower()
        
        if 'tomorrow' in message_lower:
            tomorrow = today + timedelta(days=1)
            return tomorrow.strftime('%Y-%m-%d')
        elif 'today' in message_lower:
            return today_str
        elif 'day after tomorrow' in message_lower or 'day after' in message_lower:
            day_after = today + timedelta(days=2)
            return day_after.strftime('%Y-%m-%d')
        elif 'next monday' in message_lower:
            days_ahead = (0 - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_monday = today + timedelta(days=days_ahead)
            return next_monday.strftime('%Y-%m-%d')
        elif 'next tuesday' in message_lower:
            days_ahead = (1 - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_tuesday = today + timedelta(days=days_ahead)
            return next_tuesday.strftime('%Y-%m-%d')
        elif 'next wednesday' in message_lower:
            days_ahead = (2 - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_wednesday = today + timedelta(days=days_ahead)
            return next_wednesday.strftime('%Y-%m-%d')
        
        return None
    
    def _parse_time_message(self, message: str) -> Optional[str]:
        """Parse time from user message."""
        import re
        
        # Try to match various time formats
        patterns = [
            # 24-hour format: HH:MM or HH:MM:SS
            r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$',
            # 12-hour format with AM/PM: HH:MM AM or HH:MMAM
            r'^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)$',
            r'^(\d{1,2}):(\d{2})(AM|PM|am|pm)$',
            # Simple hour with AM/PM: 2 PM, 10am
            r'^(\d{1,2})\s*(AM|PM|am|pm)$',
            r'^(\d{1,2})(AM|PM|am|pm)$',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, message.strip())
            if match:
                if pattern.startswith('^(\d{1,2}):(\d{2})'):
                    hours = match.group(1) or '0'
                    minutes = match.group(2) or '0'
                    
                    # Check if it has AM/PM
                    if len(match.groups()) >= 3 and match.group(3):
                        ampm = match.group(3).upper()
                        hour_int = int(hours)
                        if ampm == 'PM' and hour_int != 12:
                            hour_int += 12
                        elif ampm == 'AM' and hour_int == 12:
                            hour_int = 0
                        return f"{hour_int:02d}:{minutes}"
                    else:
                        return f"{int(hours):02d}:{minutes}"
                elif pattern.startswith('^(\d{1,2})\s'):
                    hour = match.group(1) or '0'
                    ampm = match.group(2).upper()
                    hour_int = int(hour)
                    if ampm == 'PM' and hour_int != 12:
                        hour_int += 12
                    elif ampm == 'AM' and hour_int == 12:
                        hour_int = 0
                    return f"{hour_int:02d}:00"
        
        return None
    
    def _is_valid_email(self, email: str) -> bool:
        """Validate email format."""
        import re
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        return bool(re.match(email_regex, email))
    
    def _is_valid_phone(self, phone: str) -> bool:
        """Validate phone format (country code + number)."""
        import re
        # Remove spaces and dashes
        cleaned = re.sub(r'[\s\-]', '', phone)
        
        # Should start with + and have reasonable length
        if not cleaned.startswith('+'):
            return False
        
        # Check for country code + at least 8 digits
        if len(cleaned[1:]) < 8:
            return False
        
        return True


# Singleton instance
callback_flow_service = CallbackFlowService()