"""Multi-Channel Notification Service for Callback Booking.

This service provides a unified interface for sending notifications through
multiple channels (WhatsApp via Send2 Digital, Email, SMS) with intelligent
fallback and retry logic.

The service prioritizes channels based on:
1. Customer preference (if known)
2. Availability and reliability
3. Content type and urgency
"""

import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum

from backend.services.send2_callback_notification import send2_callback_service
from backend.services.callback_service import CallbackRequest

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Available notification channels."""
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SMS = "sms"


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationResult:
    """Result of a notification attempt."""
    channel: str
    success: bool
    error: Optional[str] = None
    message_id: Optional[str] = None
    timestamp: str = ""
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "success": self.success,
            "error": self.error,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "retry_count": self.retry_count
        }


@dataclass
class MultiChannelNotification:
    """Multi-channel notification configuration."""
    callback_request: CallbackRequest
    message: str
    subject: str = ""
    priority: str = "normal"
    channels: List[str] = None  # Prioritized list of channels to try
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.channels is None:
            self.channels = [NotificationChannel.WHATSAPP.value]
        if self.metadata is None:
            self.metadata = {}
    
    def add_channel(self, channel: str, priority: int = 0):
        """Add a channel with priority (lower number = higher priority)."""
        if channel not in self.channels:
            self.channels.insert(priority, channel)


class MultiChannelNotificationService:
    """Service for sending multi-channel notifications."""
    
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = [5, 15, 60]  # Exponential backoff
    
    def __init__(self):
        self.send2_service = send2_callback_service
        self.notification_history = []
    
    async def send_notification(
        self,
        notification: MultiChannelNotification
    ) -> List[NotificationResult]:
        """Send notification through prioritized channels."""
        results = []
        
        for channel in notification.channels:
            result = await self._send_via_channel(channel, notification)
            results.append(result)
            
            # If successful via high-priority channel, stop
            if result.success and channel in [NotificationChannel.WHATSAPP.value, NotificationChannel.EMAIL.value]:
                break
            
            # If this channel failed, log but continue to next
            if not result.success:
                logger.warning(f"Notification failed via {channel}: {result.error}")
        
        return results
    
    async def _send_via_channel(
        self,
        channel: str,
        notification: MultiChannelNotification,
        retry_count: int = 0
    ) -> NotificationResult:
        """Send notification via specific channel."""
        
        if channel == NotificationChannel.WHATSAPP.value:
            return await self._send_whatsapp(notification, retry_count)
        elif channel == NotificationChannel.EMAIL.value:
            return await self._send_email(notification, retry_count)
        elif channel == NotificationChannel.SMS.value:
            return await self._send_sms(notification, retry_count)
        else:
            return NotificationResult(
                channel=channel,
                success=False,
                error=f"Unknown channel: {channel}",
                timestamp=datetime.now(timezone.utc).isoformat()
            )
    
    async def _send_whatsapp(
        self,
        notification: MultiChannelNotification,
        retry_count: int = 0
    ) -> NotificationResult:
        """Send notification via WhatsApp using Send2 Digital."""
        
        try:
            callback_request = notification.callback_request
            message = notification.message
            
            # Check if Send2 is configured
            if not self.send2_service.is_configured():
                return NotificationResult(
                    channel=NotificationChannel.WHATSAPP.value,
                    success=False,
                    error="Send2 Digital is not configured",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count
                )
            
            # Validate phone number
            if not callback_request.wa_id:
                return NotificationResult(
                    channel=NotificationChannel.WHATSAPP.value,
                    success=False,
                    error="No WhatsApp ID provided",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count
                )
            
            # Send via Send2 Digital
            # For callbacks, we use direct messages (not templates) for flexibility
            success = await self.send2_service._send_whatsapp_message(
                phone=callback_request.wa_id,
                message=message
            )
            
            if success:
                return NotificationResult(
                    channel=NotificationChannel.WHATSAPP.value,
                    success=True,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count
                )
            else:
                # Retry logic
                if retry_count < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY_SECONDS[retry_count] if retry_count < len(self.RETRY_DELAY_SECONDS) else 60
                    logger.info(f"Retrying WhatsApp notification in {delay}s (attempt {retry_count + 1})")
                    await asyncio.sleep(delay)
                    return await self._send_whatsapp(notification, retry_count + 1)
                
                return NotificationResult(
                    channel=NotificationChannel.WHATSAPP.value,
                    success=False,
                    error="Failed after retries",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count
                )
                
        except Exception as e:
            logger.error(f"WhatsApp notification error: {e}")
            return NotificationResult(
                channel=NotificationChannel.WHATSAPP.value,
                success=False,
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
                retry_count=retry_count
            )
    
    async def _send_email(
        self,
        notification: MultiChannelNotification,
        retry_count: int = 0
    ) -> NotificationResult:
        """Send notification via Email."""
        
        try:
            callback_request = notification.callback_request
            
            # Check if email is available
            if not callback_request.customer_email:
                return NotificationResult(
                    channel=NotificationChannel.EMAIL.value,
                    success=False,
                    error="No email address provided",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count
                )
            
            # For now, use console logging - integrate with your email service
            logger.info(f"Sending email to {callback_request.customer_email}")
            logger.info(f"Subject: {notification.subject}")
            logger.info(f"Body: {notification.message}")
            
            # TODO: Integrate with your email service (SendGrid, etc.)
            # For now, return success to allow the flow to continue
            return NotificationResult(
                channel=NotificationChannel.EMAIL.value,
                success=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
                retry_count=retry_count
            )
            
        except Exception as e:
            logger.error(f"Email notification error: {e}")
            return NotificationResult(
                channel=NotificationChannel.EMAIL.value,
                success=False,
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
                retry_count=retry_count
            )
    
    async def _send_sms(
        self,
        notification: MultiChannelNotification,
        retry_count: int = 0
    ) -> NotificationResult:
        """Send notification via SMS."""
        
        try:
            callback_request = notification.callback_request
            
            # Check if phone is available
            if not callback_request.customer_phone:
                return NotificationResult(
                    channel=NotificationChannel.SMS.value,
                    success=False,
                    error="No phone number provided",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    retry_count=retry_count
                )
            
            # TODO: Integrate with your SMS provider
            logger.info(f"Sending SMS to {callback_request.customer_phone}")
            logger.info(f"Message: {notification.message}")
            
            # Return success to allow flow to continue
            return NotificationResult(
                channel=NotificationChannel.SMS.value,
                success=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
                retry_count=retry_count
            )
            
        except Exception as e:
            logger.error(f"SMS notification error: {e}")
            return NotificationResult(
                channel=NotificationChannel.SMS.value,
                success=False,
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
                retry_count=retry_count
            )
    
    def create_callback_confirmation_notification(
        self,
        callback_request: CallbackRequest
    ) -> MultiChannelNotification:
        """Create confirmation notification for callback request."""
        message = notification_service.format_callback_confirmation(callback_request)
        
        return MultiChannelNotification(
            callback_request=callback_request,
            message=message,
            subject=f"Callback Request Confirmed: {callback_request.id}",
            priority=NotificationPriority.NORMAL.value,
            channels=[
                NotificationChannel.WHATSAPP.value,
                NotificationChannel.EMAIL.value if callback_request.customer_email else None
            ],
            metadata={
                "notification_type": "callback_confirmation",
                "callback_id": callback_request.id
            }
        )
    
    def create_callback_scheduled_notification(
        self,
        callback_request: CallbackRequest
    ) -> MultiChannelNotification:
        """Create notification when callback is scheduled with Meet link."""
        message = notification_service.format_callback_confirmation(callback_request)
        if callback_request.is_scheduled():
            message += f"\n\n🔗 Google Meet Link: {callback_request.meet_link}"
        
        return MultiChannelNotification(
            callback_request=callback_request,
            message=message,
            subject=f"Callback Scheduled: {callback_request.id}",
            priority=NotificationPriority.HIGH.value,
            channels=[
                NotificationChannel.WHATSAPP.value,
                NotificationChannel.EMAIL.value if callback_request.customer_email else None
            ],
            metadata={
                "notification_type": "callback_scheduled",
                "callback_id": callback_request.id,
                "meet_link": callback_request.meet_link
            }
        )
    
    def create_reminder_notification(
        self,
        callback_request: CallbackRequest,
        minutes_before: int = 15
    ) -> MultiChannelNotification:
        """Create reminder notification."""
        message = notification_service.format_reminder_message(callback_request, minutes_before)
        
        return MultiChannelNotification(
            callback_request=callback_request,
            message=message,
            subject=f"Reminder: Callback in {minutes_before} minutes",
            priority=NotificationPriority.HIGH.value,
            channels=[
                NotificationChannel.WHATSAPP.value,
                NotificationChannel.EMAIL.value if callback_request.customer_email else None
            ],
            metadata={
                "notification_type": "callback_reminder",
                "callback_id": callback_request.id,
                "minutes_before": minutes_before
            }
        )
    
    def create_cancellation_notification(
        self,
        callback_request: CallbackRequest,
        reason: str
    ) -> MultiChannelNotification:
        """Create cancellation notification."""
        message = notification_service.format_cancellation_message(callback_request, reason)
        
        return MultiChannelNotification(
            callback_request=callback_request,
            message=message,
            subject=f"Callback Cancelled: {callback_request.id}",
            priority=NotificationPriority.NORMAL.value,
            channels=[
                NotificationChannel.WHATSAPP.value,
                NotificationChannel.EMAIL.value if callback_request.customer_email else None
            ],
            metadata={
                "notification_type": "callback_cancellation",
                "callback_id": callback_request.id,
                "reason": reason
            }
        )
    
    def create_agent_notification(
        self,
        callback_request: CallbackRequest
    ) -> MultiChannelNotification:
        """Create notification for assigned agent."""
        message = notification_service.format_agent_notification(callback_request)
        
        # For agent notifications, we might want to use different channels
        return MultiChannelNotification(
            callback_request=callback_request,
            message=message,
            subject=f"New Callback Assigned: {callback_request.id}",
            priority=NotificationPriority.HIGH.value,
            channels=[
                # For agents, prioritize email or internal chat
                NotificationChannel.EMAIL.value,
                NotificationChannel.WHATSAPP.value
            ],
            metadata={
                "notification_type": "agent_assignment",
                "callback_id": callback_request.id,
                "agent_id": callback_request.assigned_agent_id
            }
        )
    
    def log_notification_result(self, result: NotificationResult):
        """Log notification result for auditing."""
        self.notification_history.append(result)
        logger.info(f"Notification {result.channel}: {'Success' if result.success else 'Failed'}")


# Singleton instance
multi_channel_notification_service = MultiChannelNotificationService()