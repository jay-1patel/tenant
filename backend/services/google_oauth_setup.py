"""Google OAuth 2.0 Setup for Google Calendar and Meet Integration.

This module provides:
1. OAuth 2.0 authentication with Google APIs
2. Service account authentication for server-to-server communication
3. Token management and refresh logic
4. Scopes configuration for Calendar API access

Required Setup:
1. Create a Google Cloud Project
2. Enable Google Calendar API
3. Create OAuth 2.0 credentials or Service Account credentials
4. Add service account email as calendar delegate for target calendars

Environment Variables:
- GOOGLE_CLIENT_ID: OAuth client ID
- GOOGLE_CLIENT_SECRET: OAuth client secret  
- GOOGLE_REFRESH_TOKEN: OAuth refresh token
- GOOGLE_SERVICE_ACCOUNT_JSON: Service account JSON key file path or content
- GOOGLE_CALENDAR_ID: Target calendar ID (default: "primary")
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


# Google Calendar API scopes
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

GOOGLE_CALENDAR_READONLY_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]

# OAuth 2.0 endpoints
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class AuthMethod(Enum):
    """Authentication methods for Google API."""
    OAUTH2 = "oauth2"
    SERVICE_ACCOUNT = "service_account"


@dataclass
class OAuthConfig:
    """OAuth 2.0 configuration."""
    client_id: str
    client_secret: str
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob"
    scopes: List[str] = GOOGLE_CALENDAR_SCOPES
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[str] = None  # ISO format timestamp


@dataclass
class ServiceAccountConfig:
    """Service account configuration."""
    service_account_info: Dict[str, Any]
    scopes: List[str] = GOOGLE_CALENDAR_SCOPES
    subject: Optional[str] = None  # For domain-wide delegation


class GoogleOAuthService:
    """Service for handling Google OAuth 2.0 authentication."""
    
    GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"
    
    def __init__(self):
        self.auth_method = None
        self.oauth_config = None
        self.service_account_config = None
        self.access_token = None
        self.token_expires_at = None
        self._load_config()
    
    def _load_config(self):
        """Load Google OAuth configuration from environment variables."""
        # Try OAuth 2.0 first
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")
        
        if client_id and client_secret:
            self.auth_method = AuthMethod.OAUTH2
            self.oauth_config = OAuthConfig(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token
            )
            logger.info("Google OAuth 2.0 configuration loaded")
        else:
            # Try Service Account
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if service_account_json:
                try:
                    # Check if it's a file path or JSON content
                    if os.path.isfile(service_account_json):
                        with open(service_account_json, 'r') as f:
                            service_account_info = json.load(f)
                    else:
                        service_account_info = json.loads(service_account_json)
                    
                    self.auth_method = AuthMethod.SERVICE_ACCOUNT
                    self.service_account_config = ServiceAccountConfig(
                        service_account_info=service_account_info
                    )
                    logger.info("Google Service Account configuration loaded")
                except Exception as e:
                    logger.error(f"Failed to load service account: {e}")
            else:
                logger.warning("No Google authentication configuration found")
    
    async def authenticate(self) -> bool:
        """Authenticate with Google API using configured method."""
        if self.auth_method == AuthMethod.OAUTH2:
            return await self._authenticate_oauth2()
        elif self.auth_method == AuthMethod.SERVICE_ACCOUNT:
            return await self._authenticate_service_account()
        else:
            logger.error("No authentication method configured")
            return False
    
    async def _authenticate_oauth2(self) -> bool:
        """Authenticate using OAuth 2.0."""
        if not self.oauth_config:
            return False
        
        # Check if we have a valid access token
        if self._has_valid_token():
            return True
        
        # Try to refresh token if we have refresh token
        if self.oauth_config.refresh_token:
            try:
                token_data = await self._refresh_access_token()
                if token_data.get("access_token"):
                    self.access_token = token_data["access_token"]
                    expires_in = token_data.get("expires_in", 3600)
                    self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)  # 5 min buffer
                    return True
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
        
        logger.error("No valid authentication method available")
        return False
    
    async def _authenticate_service_account(self) -> bool:
        """Authenticate using Service Account JWT."""
        if not self.service_account_config:
            return False
        
        try:
            import jwt
            import time
            
            service_account = self.service_account_config.service_account_info
            scopes = self.service_account_config.scopes
            subject = self.service_account_config.subject
            
            # Create JWT token
            now = int(time.time())
            payload = {
                "iss": service_account["client_email"],
                "sub": subject or service_account["client_email"],
                "aud": GOOGLE_OAUTH_TOKEN_URL,
                "iat": now,
                "exp": now + 3600,  # 1 hour expiration
                "scope": " ".join(scopes)
            }
            
            # Sign JWT with private key
            token = jwt.encode(payload, service_account["private_key"], algorithm="RS256")
            
            # Exchange JWT for access token
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GOOGLE_OAUTH_TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": token
                    }
                )
                
                if response.status_code == 200:
                    token_data = response.json()
                    self.access_token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in", 3600)
                    self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)
                    return True
                else:
                    logger.error(f"Failed to authenticate service account: {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Service account authentication failed: {e}")
            return False
    
    def _has_valid_token(self) -> bool:
        """Check if current access token is still valid."""
        if not self.access_token or not self.token_expires_at:
            return False
        
        try:
            expires_at = datetime.fromisoformat(self.token_expires_at)
            return expires_at > datetime.now(timezone.utc)
        except ValueError:
            return False
    
    async def _refresh_access_token(self) -> Dict[str, Any]:
        """Refresh OAuth 2.0 access token."""
        if not self.oauth_config or not self.oauth_config.refresh_token:
            raise Exception("No refresh token available")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": self.oauth_config.client_id,
                    "client_secret": self.oauth_config.client_secret,
                    "refresh_token": self.oauth_config.refresh_token,
                    "grant_type": "refresh_token"
                }
            )
            
            if response.status_code == 200:
                token_data = response.json()
                # Update refresh token if new one provided
                if token_data.get("refresh_token"):
                    self.oauth_config.refresh_token = token_data["refresh_token"]
                return token_data
            else:
                raise Exception(f"Failed to refresh token: {response.text}")
    
    def get_access_token(self) -> Optional[str]:
        """Get current access token (will automatically refresh if needed)."""
        return self.access_token
    
    async def get_valid_access_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if necessary."""
        if self._has_valid_token():
            return self.access_token
        
        if await self.authenticate():
            return self.access_token
        
        return None
    
    def generate_oauth_url(self, state: str = None) -> str:
        """Generate OAuth 2.0 authentication URL for user consent."""
        if not self.oauth_config:
            raise Exception("OAuth configuration not available")
        
        params = {
            "client_id": self.oauth_config.client_id,
            "redirect_uri": self.oauth_config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.oauth_config.scopes),
            "access_type": "offline",  # Request refresh token
            "prompt": "consent"  # Force consent screen to get refresh token
        }
        
        if state:
            params["state"] = state
        
        # Build URL with query parameters
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{GOOGLE_OAUTH_AUTH_URL}?{query_string}"
    
    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if not self.oauth_config:
            raise Exception("OAuth configuration not available")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": self.oauth_config.client_id,
                    "client_secret": self.oauth_config.client_secret,
                    "code": code,
                    "redirect_uri": self.oauth_config.redirect_uri,
                    "grant_type": "authorization_code"
                }
            )
            
            if response.status_code == 200:
                token_data = response.json()
                # Store tokens
                self.access_token = token_data.get("access_token")
                self.oauth_config.access_token = self.access_token
                
                refresh_token = token_data.get("refresh_token")
                if refresh_token:
                    self.oauth_config.refresh_token = refresh_token
                    # Save to environment for persistence
                    os.environ["GOOGLE_REFRESH_TOKEN"] = refresh_token
                
                expires_in = token_data.get("expires_in", 3600)
                self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)
                
                return token_data
            else:
                raise Exception(f"Failed to exchange code: {response.text}")
    
    async def revoke_token(self) -> bool:
        """Revoke current access token."""
        if not self.access_token:
            return True
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GOOGLE_OAUTH_REVOKE_URL,
                    params={"token": self.access_token}
                )
                
                if response.status_code == 200:
                    self.access_token = None
                    self.token_expires_at = None
                    if self.oauth_config:
                        self.oauth_config.access_token = None
                    return True
                else:
                    logger.error(f"Failed to revoke token: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error revoking token: {e}")
            return False
    
    def is_configured(self) -> bool:
        """Check if Google authentication is configured."""
        return self.auth_method is not None
    
    def get_auth_method(self) -> Optional[str]:
        """Get current authentication method."""
        return self.auth_method.value if self.auth_method else None


