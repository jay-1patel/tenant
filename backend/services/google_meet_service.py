import logging
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .token_storage import get_token

logger = logging.getLogger(__name__)


async def create_meeting(
    tenant_id: str,
    calendar_id: str = "primary",
    title: str = "Callback Meeting",
    description: str = "",
    start_time: str = "",
    end_time: str = "",
    attendees: Optional[List[Dict[str, str]]] = None,
    timezone: str = "Asia/Kolkata",
) -> Dict[str, Any]:
    """Create a Google Calendar event with a Meet link for a specific tenant.

    The function retrieves a stored OAuth access token for the tenant from
    ``token_storage``. It assumes the token is valid; refresh handling can be
    added later if needed.
    """
    token_info = get_token(tenant_id)
    if not token_info:
        logger.error(f"No Google OAuth token found for tenant {tenant_id}")
        return {"ok": False, "error": "OAuth token not configured for tenant"}

    access_token = token_info.get("access_token")
    if not access_token:
        logger.error(f"OAuth token missing access_token for tenant {tenant_id}")
        return {"ok": False, "error": "Access token missing"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    conference_data = {
        "createRequest": {
            "requestId": __import__("secrets").token_hex(12),
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }

    event_data = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_time, "timeZone": timezone},
        "end": {"dateTime": end_time, "timeZone": timezone},
        "attendees": attendees or [],
        "conferenceData": conference_data,
        "reminders": {
            "useDefault": True,
            "overrides": [
                {"method": "email", "minutes": 24 * 60},
                {"method": "email", "minutes": 15},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events?conferenceDataVersion=1"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=event_data)
        if response.status_code in (200, 201):
            event = response.json()
            meet_link = None
            conference = event.get("conferenceData")
            if conference:
                for ep in conference.get("entryPoints", []):
                    if ep.get("entryPointType") == "video":
                        meet_link = ep.get("uri")
                        break
            if not meet_link:
                meet_link = event.get("hangoutLink")
            return {
                "ok": True,
                "event_id": event.get("id"),
                "meet_link": meet_link,
                "html_link": event.get("htmlLink"),
                "start": event.get("start", {}).get("dateTime"),
                "end": event.get("end", {}).get("dateTime"),
                "calendar_id": calendar_id,
            }
        else:
            logger.error(
                f"Failed to create Google Meet event for tenant {tenant_id}: {response.text}"
            )
            return {"ok": False, "error": response.text, "status_code": response.status_code}
