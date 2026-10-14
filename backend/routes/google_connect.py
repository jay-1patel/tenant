"""Google Connect API Routes.

Provides endpoints for connecting Google OAuth accounts per tenant,
checking connection status, and handling the OAuth callback.
Used by frontend/src/components/tenants/google-connect-panel.tsx.
"""

import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from services.token_storage import get_token, save_token, delete_token

logger = logging.getLogger("google_connect")

router = APIRouter(tags=["google-connect"])

GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def _get_google_credentials() -> tuple[Optional[str], Optional[str]]:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    return client_id, client_secret


@router.get("/api/tenants/{tenant_id}/google-connect/status")
def get_google_connect_status(tenant_id: str):
    """Return whether the tenant has a valid Google OAuth connection."""
    token_info = get_token(tenant_id)
    if not token_info:
        return {
            "connected": False,
            "has_refresh_token": False,
            "token_expired": False,
            "scope": None,
        }

    now = time.time()
    expires_at = token_info.get("expires_at", 0)
    has_refresh = bool(token_info.get("refresh_token"))
    is_expired = now >= expires_at

    return {
        "connected": True,
        "has_refresh_token": has_refresh,
        "token_expired": is_expired,
        "scope": token_info.get("scope"),
        "expires_at": expires_at,
    }


@router.get("/api/tenants/{tenant_id}/google-connect/oauth-url")
def get_google_oauth_url(tenant_id: str, request: Request):
    """Generate the Google OAuth consent URL for a tenant."""
    client_id, _ = _get_google_credentials()
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth is not configured on the server. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the server environment (.env).",
        )

    # Determine redirect URI
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not redirect_uri:
        base = str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/api/tenants/google-connect/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": tenant_id,
        "include_granted_scopes": "true",
    }

    oauth_url = f"{GOOGLE_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {"oauth_url": oauth_url, "redirect_uri": redirect_uri}


@router.get("/api/tenants/google-connect/callback")
@router.get("/api/tenants/{tenant_id}/google-connect/callback")
async def google_oauth_callback(
    request: Request,
    tenant_id: Optional[str] = None,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Handle the OAuth 2.0 redirect from Google."""
    effective_tenant = tenant_id or state or "leewaysoftech"

    if error:
        logger.error(f"Google OAuth authorization error for tenant {effective_tenant}: {error}")
        html_error = f"""
        <html>
        <body style="font-family:sans-serif; text-align:center; padding:50px;">
            <h2>Google Connection Failed</h2>
            <p style="color:red;">Error: {error}</p>
            <p><a href="/?view=callbacks&tenant={effective_tenant}">Return to Dashboard</a></p>
        </body>
        </html>
        """
        return HTMLResponse(content=html_error, status_code=400)

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    client_id, client_secret = _get_google_credentials()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Server missing Google OAuth client credentials")

    # Determine redirect URI (must match the one used in the auth-url request)
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not redirect_uri:
        base = str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/api/tenants/google-connect/callback"

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )

        if token_resp.status_code != 200:
            logger.error(f"Failed to exchange OAuth code for tokens: {token_resp.text}")
            html_fail = f"""
            <html>
            <body style="font-family:sans-serif; text-align:center; padding:50px;">
                <h2>Failed to connect Google account</h2>
                <p style="color:red;">Google API returned: {token_resp.status_code}</p>
                <p><a href="/?view=callbacks&tenant={effective_tenant}">Return to Dashboard</a></p>
            </body>
            </html>
            """
            return HTMLResponse(content=html_fail, status_code=400)

        data = token_resp.json()
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)
        expires_at = int(time.time()) + int(expires_in)
        token_type = data.get("token_type", "Bearer")
        scope = data.get("scope")

        # Preserve existing refresh token if Google didn't issue a new one
        if not refresh_token:
            old_token = get_token(effective_tenant)
            if old_token and old_token.get("refresh_token"):
                refresh_token = old_token["refresh_token"]

        saved = save_token(
            tenant_id=effective_tenant,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            token_type=token_type,
            scope=scope,
        )

        if not saved:
            raise HTTPException(status_code=500, detail="Failed to save Google OAuth tokens to database")

        logger.info(f"Google account connected successfully for tenant: {effective_tenant}")

    html_success = f"""
    <html>
    <head>
        <title>Google Account Connected</title>
        <script>
            setTimeout(function() {{
                window.location.href = "/?view=callbacks&tenant={effective_tenant}&success=true";
            }}, 1500);
        </script>
    </head>
    <body style="font-family:sans-serif; text-align:center; padding:50px;">
        <h2 style="color:green;">Google Account Connected Successfully!</h2>
        <p>Google Meet and Google Calendar are now enabled for callbacks.</p>
        <p>Redirecting you back to your dashboard...</p>
        <p><a href="/?view=callbacks&tenant={effective_tenant}&success=true">Click here if not redirected automatically</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_success)


@router.post("/api/tenants/{tenant_id}/google-connect/disconnect")
def disconnect_google_account(tenant_id: str):
    """Disconnect Google OAuth account for a tenant."""
    deleted = delete_token(tenant_id)
    if deleted:
        logger.info(f"Google account disconnected for tenant: {tenant_id}")
        return {"status": "disconnected", "tenant_id": tenant_id}
    raise HTTPException(status_code=500, detail="Failed to disconnect Google account")