# Create singleton instance
google_oauth_service = GoogleOAuthService()


# Enhanced GoogleMeetService with OAuth integration
class EnhancedGoogleMeetService:
    """Enhanced Google Meet service with OAuth authentication."""
    
    GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"
    
    def __init__(self, oauth_service: GoogleOAuthService = None):
        self.oauth_service = oauth_service or google_oauth_service
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers with authorization token."""
        access_token = await self.oauth_service.get_valid_access_token()
        if not access_token:
            raise Exception("Failed to obtain access token")
        
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    async def get_calendar_list(self) -> List[Dict[str, Any]]:
        """Get list of available calendars."""
        try:
            headers = await self._get_auth_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.GOOGLE_API_BASE}/users/me/calendarList",
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json().get("items", [])
                else:
                    logger.error(f"Failed to get calendar list: {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error getting calendar list: {e}")
            return []
    
    async def create_meeting(
        self,
        calendar_id: str = "primary",
        title: str = "Callback Meeting",
        description: str = "",
        start_time: str = "",
        end_time: str = "",
        attendees: List[Dict[str, str]] = None,
        timezone: str = "Asia/Kolkata",
        send_notifications: bool = True
    ) -> Dict[str, Any]:
        """Create a Google Calendar event with Google Meet conference."""
        try:
            headers = await self._get_auth_headers()
            
            # Create event with conference data
            conference_data = {
                "createRequest": {
                    "requestId": secrets.token_hex(12),
                    "conferenceSolutionKey": {
                        "type": "hangoutsMeet"
                    }
                }
            }
            
            event_data = {
                "summary": title,
                "description": description,
                "start": {
                    "dateTime": start_time,
                    "timeZone": timezone
                },
                "end": {
                    "dateTime": end_time,
                    "timeZone": timezone
                },
                "attendees": attendees or [],
                "conferenceData": conference_data,
                "reminders": {
                    "useDefault": True,
                    "overrides": [
                        {"method": "email", "minutes": 24 * 60},  # 24 hours
                        {"method": "email", "minutes": 15},     # 15 minutes
                        {"method": "popup", "minutes": 10}
                    ]
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.GOOGLE_API_BASE}/calendars/{calendar_id}/events",
                    headers=headers,
                    json=event_data
                )
                
                if response.status_code in [200, 201]:
                    event = response.json()
                    meet_link = None
                    
                    # Extract Google Meet link from event
                    conference_data = event.get("conferenceData")
                    if conference_data:
                        entry_points = conference_data.get("entryPoints", [])
                        for entry_point in entry_points:
                            if entry_point.get("entryPointType") == "video":
                                meet_link = entry_point.get("uri")
                                break
                    
                    # Fallback: Try hangoutLink (older API)
                    if not meet_link:
                        meet_link = event.get("hangoutLink")
                    
                    return {
                        "ok": True,
                        "event_id": event.get("id"),
                        "meet_link": meet_link,
                        "html_link": event.get("htmlLink"),
                        "start": event.get("start", {}).get("dateTime"),
                        "end": event.get("end", {}).get("dateTime"),
                        "calendar_id": calendar_id
                    }
                else:
                    logger.error(f"Failed to create event: {response.text}")
                    return {
                        "ok": False,
                        "error": response.text,
                        "status_code": response.status_code
                    }
                    
        except Exception as e:
            logger.error(f"Error creating meeting: {e}")
            return {"ok": False, "error": str(e)}
    
    async def get_event(self, calendar_id: str, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a calendar event by ID."""
        try:
            headers = await self._get_auth_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.GOOGLE_API_BASE}/calendars/{calendar_id}/events/{event_id}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get event: {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Error getting event: {e}")
            return None
    
    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update a calendar event."""
        try:
            headers = await self._get_auth_headers()
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self.GOOGLE_API_BASE}/calendars/{calendar_id}/events/{event_id}",
                    headers=headers,
                    json=updates
                )
                
                return response.status_code in [200, 204]
        except Exception as e:
            logger.error(f"Error updating event: {e}")
            return False
    
    async def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """Delete a calendar event."""
        try:
            headers = await self._get_auth_headers()
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.GOOGLE_API_BASE}/calendars/{calendar_id}/events/{event_id}",
                    headers=headers
                )
                
                return response.status_code in [200, 204]
        except Exception as e:
            logger.error(f"Error deleting event: {e}")
            return False
    
    async def get_available_time_slots(
        self,
        calendar_id: str = "primary",
        start_date: str = "",
        end_date: str = "",
        duration_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """Get available time slots by checking calendar busy times."""
        try:
            headers = await self._get_auth_headers()
            
            # Get busy times
            params = {
                "timeMin": start_date,
                "timeMax": end_date
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.GOOGLE_API_BASE}/calendars/{calendar_id}/events",
                    headers=headers,
                    params=params
                )
                
                if response.status_code == 200:
                    events = response.json().get("items", [])
                    return self._calculate_available_slots(events, start_date, end_date, duration_minutes)
                else:
                    logger.error(f"Failed to get busy times: {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error getting available times: {e}")
            return []
    
    def _calculate_available_slots(
        self,
        events: List[Dict[str, Any]],
        start_date: str,
        end_date: str,
        duration_minutes: int
    ) -> List[Dict[str, Any]]:
        """Calculate available time slots from busy events."""
        # Simple implementation - can be enhanced
        available_slots = []
        
        # For now, return some default slots
        # This should be enhanced with actual calendar parsing
        from datetime import datetime, timedelta
        
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        
        current = start
        while current + timedelta(minutes=duration_minutes) <= end:
            available_slots.append({
                "start": current.isoformat(),
                "end": (current + timedelta(minutes=duration_minutes)).isoformat(),
                "duration_minutes": duration_minutes
            })
            current += timedelta(minutes=duration_minutes)
        
        return available_slots


# Singleton instance for enhanced Google Meet service
enhanced_google_meet_service = EnhancedGoogleMeetService()


# Legacy compatibility - update the original service
def update_google_meet_service():
    """Update the original google_meet_service with enhanced capabilities."""
    from backend.services.callback_service import google_meet_service
    
    # Replace create_meeting method
    original_create = google_meet_service.create_meeting
    
    async def enhanced_create(*args, **kwargs):
        # First try with OAuth
        result = await enhanced_google_meet_service.create_meeting(*args, **kwargs)
        if result.get("ok"):
            return result
        # Fallback to original (for testing)
        return await original_create(*args, **kwargs)
    
    google_meet_service.create_meeting = enhanced_create
    google_meet_service.get_event = enhanced_google_meet_service.get_event
    google_meet_service.update_event = enhanced_google_meet_service.update_event
    google_meet_service.delete_event = enhanced_google_meet_service.delete_event


# Update on import
update_google_meet_service()