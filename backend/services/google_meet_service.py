"""Google Calendar and Meet Service for Tenants.

Handles real Google Calendar event creation and Meet link generation using
per-tenant OAuth tokens stored in `token_storage.py`. Automatically refreshes
expired access tokens using stored refresh tokens.
"""

import json
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
from .token_storage import get_token, save_token

logger = logging.getLogger("google_meet_service")

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def generate_gcal_add_url(
    title: str,
    description: str,
    start_utc_compact: str,
    end_utc_compact: str,
    meet_link: Optional[str] = None,
) -> str:
    """Generate a direct 'Add to Google Calendar' web link."""
    details = f"{description}"
    if meet_link:
        details += f"\n\nJoin Google Meet: {meet_link}"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_utc_compact}/{end_utc_compact}",
        "details": details,
    }
    if meet_link:
        params["location"] = meet_link
    return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"


def _get_client_credentials() -> tuple[Optional[str], Optional[str]]:
    """Retrieve Google OAuth Client ID and Secret from environment."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    return client_id, client_secret


def refresh_access_token_sync(tenant_id: str, refresh_token: str) -> Optional[str]:
    """Synchronously refresh an expired Google OAuth access token."""
    client_id, client_secret = _get_client_credentials()
    if not client_id or not client_secret:
        logger.warning(
            f"Cannot refresh Google token for tenant {tenant_id}: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set"
        )
        return None

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                new_access_token = data.get("access_token")
                expires_in = data.get("expires_in", 3600)
                new_expires_at = int(time.time()) + int(expires_in)
                new_refresh_token = data.get("refresh_token") or refresh_token
                scope = data.get("scope")
                token_type = data.get("token_type", "Bearer")

                save_token(
                    tenant_id=tenant_id,
                    access_token=new_access_token,
                    refresh_token=new_refresh_token,
                    expires_at=new_expires_at,
                    token_type=token_type,
                    scope=scope,
                )
                logger.info(f"Google OAuth token refreshed successfully for tenant {tenant_id}")
                return new_access_token
            else:
                logger.error(
                    f"Failed to refresh Google token for tenant {tenant_id}: status={resp.status_code} body={resp.text}"
                )
    except Exception as exc:
        logger.error(f"Exception refreshing Google token for tenant {tenant_id}: {exc}")
    return None


async def refresh_access_token_async(tenant_id: str, refresh_token: str) -> Optional[str]:
    """Asynchronously refresh an expired Google OAuth access token."""
    client_id, client_secret = _get_client_credentials()
    if not client_id or not client_secret:
        logger.warning(
            f"Cannot refresh Google token for tenant {tenant_id}: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set"
        )
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                new_access_token = data.get("access_token")
                expires_in = data.get("expires_in", 3600)
                new_expires_at = int(time.time()) + int(expires_in)
                new_refresh_token = data.get("refresh_token") or refresh_token
                scope = data.get("scope")
                token_type = data.get("token_type", "Bearer")

                save_token(
                    tenant_id=tenant_id,
                    access_token=new_access_token,
                    refresh_token=new_refresh_token,
                    expires_at=new_expires_at,
                    token_type=token_type,
                    scope=scope,
                )
                logger.info(f"Google OAuth token refreshed successfully for tenant {tenant_id}")
                return new_access_token
            else:
                logger.error(
                    f"Failed to refresh Google token for tenant {tenant_id}: status={resp.status_code} body={resp.text}"
                )
    except Exception as exc:
        logger.error(f"Exception refreshing Google token for tenant {tenant_id}: {exc}")
    return None


def get_valid_access_token_sync(tenant_id: str) -> Optional[str]:
    """Get a valid access token for the tenant, refreshing if needed."""
    token_info = get_token(tenant_id)
    if not token_info:
        # Fallback to leewaysoftech if tenant not explicitly matched
        if tenant_id != "leewaysoftech":
            token_info = get_token("leewaysoftech")
        if not token_info:
            return None

    access_token = token_info.get("access_token")
    expires_at = token_info.get("expires_at", 0)
    refresh_token = token_info.get("refresh_token")

    # If token expires in less than 3 minutes, refresh it
    if time.time() >= (expires_at - 180):
        if refresh_token:
            refreshed = refresh_access_token_sync(tenant_id, refresh_token)
            if refreshed:
                return refreshed
        logger.warning(f"Google token for tenant {tenant_id} is expired and has no refresh token")

    return access_token


async def get_valid_access_token_async(tenant_id: str) -> Optional[str]:
    """Get a valid access token for the tenant asynchronously, refreshing if needed."""
    token_info = get_token(tenant_id)
    if not token_info:
        if tenant_id != "leewaysoftech":
            token_info = get_token("leewaysoftech")
        if not token_info:
            return None

    access_token = token_info.get("access_token")
    expires_at = token_info.get("expires_at", 0)
    refresh_token = token_info.get("refresh_token")

    if time.time() >= (expires_at - 180):
        if refresh_token:
            refreshed = await refresh_access_token_async(tenant_id, refresh_token)
            if refreshed:
                return refreshed
        logger.warning(f"Google token for tenant {tenant_id} is expired and has no refresh token")

    return access_token


def _build_event_payload(
    title: str,
    description: str,
    start_time: str,
    end_time: str,
    attendees: Optional[List[Dict[str, str]]],
    timezone: str,
) -> dict:
    conference_data = {
        "createRequest": {
            "requestId": secrets.token_hex(12),
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }
    return {
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


def _extract_meet_link(event: dict) -> Optional[str]:
    conference = event.get("conferenceData")
    if conference:
        for ep in conference.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                return ep.get("uri")
    return event.get("hangoutLink")


def _calculate_compact_utc(start_time: str, end_time: str) -> tuple[str, str]:
    try:
        from dateutil.parser import parse
        s_dt = parse(start_time) if start_time else datetime.now(timezone.utc)
        e_dt = parse(end_time) if end_time else (s_dt + timedelta(minutes=30))
        if not s_dt.tzinfo:
            s_dt = s_dt.replace(tzinfo=timezone.utc)
        if not e_dt.tzinfo:
            e_dt = e_dt.replace(tzinfo=timezone.utc)
        s_utc = s_dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        e_utc = e_dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return s_utc, e_utc
    except Exception:
        now_dt = datetime.now(timezone.utc)
        return now_dt.strftime("%Y%m%dT%H%M%SZ"), (now_dt + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%SZ")


def _create_via_service_account(
    sa_json: str,
    calendar_id: str,
    title: str,
    description: str,
    start_time: str,
    end_time: str,
    attendees: Optional[List[Dict[str, str]]],
    timezone: str,
) -> Optional[dict]:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_info = json.loads(sa_json) if sa_json.strip().startswith("{") else json.load(open(sa_json))
        credentials = service_account.Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/calendar"]
        )
        service = build("calendar", "v3", credentials=credentials)
        body = _build_event_payload(title, description, start_time, end_time, attendees, timezone)
        event = service.events().insert(calendarId=calendar_id, body=body, conferenceDataVersion=1).execute()
        meet_link = _extract_meet_link(event)
        return {
            "ok": True,
            "event_id": event.get("id"),
            "meet_link": meet_link,
            "html_link": event.get("htmlLink"),
            "start": start_time,
            "end": end_time,
            "calendar_id": calendar_id,
        }
    except Exception as exc:
        logger.warning(f"Service account calendar creation failed: {exc}")
        return None


def create_meeting_sync(
    tenant_id: str = "leewaysoftech",
    calendar_id: str = "primary",
    title: str = "Callback Meeting",
    description: str = "",
    start_time: str = "",
    end_time: str = "",
    attendees: Optional[List[Dict[str, str]]] = None,
    timezone: str = "Asia/Kolkata",
) -> Dict[str, Any]:
    """Synchronously create a Google Calendar event with Google Meet link.
    
    1. Uses the tenant's OAuth token from `token_storage.py` (with auto-refresh).
    2. Falls back to Service Account if configured.
    3. Returns real Meet link and Google Calendar add URL.
    """
    s_utc, e_utc = _calculate_compact_utc(start_time, end_time)

    # 1. Try Tenant OAuth Token
    access_token = get_valid_access_token_sync(tenant_id)
    if access_token:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        event_payload = _build_event_payload(title, description, start_time, end_time, attendees, timezone)
        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events?conferenceDataVersion=1"

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, headers=headers, json=event_payload)
                if resp.status_code in (200, 201):
                    event = resp.json()
                    meet_link = _extract_meet_link(event)
                    event_id = event.get("id")
                    cal_url = generate_gcal_add_url(title, description, s_utc, e_utc, meet_link)
                    logger.info(
                        f"REAL_GOOGLE_MEET_CREATED | tenant={tenant_id} | event_id={event_id} | meet={meet_link}"
                    )
                    return {
                        "ok": True,
                        "event_id": event_id,
                        "meet_link": meet_link,
                        "html_link": event.get("htmlLink"),
                        "calendar_add_url": cal_url,
                        "start": start_time,
                        "end": end_time,
                        "calendar_id": calendar_id,
                        "oauth_connected": True,
                    }
                elif resp.status_code == 401:
                    logger.warning(f"Google 401 Unauthorized for tenant {tenant_id}. Attempting token refresh...")
                    token_info = get_token(tenant_id)
                    if token_info and token_info.get("refresh_token"):
                        new_tok = refresh_access_token_sync(tenant_id, token_info["refresh_token"])
                        if new_tok:
                            headers["Authorization"] = f"Bearer {new_tok}"
                            retry_resp = client.post(url, headers=headers, json=event_payload)
                            if retry_resp.status_code in (200, 201):
                                event = retry_resp.json()
                                meet_link = _extract_meet_link(event)
                                event_id = event.get("id")
                                cal_url = generate_gcal_add_url(title, description, s_utc, e_utc, meet_link)
                                return {
                                    "ok": True,
                                    "event_id": event_id,
                                    "meet_link": meet_link,
                                    "html_link": event.get("htmlLink"),
                                    "calendar_add_url": cal_url,
                                    "start": start_time,
                                    "end": end_time,
                                    "calendar_id": calendar_id,
                                    "oauth_connected": True,
                                }
                logger.error(
                    f"Google Calendar API error for tenant {tenant_id}: status={resp.status_code} body={resp.text}"
                )
        except Exception as exc:
            logger.error(f"Error calling Google Calendar API for tenant {tenant_id}: {exc}")

    # 2. Fallback to Service Account if available
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        sa_res = _create_via_service_account(
            sa_json, calendar_id, title, description, start_time, end_time, attendees, timezone
        )
        if sa_res:
            sa_res["calendar_add_url"] = generate_gcal_add_url(title, description, s_utc, e_utc, sa_res.get("meet_link"))
            sa_res["oauth_connected"] = True
            return sa_res

    # 3. No OAuth configured: return calendar template add URL with clean status (NO FAKE MEET LINK)
    cal_url = generate_gcal_add_url(title, description, s_utc, e_utc, None)
    logger.info(
        f"Google OAuth not configured for tenant {tenant_id}. Returning calendar add template without meet link."
    )
    return {
        "ok": False,
        "error": "google_oauth_not_connected",
        "event_id": f"evt_{secrets.token_hex(8)}",
        "meet_link": None,
        "calendar_add_url": cal_url,
        "html_link": cal_url,
        "start": start_time,
        "end": end_time,
        "oauth_connected": False,
    }


async def create_meeting(
    tenant_id: str = "leewaysoftech",
    calendar_id: str = "primary",
    title: str = "Callback Meeting",
    description: str = "",
    start_time: str = "",
    end_time: str = "",
    attendees: Optional[List[Dict[str, str]]] = None,
    timezone: str = "Asia/Kolkata",
) -> Dict[str, Any]:
    """Asynchronous version of create_meeting_sync."""
    s_utc, e_utc = _calculate_compact_utc(start_time, end_time)

    access_token = await get_valid_access_token_async(tenant_id)
    if access_token:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        event_payload = _build_event_payload(title, description, start_time, end_time, attendees, timezone)
        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events?conferenceDataVersion=1"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=event_payload)
                if resp.status_code in (200, 201):
                    event = resp.json()
                    meet_link = _extract_meet_link(event)
                    event_id = event.get("id")
                    cal_url = generate_gcal_add_url(title, description, s_utc, e_utc, meet_link)
                    return {
                        "ok": True,
                        "event_id": event_id,
                        "meet_link": meet_link,
                        "html_link": event.get("htmlLink"),
                        "calendar_add_url": cal_url,
                        "start": start_time,
                        "end": end_time,
                        "calendar_id": calendar_id,
                        "oauth_connected": True,
                    }
                elif resp.status_code == 401:
                    token_info = get_token(tenant_id)
                    if token_info and token_info.get("refresh_token"):
                        new_tok = await refresh_access_token_async(tenant_id, token_info["refresh_token"])
                        if new_tok:
                            headers["Authorization"] = f"Bearer {new_tok}"
                            retry_resp = await client.post(url, headers=headers, json=event_payload)
                            if retry_resp.status_code in (200, 201):
                                event = retry_resp.json()
                                meet_link = _extract_meet_link(event)
                                event_id = event.get("id")
                                cal_url = generate_gcal_add_url(title, description, s_utc, e_utc, meet_link)
                                return {
                                    "ok": True,
                                    "event_id": event_id,
                                    "meet_link": meet_link,
                                    "html_link": event.get("htmlLink"),
                                    "calendar_add_url": cal_url,
                                    "start": start_time,
                                    "end": end_time,
                                    "calendar_id": calendar_id,
                                    "oauth_connected": True,
                                }
        except Exception as exc:
            logger.error(f"Error calling Google Calendar API async for tenant {tenant_id}: {exc}")

    # Fallback to Service Account if available
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        sa_res = _create_via_service_account(
            sa_json, calendar_id, title, description, start_time, end_time, attendees, timezone
        )
        if sa_res:
            sa_res["calendar_add_url"] = generate_gcal_add_url(title, description, s_utc, e_utc, sa_res.get("meet_link"))
            sa_res["oauth_connected"] = True
            return sa_res

    cal_url = generate_gcal_add_url(title, description, s_utc, e_utc, None)
    return {
        "ok": False,
        "error": "google_oauth_not_connected",
        "event_id": f"evt_{secrets.token_hex(8)}",
        "meet_link": None,
        "calendar_add_url": cal_url,
        "html_link": cal_url,
        "start": start_time,
        "end": end_time,
        "oauth_connected": False,
    }


def delete_event_sync(event_id: str, tenant_id: str = "leewaysoftech", calendar_id: str = "primary") -> bool:
    """Synchronously delete an event from Google Calendar."""
    access_token = get_valid_access_token_sync(tenant_id)
    if not access_token:
        return False
    try:
        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(url, headers=headers)
            return resp.status_code in (200, 204)
    except Exception as exc:
        logger.error(f"Failed to delete event {event_id} for tenant {tenant_id}: {exc}")
        return False


async def delete_event(event_id: str, tenant_id: str = "leewaysoftech", calendar_id: str = "primary") -> bool:
    """Asynchronously delete an event from Google Calendar."""
    access_token = await get_valid_access_token_async(tenant_id)
    if not access_token:
        return False
    try:
        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(url, headers=headers)
            return resp.status_code in (200, 204)
    except Exception as exc:
        logger.error(f"Failed to delete event {event_id} for tenant {tenant_id}: {exc}")
        return False
