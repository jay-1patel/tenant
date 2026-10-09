"""
WhatsApp Integration Layer for send2.digital CPaaS API.

This module supports both the OLD API (List Menus) and NEW Unified API (Text, Media, Buttons).
- OLD API: Used for large menus (>3 options) that require list format
- NEW API: Used for text, media, and interactive buttons (max 3 buttons)

Key distinction:
- OLD API uses 'number' field for contact
- NEW API uses 'contact_no' field for contact
"""

import json
import os
import re
from typing import List, Dict, Optional
import httpx
import httpx  # FIX: Missing import for legacy sync functions

from ..database import get_db, get_db_context, is_session_open, update_session_outbound
from routing.config import (
    SEND2_USERNAME,
    SEND2_PASSWORD,
    SEND2_SESSION_MSG_URL,
    SEND2_NUMBER,
    SEND2_INCOMING_URL,
    SEND2_SESSION_SEND_URL,
    SEND2_LIST_MENU_URL,
    SEND2_QUICK_BUTTON_URL,
    SEND2_MEDIA_URL,
    BUSINESS_NAME,
    BOT_NAME,
    WELCOME_MESSAGE,
    MENU_HEADER,
    MENU_BODY,
    MENU_FOOTER,
    SIGNATURE,
    TEMPLATE_PREFIX,
    logger,
)

# ============================================
# API ENDPOINT CONSTANTS
# ============================================

# OFFICIAL send2.digital API Endpoints (sourced from .env via routing.config)
LIST_MENU_URL = SEND2_LIST_MENU_URL
QUICK_BUTTON_URL = SEND2_QUICK_BUTTON_URL
# Session/unified outgoing messages (text, media) are sent to the
# session-msg-send endpoint, which is the one that authenticates this account
# (user_name + contact_no) and reaches the send stage. The old incoming-report
# URL (/devdesk/incoming-report) is a report API and rejects sends with
# "Please provide Username".
SESSION_MSG_URL = SEND2_SESSION_SEND_URL

# Legacy endpoints (kept for backward compatibility)
# SEND2_INCOMING_URL and SEND2_MEDIA_URL are imported from routing.config


# ============================================
# BASE REQUEST HELPERS
# ============================================

def _inject_credentials(payload: dict) -> dict:
    """Inject send2.digital credentials into payload."""
    payload["username"] = SEND2_USERNAME
    payload["password"] = SEND2_PASSWORD
    return payload


async def _send_post_request(url: str, payload: dict, timeout: int = 30) -> dict:
    """
    Base async helper for POST httpx to send2.digital API.

    Args:
        url: API endpoint URL
        payload: Request payload (credentials will be injected)
        timeout: Request timeout in seconds

    Returns:
        dict: Response JSON data

    Raises:
        httpx.HTTPError: If request fails
    """
    payload = _inject_credentials(payload)

    logger.info(f"API_REQUEST | url={url} | timeout={timeout} | payload_preview={str(payload)[:200]}")

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            result = response.json()
            logger.info(f"API_RESPONSE | status={response.status_code} | success={result.get('success', True)}")
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"API_ERROR | status={e.response.status_code} | body={e.response.text[:300]}")
            raise
        except httpx.RequestError as e:
            logger.error(f"API_NETWORK_ERROR | error={e}")
            raise


def _send_post_request_sync(url: str, payload: dict, timeout: int = 30) -> dict:
    """
    Synchronous version of POST request helper for backward compatibility.

    Args:
        url: API endpoint URL
        payload: Request payload (credentials will be injected)
        timeout: Request timeout in seconds

    Returns:
        dict: Response JSON data
    """
    # Use httpx for consistency with async functions
    payload = _inject_credentials(payload)

    logger.info(f"API_REQUEST_SYNC | url={url} | timeout={timeout} | payload_preview={str(payload)[:200]}")

    try:
        response = httpx.post(url, json=payload, timeout=timeout)
        response.raise_for_status()

        result = response.json()
        logger.info(f"API_RESPONSE_SYNC | status={response.status_code} | success={result.get('success', True)}")
        return result

    except httpx.HTTPStatusError as e:
        logger.error(f"API_ERROR_SYNC | status={e.response.status_code} | body={e.response.text[:300]}")
        raise
    except httpx.RequestError as e:
        logger.error(f"API_NETWORK_ERROR | error={e}")
        raise


# ============================================
# BUTTON BUILDER HELPER (NEW API)
# ============================================

def build_button(id: str = None, title: str = None, url: str = None) -> dict:
    """
    Build a button for the NEW API interactive messages.

    Args:
        id: Button ID for reply buttons
        title: Button display text (required for both types)
        url: URL for URL buttons (optional)

    Returns:
        dict: Button object in NEW API format

    Raises:
        ValueError: If parameters are invalid

    Examples:
        # Reply button
        build_button(id="download", title="Download")
        # Returns: {"type": "reply", "reply": {"id": "download", "title": "Download"}}

        # URL button
        build_button(title="Visit Website", url="https://example.com")
        # Returns: {"type": "url", "url": {"display_text": "Visit Website", "url": "https://example.com"}}
    """
    if not title:
        raise ValueError("Button title is required")

    if url:
        # URL button
        return {
            "type": "url",
            "url": {
                "display_text": title,
                "url": url
            }
        }
    elif id:
        # Reply button
        return {
            "type": "reply",
            "reply": {
                "id": id,
                "title": title
            }
        }
    else:
        raise ValueError("Either 'id' (for reply) or 'url' (for URL button) must be provided")


# ============================================
# NEW API: UNIFIED MESSAGE SENDERS
# ============================================

async def send_text_message(contact_no: str, text: str) -> bool:
    """
    Send text message using NEW API.

    Args:
        contact_no: WhatsApp number (with country code, no spaces/dashes)
        text: Message text

    Returns:
        bool: True if successful, False otherwise

    Example:
        success = await send_text_message("919876543210", "Hello from our bot!")
    """
    if not text or not text.strip():
        logger.warning("Empty text message, skipping send")
        return False

    # Normalize formatting + append the tenant's signature
    text = format_for_whatsapp(text, contact_no)

    # FIX: Build payload with credentials included
    payload = {
        "user_name": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "contact_no": contact_no,
        "message_type": "text",
        "message": text
    }

    try:
        # FIX: Use direct httpx call without _send_post_request to avoid double credentials
        logger.info(f"API_REQUEST | url={SESSION_MSG_URL} | timeout=30 | payload_preview={str(payload)[:200]}")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(SESSION_MSG_URL, json=payload)
            logger.info(f"API_RESPONSE | status={response.status_code} | body={response.text[:300]}")

            if response.status_code == 200:
                try:
                    update_session_outbound(contact_no)
                except Exception:
                    pass

                logger.info(f"TEXT_SENT | to={contact_no} | chars={len(text)}")
                return True
            else:
                logger.error(f"TEXT_SEND_FAILED | to={contact_no} | status={response.status_code} | body={response.text[:300]}")
                return False

    except Exception as e:
        logger.error(f"TEXT_SEND_FAILED | to={contact_no} | error={e}")
        return False


async def send_media_message(contact_no: str, media_type: str, media_url: str, caption: str = None) -> bool:
    """
    Send media message (image/video/document) using NEW API.

    Args:
        contact_no: WhatsApp number (with country code)
        media_type: Media type - "image", "video", or "document"
        media_url: Public URL of the media file
        caption: Optional caption text for the media

    Returns:
        bool: True if successful, False otherwise

    Example:
        success = await send_media_message("919876543210", "image", "https://example.com/product.jpg")
    """
    if media_type not in ("image", "video", "document"):
        raise ValueError(f"Invalid media_type: {media_type}. Must be 'image', 'video', or 'document'")

    # Direct media (image/video/document) sends are disabled for the bot.
    # Only text and interactive button/list messages are sent; messages with
    # an image header are delivered through send_interactive_buttons instead.
    logger.info(f"MEDIA_SEND_DISABLED | to={contact_no} | type={media_type} | url={str(media_url)[:120]}")
    return False


async def send_button_message(
    contact_no: str,
    body_text: str,
    buttons: List[dict],
    header_media: dict = None,
    footer_text: str = None
) -> bool:
    """
    Send interactive button message using NEW API.

    Args:
        contact_no: WhatsApp number (with country code)
        body_text: Main message body text
        buttons: List of button objects created by build_button() (max 3)
        header_media: Optional header media dict like:
            {"type": "image", "image": {"link": "https://..."}}
            {"type": "video", "video": {"link": "https://..."}}
            {"type": "document", "document": {"link": "https://...", "filename": "file.pdf"}}
        footer_text: Optional footer text

    Returns:
        bool: True if successful, False otherwise

    Note:
        WhatsApp limits interactive buttons to maximum 3 per message.
        For menus with >3 options, use send_list_menu() with OLD API instead.

    Example:
        buttons = [
            build_button(id="download", title="Download Brochure"),
            build_button(title="Visit Website", url="https://example.com")
        ]
        success = await send_button_message("919876543210", "Choose an option:", buttons)
    """
    if not buttons or len(buttons) == 0:
        logger.warning("No buttons provided, falling back to text message")
        return await send_text_message(contact_no, body_text)

    if len(buttons) > 3:
        logger.warning(f"Too many buttons ({len(buttons)}), limiting to 3")
        buttons = buttons[:3]

    # Normalize formatting + append the tenant's signature to the button message body
    body_text = format_for_whatsapp(body_text, contact_no)

    # Primary path: session-msg-send Cloud interactive API — ONE call carrying
    # optional media header + body + footer + buttons together.
    # (The Quick Button endpoint does not support media headers and uses a
    # legacy payload shape, so it is kept only as a fallback below.)
    # NOTE: footer must be a NON-EMPTY string, otherwise send2.digital
    # rejects the whole request with {"error":"INVALID PARAMETER"}.
    cloud_buttons = []
    for btn in buttons[:3]:
        if isinstance(btn, dict) and btn.get("type") in ("reply", "url"):
            cloud_buttons.append(btn)
    if not cloud_buttons:
        cloud_buttons = [build_button(id=f"btn_{i+1}", title=str(b)) for i, b in enumerate(buttons[:3])]

    interactive_body = {
        "type": "button",
        "body": {"text": body_text},
        "footer": {"text": footer_text or " "},
        "action": {"buttons": cloud_buttons},
    }
    if header_media and isinstance(header_media, dict):
        header_type = header_media.get("type")
        media_obj = header_media.get(header_type) if header_type else None
        if header_type in ("image", "video", "document") and isinstance(media_obj, dict) and media_obj.get("link"):
            if header_type == "document":
                interactive_body["header"] = {"type": "document", "document": {
                    "link": media_obj["link"],
                    **({"filename": media_obj["filename"]} if media_obj.get("filename") else {}),
                }}
            else:
                interactive_body["header"] = {"type": header_type, header_type: {"link": media_obj["link"]}}

    cloud_payload = {
        "user_name": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "contact_no": contact_no,
        "message_type": "interactive",
        "interactive": interactive_body,
    }
    try:
        logger.info(f"API_REQUEST | url={SESSION_MSG_URL} (cloud interactive)")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(SESSION_MSG_URL, json=cloud_payload)
        logger.info(f"API_RESPONSE | status={response.status_code} | body={response.text[:300]}")
        low = response.text.lower()
        accepted = (
            response.status_code == 200
            and "invalid parameter" not in low
            and "unexpected server error" not in low
            and "interactive payload is required" not in low
        )
        # Note: "user has OPT OUT" means the payload was ACCEPTED and the
        # pipeline reached the delivery stage — format is proven correct.
        opted_out = "opt out" in low
        if accepted:
            if not opted_out:
                try:
                    update_session_outbound(contact_no)
                except Exception:
                    pass
            logger.info(
                f"BUTTON_MESSAGE_SENT | to={contact_no} | buttons={len(cloud_buttons)} | "
                f"media_header={'yes' if 'header' in interactive_body else 'no'} | "
                f"delivered={'no (recipient opted out)' if opted_out else 'yes'}"
            )
            return True
        logger.warning(f"Cloud interactive send failed ({response.status_code}), falling back to quick-button endpoint")
    except Exception as e:
        logger.warning(f"Cloud interactive send error: {e}, falling back to quick-button endpoint")

    # Fallback: Quick Button endpoint (text header only, no media).
    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": contact_no,
        "headertype": "text",
        "headertext": " ",
        "bodytext": body_text,
        "footertext": footer_text or " ",
        "total_buttons": len(buttons),
        "buttons": buttons,
    }

    try:
        logger.info(f"API_REQUEST | url={QUICK_BUTTON_URL} | timeout=30 | payload_preview={str(payload)[:200]}")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(QUICK_BUTTON_URL, json=payload)
            logger.info(f"API_RESPONSE | status={response.status_code} | body={response.text[:300]}")

            if response.status_code == 200:
                try:
                    update_session_outbound(contact_no)
                except Exception:
                    pass

                logger.info(f"BUTTON_MESSAGE_SENT | to={contact_no} | buttons={len(buttons)}")
                return True
            else:
                logger.error(f"BUTTON_MESSAGE_FAILED | to={contact_no} | status={response.status_code} | body={response.text[:300]}")
                return False

    except Exception as e:
        logger.error(f"BUTTON_MESSAGE_FAILED | to={contact_no} | error={e}")
        return False


# ============================================
# OLD API: LIST MENU SENDER (>3 options)
# ============================================

async def send_list_menu(
    contact_no: str,
    header_text: str,
    body_text: str,
    button_text: str,
    sections: List[dict],
    footer_text: str = None
) -> bool:
    """
    Send list menu message using OLD API (>3 options support).

    Args:
        contact_no: WhatsApp number (with country code)
        header_text: Menu header/title text
        body_text: Menu body/description text
        button_text: Button text (e.g., "View Options")
        sections: List of section dicts with format:
            [{"title": "Section 1", "rows": [{"id": "1", "title": "Option 1", "description": "..."}, ...]}]
        footer_text: Optional footer text

    Returns:
        bool: True if successful, False otherwise

    Note:
        OLD API uses 'number' field instead of 'contact_no'.
        Use this for menus with more than 3 options that can't fit in interactive buttons.

    Example:
        sections = [{
            "title": "Products",
            "rows": [
                {"id": "1", "title": "Product A", "description": "Description A"},
                {"id": "2", "title": "Product B", "description": "Description B"}
            ]
        }]
        success = await send_list_menu("919876543210", "Our Products", "Browse below:", "View", sections)
    """
    if not sections or len(sections) == 0:
        logger.warning("No sections provided, cannot send list menu")
        return False

    # Normalize formatting + append the tenant's signature to the menu body text
    body_text = format_for_whatsapp(body_text, contact_no)

    # FIX: Transform sections structure to match OFFICIAL send2.digital API format
    # Based on official docs: sections use "title" and rows use "id", "title", "description"
    api_sections = []
    for section in sections:
        api_section = {
            "title": section.get("title", ""),  # API expects 'title'
            "rows": []
        }

        for row in section.get("rows", []):
            api_row = {
                "id": row.get("id", ""),              # API expects 'id'
                "title": row.get("title", ""),        # API expects 'title'
                "description": row.get("description", "")  # API expects 'description'
            }
            api_section["rows"].append(api_row)

        api_sections.append(api_section)

    # FIX: Build payload with CORRECT send2.digital field names from official documentation
    payload = {
        "username": SEND2_USERNAME,     # ✅ CORRECT: API expects 'username' not 'user_name'
        "password": SEND2_PASSWORD,
        "number": contact_no,
        "headertext": header_text or " ",  # ✅ non-empty required by send2
        "bodytext": body_text or " ",      # ✅ non-empty required by send2
        "footertext": footer_text or " ",  # ✅ non-empty required by send2
        "buttontext": button_text or "Menu",  # ✅ non-empty required by send2
        "total_number_section": len(api_sections),
        "total_rows": sum(len(section.get("rows", [])) for section in api_sections),
        "sections": api_sections         # ✅ Use sections with correct field names
    }

    try:
        # FIX: Use direct httpx call instead of _send_post_request to avoid double credential injection
        logger.info(f"API_REQUEST | url={LIST_MENU_URL} | timeout=30 | payload_preview={str(payload)[:200]}")
        logger.debug(f"FULL LIST_MENU_PAYLOAD: {json.dumps(payload, indent=2)}")  # DEBUG: Log full payload

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(LIST_MENU_URL, json=payload)
            logger.info(f"API_RESPONSE | status={response.status_code} | body={response.text[:300]}")

            if response.status_code == 200:
                try:
                    update_session_outbound(contact_no)
                except Exception:
                    pass

                logger.info(f"LIST_MENU_SENT | to={contact_no} | sections={len(api_sections)} | rows={sum(len(section.get('rows', [])) for section in api_sections)}")
                return True
            else:
                logger.error(f"LIST_MENU_FAILED | to={contact_no} | status={response.status_code} | body={response.text[:300]}")

                # DEBUG: Log detailed error information
                logger.error(f"FAILED_REQUEST_DETAILS | url={LIST_MENU_URL} | payload_keys={list(payload.keys())} | sections_count={len(api_sections)}")
                if api_sections and len(api_sections) > 0:
                    logger.error(f"FIRST_API_SECTION | {str(api_sections[0])[:300]}")

                return False

    except Exception as e:
        logger.error(f"LIST_MENU_FAILED | to={contact_no} | error={e}")
        return False


async def send_quick_button_message(
    number: str,
    header_text: str,
    body_text: str,
    footer_text: str,
    buttons: List[dict]
) -> bool:
    """
    Send interactive button message using OFFICIAL send2.digital Quick Button API.

    Args:
        number: WhatsApp number (with country code)
        header_text: Header text
        body_text: Main message body text
        footer_text: Footer text
        buttons: List of button objects with format:
            [{"type": "reply", "reply": {"id": "btn1", "title": "Button 1"}}, ...]

    Returns:
        bool: True if successful, False otherwise

    Note:
        Max 3 buttons allowed per message.
        Uses the official send2.digital session_msg_quickbtn endpoint.

    Example:
        buttons = [
            {"type": "reply", "reply": {"id": "download", "title": "Download"}},
            {"type": "reply", "reply": {"id": "cancel", "title": "Cancel"}}
        ]
        success = await send_quick_button_message("919876543210", "Header", "Body text", "Footer", buttons)
    """
    if not buttons or len(buttons) == 0:
        logger.warning("No buttons provided, cannot send quick button message")
        return False

    if len(buttons) > 3:
        logger.warning(f"Too many buttons ({len(buttons)}), limiting to 3")
        buttons = buttons[:3]

    # Build payload with OFFICIAL send2.digital field names.
    # NOTE: headertext and footertext must be NON-EMPTY strings, otherwise
    # send2.digital rejects the whole request with {"error":"INVALID PARAMETER"}.
    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": number,
        "headertype": "text",
        "headertext": header_text or " ",
        "bodytext": body_text,
        "footertext": footer_text or " ",
        "total_buttons": len(buttons),
        "buttons": buttons
    }

    try:
        logger.info(f"API_REQUEST | url={QUICK_BUTTON_URL} | timeout=30 | payload_preview={str(payload)[:200]}")
        logger.debug(f"FULL BUTTON_PAYLOAD: {json.dumps(payload, indent=2)}")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(QUICK_BUTTON_URL, json=payload)
            logger.info(f"API_RESPONSE | status={response.status_code} | body={response.text[:300]}")

            if response.status_code == 200:
                try:
                    update_session_outbound(number)
                except Exception:
                    pass

                logger.info(f"QUICK_BUTTON_SENT | to={number} | buttons={len(buttons)}")
                return True
            else:
                logger.error(f"QUICK_BUTTON_FAILED | to={number} | status={response.status_code} | body={response.text[:300]}")
                return False

    except Exception as e:
        logger.error(f"QUICK_BUTTON_FAILED | to={number} | error={e}")
        return False


# ============================================
# UTILITY FUNCTIONS
# ============================================

def _tenant_signature(wa_id: str = "") -> str:
    """The closing signature of the tenant that owns this conversation.

    Resolved from the tenant's profile (the per-tenant data layer), keyed by
    the recipient's WhatsApp number. The legacy env SIGNATURE is only a
    fallback for deployments with no profile layer at all; when a profile
    exists its value wins, including an empty one.
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[2])
        if root not in _sys.path:
            _sys.path.insert(0, root)

        from shared.tenancy import loader
        from shared.tenancy.resolver import resolve_tenant_for_user

        profile = loader.get_tenant_profile(resolve_tenant_for_user(wa_id))
        return profile.brand.signature
    except Exception:  # defensive: sending must never fail over branding
        return SIGNATURE or ""


def append_signature(text: str, wa_id: str = "") -> str:
    """Append the owning tenant's signature to a message unless already present."""
    signature = _tenant_signature(wa_id)
    if not signature:
        return text or ""
    text = text or ""
    if signature in text:
        return text
    return text.rstrip() + f"\n\n--- {signature}"


def normalize_whatsapp_formatting(text: str) -> str:
    """
    Normalize Markdown-ish emphasis so WhatsApp renders it as true bold/italic
    (native *bold* / _italic_) instead of showing literal asterisks.

    - **bold**  -> *bold*   (WhatsApp bold)
    - _italic_ already works, but `__italic__` / `**...**` are collapsed.
    - Trailing single/double asterisks on their own line are dropped.

    Single-asterisk WhatsApp formatting (*bold* / _italic_) is preserved.
    """
    if not text:
        return text or ""
    # Markdown bold / strong -> WhatsApp bold (single asterisk)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Markdown italic underscores -> WhatsApp italic already; leave as is.
    return text


def format_for_whatsapp(text: str, wa_id: str = "") -> str:
    """Apply formatting normalization + the tenant's signature to a message body."""
    if not text:
        return ""
    text = normalize_whatsapp_formatting(text)
    return append_signature(text, wa_id)


def _send2_response_ok(resp) -> bool:
    """send2 often returns HTTP 200 with an error string body — treat those as failure."""
    if resp is None or resp.status_code != 200:
        return False

    body = (resp.text or "").strip()
    lower = body.lower()

    hard_fail = (
        "invalid message type",
        "opt out",
        "unable to send",
        '"success":false',
        '"success": false',
        "error",
        "failed",
    )

    # More lenient: only treat explicit failures as errors
    if any(m in lower for m in hard_fail):
        # Double-check that it's actually an error, not just containing these words
        explicit_errors = ("invalid message type", "opt out", "unable to send", "request failed")
        if any(e in lower for e in explicit_errors):
            return False

    try:
        data = resp.json()
        if isinstance(data, dict):
            # Only treat explicit success:false as failure
            if data.get("success") is False and not data.get("message"):
                return False
            # Treat explicit error status as failure
            if data.get("status") == "error" and data.get("message"):
                return False
            # Accept success:true or any other response
            if data.get("success") is True:
                return True
            # If we got valid JSON but unclear status, assume success for 200
            return True
    except (ValueError, TypeError):
        pass

    # plain error phrases (non-JSON) - be more specific
    if lower.startswith("we sorry") or lower.startswith("invalid ") or lower == "failed":
        return False

    # For HTTP 200 with no clear error, assume success
    return True


def resolve_public_media_url(media_url: str) -> Optional[str]:
    """
    Turn any stored media path into a public HTTPS URL WhatsApp can fetch.

    FIX: Uses native file extension checking instead of undefined variables.
    Handles all file types properly: images, PDFs, documents, etc.

    Resolution order:
    1. Already public HTTPS URL → return as-is
    2. Cached host URL in database → use cached URL
    3. Upload to external service (imghippo for images, catbox for others)
    4. Construct using PUBLIC_BASE_URL as fallback

    Args:
        media_url: Media URL or local path to resolve

    Returns:
        Public HTTPS URL or None if resolution fails
    """
    if not media_url:
        return None
    if media_url.startswith("https://") or media_url.startswith("http://"):
        return media_url

    from routing.config import UPLOAD_DIR
    import routing.config as config
    import mimetypes

    local_path = None
    stored_name = None

    if media_url.startswith("/media/serve/"):
        parts = media_url.split("/")
        if len(parts) >= 5:
            subdir, stored_name = parts[3], parts[4]
            local_path = os.path.join(UPLOAD_DIR, subdir, stored_name)
    elif os.path.isfile(media_url):
        local_path = media_url
        stored_name = os.path.basename(media_url)
    else:
        potential = os.path.join(UPLOAD_DIR, media_url.lstrip("/"))
        if os.path.isfile(potential):
            local_path = potential
            stored_name = os.path.basename(potential)

    if stored_name:
        pass  # media table removed; local path resolution handled below

    if local_path and os.path.isfile(local_path):
        # FIX: Use native file extension checking instead of undefined variables
        file_ext = os.path.splitext(local_path)[1].lower()

        # Determine if it's an image or PDF
        is_image = file_ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
        is_pdf = file_ext == ".pdf"  # FIX: Direct file extension check, no undefined variable

        # Only upload images and PDFs to external services
        if is_image or is_pdf:
            uploaded = _upload_image_file(local_path)
            if uploaded:
                return uploaded

    if media_url.startswith("/media/serve/") and config.PUBLIC_BASE_URL:
        return f"{config.PUBLIC_BASE_URL}{media_url}"

    return None


def _upload_image_file(file_path: str) -> Optional[str]:
    """Upload local file to imghippo/catbox. Returns URL or None."""
    from routing.config import IMGHIPPO_API_KEY

    ext = os.path.splitext(file_path)[1].lower()
    is_image = ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")

    # 1. imghippo (images only)
    if IMGHIPPO_API_KEY and is_image:
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            resp = httpx.post(
                "https://api.imghippo.com/v1/upload",
                data={"api_key": IMGHIPPO_API_KEY},
                files={
                    "file": (
                        os.path.basename(file_path),
                        file_bytes,
                        "application/octet-stream",
                    )
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    url = data["data"]["url"]
                    logger.info(f"upload_image: imghippo -> {url}")
                    return url
                logger.warning(f"upload_image: imghippo rejected: {resp.status_code} {resp.text[:120]}")
        except Exception as e:
            logger.error(f"upload_image: imghippo failed: {e}")
    else:
        if not IMGHIPPO_API_KEY:
            logger.warning("upload_image: IMGHIPPO_API_KEY not set, skipping imghippo")
        else:
            logger.info(f"upload_image: skipping imghippo for non-image file ({ext})")

    # 2. Catbox.moe (fallback)
    try:
        with open(file_path, "rb") as f:
            resp = httpx.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (os.path.basename(file_path), f)},
                timeout=60,
            )
            if resp.status_code == 200 and resp.text.strip().startswith("http"):
                url = resp.text.strip()
                logger.info(f"upload_image: catbox.moe -> {url}")
                return url
            logger.warning(f"upload_image: catbox rejected: {resp.status_code} {resp.text[:120]}")
    except Exception as e:
        logger.error(f"upload_image: catbox.moe failed: {e}")

    # 3. 0x0.st (fallback)
    try:
        with open(file_path, "rb") as f:
            resp = httpx.post(
                "https://0x0.st",
                files={"file": f},
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200 and resp.text.strip().startswith("http"):
                url = resp.text.strip()
                logger.info(f"upload_image: 0x0.st -> {url}")
                return url
    except Exception as e:
        logger.error(f"upload_image: 0x0.st failed: {e}")

    # 4. data URL only useful if send2 accepts it (last resort, small files)
    try:
        file_size = os.path.getsize(file_path)
        if file_size < 2 * 1024 * 1024:
            with open(file_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(file_path)[1].lower()
            mime = {
                "webp": "image/webp",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "png": "image/png",
                "gif": "image/gif",
            }.get(ext, "image/jpeg")
            return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.error(f"upload_image: base64 failed: {e}")

    return None


# ============================================
# BACKWARD COMPATIBILITY WRAPPERS
# ============================================

# These functions maintain backward compatibility with existing code
# They map old function names to the new API functions

def send_whatsapp_message(to, text, message_type="text"):
    """Legacy wrapper - maps to NEW API send_text_message."""
    # Direct media sends are disabled for the bot; only text is supported here.
    if message_type != "text":
        logger.info(f"MEDIA_SEND_DISABLED | to={to} | type={message_type} | url={str(text)[:120]}")
        return False
    # This is kept for synchronous compatibility
    import asyncio
    import threading

    def run_async():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(send_text_message(to, text))
        finally:
            loop.close()

    # FIX: Check if event loop is running correctly
    try:
        loop = asyncio.get_event_loop()
        is_running = loop.is_running()
    except RuntimeError:
        # No event loop exists
        is_running = False

    if is_running:
        # If we're in an async context, we can't use run_until_complete
        # Fall back to sync implementation
        text = format_for_whatsapp(text, to)
        payload = {
            "user_name": SEND2_USERNAME,
            "password": SEND2_PASSWORD,
            "contact_no": to,
            "message_type": "text",
            "message": text,
        }

        msg_preview = text[:100] + "..." if len(str(text)) > 100 else text
        logger.info(f"OUTGOING (LEGACY) | to={to} | type=text | msg={msg_preview}")

        return _send_whatsapp_sync(to, payload, "text")
    else:
        # Run in background thread
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
        return True


def _send_whatsapp_sync(to, payload, message_type):
    """Legacy synchronous sender for backward compatibility."""
    timeout_val = 120 if message_type in ("document", "image", "video", "audio") else 30
    try:
        resp = httpx.post(SEND2_SESSION_SEND_URL, json=payload, timeout=timeout_val)
        ok = _send2_response_ok(resp)
        logger.info(
            f"OUTGOING_RESULT | to={to} | status={resp.status_code} | ok={ok} | resp={resp.text[:200]}"
        )
        if ok:
            try:
                update_session_outbound(to)
            except Exception:
                pass
        return ok
    except Exception as e:
        logger.error(f"OUTGOING_FAILED | to={to} | error={e}")
        return False


def send_image(to: str, media_url: str) -> bool:
    """Legacy wrapper — direct image sends are disabled for the bot."""
    logger.info(f"MEDIA_SEND_DISABLED | to={to} | type=image | url={str(media_url)[:120]}")
    return False


def send_video(to: str, video_url: str) -> bool:
    """Legacy wrapper — direct media sends are disabled for the bot."""
    logger.info(f"MEDIA_SEND_DISABLED | to={to} | type=video | url={str(video_url)[:120]}")
    return False


def send_audio(to: str, audio_url: str) -> bool:
    """Legacy wrapper — direct media sends are disabled for the bot."""
    logger.info(f"MEDIA_SEND_DISABLED | to={to} | type=audio | url={str(audio_url)[:120]}")
    return False


def send_document(to: str, doc_url: str, filename: str = None) -> bool:
    """Legacy wrapper — direct document sends are disabled for the bot."""
    logger.info(f"MEDIA_SEND_DISABLED | to={to} | type=document | url={str(doc_url)[:120]}")
    return False


def send_sticker(to: str, sticker_url: str) -> bool:
    """Legacy wrapper — direct media sends are disabled for the bot."""
    logger.info(f"MEDIA_SEND_DISABLED | to={to} | type=sticker | url={str(sticker_url)[:120]}")
    return False


def send_interactive_buttons(
    to: str,
    body_text: str,
    buttons: List[Dict],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
    header_media: Optional[Dict] = None,
) -> bool:
    """Legacy wrapper - maps to NEW API send_button_message."""
    import asyncio

    # Convert old button format to new format if needed
    normalized_buttons = []
    for btn in buttons[:3]:  # Max 3 buttons
        if isinstance(btn, dict):
            if btn.get("type") == "reply" and "reply" in btn:
                reply = btn["reply"]
                normalized_buttons.append(build_button(id=reply.get("id"), title=reply.get("title")))
            elif btn.get("id") and btn.get("title"):
                # Simple format
                normalized_buttons.append(build_button(id=btn["id"], title=btn["title"]))

    try:
        loop = asyncio.get_event_loop()
        # FIX: Check if loop is running correctly
        try:
            is_running = loop.is_running()
        except RuntimeError:
            is_running = False

        if is_running:
            asyncio.create_task(send_button_message(to, body_text, normalized_buttons, header_media, footer_text))
            return True
        else:
            return loop.run_until_complete(send_button_message(to, body_text, normalized_buttons, header_media, footer_text))
    except:
        # Fallback to numbered text
        logger.warning(f"BUTTON_MESSAGE_FALLBACK | to={to} | using text format")
        rows = []
        for btn in normalized_buttons[:10]:
            reply = btn.get("reply") or {}
            rows.append({"id": reply.get("id", ""), "title": reply.get("title", "")})
        sections = [{"title": header_text or "Options", "rows": rows}]
        return _send_list_as_text_fallback(to, body_text, sections, footer_text=footer_text or "Reply with a number", store_options=True)


def send_interactive_list(
    to: str,
    body_text: str,
    button_text: str,
    sections: List[Dict],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> bool:
    """Legacy wrapper - maps to OLD API send_list_menu."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        # FIX: Check if loop is running correctly
        try:
            is_running = loop.is_running()
        except RuntimeError:
            is_running = False

        if is_running:
            asyncio.create_task(send_list_menu(to, header_text or "", body_text, button_text, sections, footer_text))
            return True
        else:
            return loop.run_until_complete(send_list_menu(to, header_text or "", body_text, button_text, sections, footer_text))
    except:
        # Fallback to text format
        logger.warning(f"LIST_MENU_FALLBACK | to={to} | using text format")
        return _send_list_as_text_fallback(to, body_text, sections or [], footer_text=footer_text, store_options=True)


def _send_list_as_text_fallback(
    to: str,
    body_text: str,
    sections: List[Dict],
    footer_text: Optional[str] = None,
    store_options: bool = True,
) -> bool:
    """Numbered text menu + store option map so user can reply 1, 2, 3..."""
    text = (body_text or "").rstrip() + "\n\n"
    options = []
    count = 0
    for sec in sections[:8]:
        if sec.get("title"):
            text += f"*{sec['title']}*\n"
        for row in sec.get("rows", [])[:10]:
            count += 1
            row_id = row.get("id", "") or f"opt_{count}"
            title = (row.get("title") or "").strip() or f"Option {count}"
            desc = (row.get("description") or "").strip()
            text += f"{count}. {title}"
            if desc:
                text += f" - {desc[:60]}"
            text += "\n"
            options.append({"n": count, "id": row_id, "title": title})
            if count >= 20:
                break
        if count >= 20:
            break
    if count == 0:
        text += "_No options available._\n"
    else:
        text += f"\nReply with a number (*1*-*{count}*)"
    if footer_text:
        text += f"\n_{footer_text}_"

    if store_options and options:
        try:
            from ..database import update_user_context
            update_user_context(to, {"pending_options": options})
        except Exception as e:
            logger.warning(f"Failed to store pending menu options for {to}: {e}")

    return send_whatsapp_message(to, text)


# ============================================
# REMAINING LEGACY FUNCTIONS (Kept for compatibility)
# ============================================

# Functions below are kept from the original implementation for backward compatibility
# They handle menus, incoming messages, media operations, etc.

def _build_product_message(product: dict) -> str:
    """Build the text message for a product with emojis and bold formatting."""
    name = product.get("name", "")
    desc = product.get("short_description") or product.get("description", "")
    price = product.get("price", "")
    mrp = product.get("mrp", "")
    moq = product.get("moq", "")
    unit = product.get("unit", "")
    category = product.get("category", "")

    lines = [f"📦 *{name}*"]
    if category:
        lines.append(f"🏷️ Category: {category}")
    if desc:
        lines.append(f"\n📝 {desc}")
    if price:
        lines.append(f"\n💰 *Price: ₹{price}*" + (f" / {unit}" if unit else ""))
    if mrp and mrp != price:
        lines.append(f"~MRP: ₹{mrp}~")
    if moq:
        lines.append(f"🛍️ Min Order: {moq}")
    return "\n".join(lines)


def send_product_with_image(to: str, product: dict) -> bool:
    """Send product as a single interactive button message with image header.

    Payload shape matches the send2.digital session-msg-send interactive API:
    {
        "message_type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "image", "image": {"link": "..."}},
            "body":   {"text": "..."},
            "footer": {"text": "..."},
            "action": {"buttons": [...]}
        }
    }
    """
    media_url = product.get("media_url")
    product_id = product.get("id", "")
    name = product.get("name", "Product")

    body_text = _build_product_message(product)
    if not body_text:
        body_text = name

    buttons = []
    if product_id:
        buttons.append(build_button(id=f"b2c_add_cart_{product_id}", title="🛒 Add to Cart"))
    buttons.append(build_button(id="b2c_products", title="📦 View Products"))
    buttons.append(build_button(id="main_menu", title="🏠 Main Menu"))

    header_media = None
    if media_url:
        header_media = {"type": "image", "image": {"link": media_url}}

    return send_interactive_buttons(
        to=to,
        body_text=body_text,
        buttons=buttons[:3],
        header_media=header_media,
        footer_text="Reply with a number or tap a button",
    )


def send_with_main_menu_fallback(
    to: str,
    text: str,
    include_menu_button: bool = True,
) -> bool:
    """Send text; append menu hint (send2 has no native buttons)."""
    if not include_menu_button:
        return send_whatsapp_message(to, text)
    footer = "\n\n_Reply *menu* for Main Menu_"
    return send_whatsapp_message(to, (text or "").rstrip() + footer)


def send_main_menu(to: str) -> bool:
    """Send main menu as numbered text (send2 has no interactive lists)."""
    from .menu_router import build_main_menu_list, set_state, UserState

    menu_config = build_main_menu_list(to)
    set_state(to, UserState.MAIN_MENU)

    return send_interactive_list(
        to=to,
        body_text=menu_config.get("body", f"Welcome to {BUSINESS_NAME}!"),
        button_text=menu_config.get("button", "Main Menu"),
        sections=menu_config.get("sections", []),
        header_text=menu_config.get("header", BUSINESS_NAME),
        footer_text=menu_config.get("footer", "Type menu anytime to return here"),
    )


def fetch_incoming_messages(from_date, to_date):
    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "from_date": from_date,
        "to_date": to_date,
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = httpx.post(SEND2_INCOMING_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else []
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as e:
        logger.error(f"fetch_incoming_messages failed: {e}")
        return []


def store_incoming_messages(messages):
    stored = 0
    with get_db_context() as conn:
        for msg in messages:
            msg_id = msg.get("messageid") or msg.get("message_id") or msg.get("id")
            number = msg.get("Number") or msg.get("number") or ""
            message = msg.get("Message") or msg.get("message") or ""
            status = msg.get("status") or "received"
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO incoming_messages (message_id, number, message, status, raw_payload) VALUES (?, ?, ?, ?, ?)",
                    (msg_id, number, message, status, json.dumps(msg)),
                )
                stored += 1
            except Exception as e:
                logger.error(f"store_incoming_messages insert error: {e}")
    return stored


def download_media(media_id: str, mime_type: str = None) -> str:
    """Download media from send2.digital and extract text via OCR if image."""
    try:
        resp = httpx.get(
            f"{SEND2_MEDIA_URL}/{media_id}",
            auth=(SEND2_USERNAME, SEND2_PASSWORD),
            timeout=30,
            stream=True,
        )
        if resp.status_code != 200:
            logger.error(f"Media download failed: {resp.status_code} {resp.text[:200]}")
            return ""

        content_type = resp.headers.get("content-type", mime_type or "")

        if "image" in content_type:
            # Save to temp file for OCR
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                for chunk in resp.iter_content(chunk_size=8192):
                    tmp.write(chunk)
                tmp_path = tmp.name
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(tmp_path)
                text = pytesseract.image_to_string(img)
                return text.strip() if text else "[OCR: No text found]"
            except Exception as e:
                logger.error(f"OCR failed: {e}")
                return "[Image received - OCR unavailable]"
            finally:
                try:
                    os.unlink(tmp_path)
                except:
                    pass

        elif "pdf" in content_type:
            # Save to temp and extract text
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                for chunk in resp.iter_content(chunk_size=8192):
                    tmp.write(chunk)
                tmp_path = tmp.name
            try:
                from pypdf import PdfReader
                reader = PdfReader(tmp_path)
                texts = []
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        texts.append(t)
                return "\n".join(texts)[:5000]
            except Exception as e:
                logger.error(f"PDF extract failed: {e}")
                return "[PDF received - text extraction unavailable]"
            finally:
                try:
                    os.unlink(tmp_path)
                except:
                    pass

        return f"[Media received: {content_type}]"

    except Exception as e:
        logger.error(f"download_media failed: {e}")
        return ""


def _fetch_all_categories() -> list:
    """Get all unique categories from products and faq_dataset."""
    from ..database import get_db_context
    categories = set()
    with get_db_context() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM products WHERE is_active = 1").fetchall()
        categories.update(r[0] for r in rows)
        rows = conn.execute("SELECT DISTINCT category FROM faq_dataset").fetchall()
        categories.update(r[0] for r in rows)
    return sorted(categories)


def _fetch_items_from_category(category: str, limit: int = 10) -> list:
    """Fetch items from any category across products and faq."""
    from ..database import get_db_context
    items = []
    with get_db_context() as conn:
        # Check products
        rows = conn.execute(
            "SELECT id, name, short_description, price, mrp, moq, media_url "
            "FROM products WHERE category = ? AND is_active = 1 ORDER BY sort_order ASC LIMIT ?",
            (category, limit),
        ).fetchall()
        for r in rows:
            items.append({
                "id": f"prod_{r[0]}",
                "title": r[1],
                "description": (r[2] or "")[:50],
                "media_url": r[6],
                "type": "product",
                "price": r[3],
            })

        # Check FAQ
        rows = conn.execute(
            "SELECT id, content, source_file FROM faq_dataset WHERE source_file = ? ORDER BY id LIMIT ?",
            (category, limit),
        ).fetchall()
        for r in rows:
            items.append({
                "id": f"faq_{r[0]}",
                "title": r[2] or "FAQ",
                "description": (r[1] or "")[:80],
                "answer": r[1],
                "type": "faq",
            })
    return items


def _fetch_faq_by_keyword(keyword: str, limit: int = 5) -> list:
    """Search FAQ dataset for keyword matches."""
    from ..database import get_db_context
    results = []
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT id, content, source_file FROM faq_dataset "
            "WHERE content LIKE ? LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        for r in rows:
            results.append({
                "id": f"faq_{r[0]}",
                "title": r[2] or "FAQ",
                "description": r[1][:80] if r[1] else "",
                "answer": r[1],
                "type": "faq",
            })
    return results


def _fetch_banner_images() -> list:
    """Get banner images from products with category='banner'."""
    from ..database import get_db_context
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT id, name, media_url, media_type FROM products "
            "WHERE category = 'banner' AND is_active = 1 AND media_url IS NOT NULL "
            "ORDER BY sort_order ASC LIMIT 3"
        ).fetchall()
    return [{"id": r[0], "name": r[1], "url": r[2], "media_type": r[3]} for r in rows]


def _handle_menu_selection(wa_id: str, selected_id: str, selected_title: str) -> bool:
    """Handle any menu selection universally — product, FAQ, KB article."""
    from ..database import get_product, list_products as _list_products
    import re

    # New button-based menu IDs
    if selected_id in ("menu_catalogue", "menu_catalog", "menu_brochure"):
        return send_catalogue_pdf(wa_id)
    if selected_id == "menu_browse":
        return send_products_by_category(wa_id)
    if selected_id == "menu_products":
        return send_products_by_category(wa_id)
    if selected_id.startswith("menu_cat_"):
        cat = selected_id.replace("menu_cat_", "")
        return send_category_menu(wa_id, cat)
    if selected_id == "menu_faq":
        faq_items = _fetch_items_from_category("faq", limit=8)
        if not faq_items:
            all_cats = _fetch_all_categories()
            faq_items = []
            for cat in all_cats[:3]:
                faq_items.extend(_fetch_items_from_category(cat, limit=3))
        if faq_items:
            rows = [{"id": f["id"], "title": f["title"], "description": f["description"]} for f in faq_items[:10]]
            return send_interactive_list(
                to=wa_id,
                header_text="FAQ / Help",
                body_text="Choose a topic:",
                button_text="Topics",
                sections=[{"title": "Frequently Asked", "rows": rows}],
            )
        return send_whatsapp_message(wa_id, "Ask me anything and I'll help!")

    # Extract ID from "[ID:xxx]" pattern in text (from interactive replies)
    if not selected_id or not selected_id.startswith(("product_", "cat_prod_", "prod_", "faq_", "kb_")):
        match = re.search(r"\[ID:([^\]]+)\]", selected_title)
        if match:
            selected_id = match.group(1)

    # Plain text menu commands (user typed "products", "faq", etc.)
    text_lower = selected_title.lower().strip()
    if text_lower in ("catalogue", "catalog", "product catalogue", "product catalog", "pdf", "catalogue pdf", "catalog pdf", "brochure", "brochure pdf"):
        return send_catalogue_pdf(wa_id)
    if text_lower in ("products", "product", "browse products", "browse"):
        return send_products_by_category(wa_id)
    if text_lower in ("faq", "help", "faqs"):
        return _handle_menu_selection(wa_id, "menu_faq", "")
    if text_lower in ("menu", "start", "hi", "hello", "hey"):
        return send_menu(wa_id)

    if selected_id.startswith("product_") or selected_id.startswith("cat_prod_") or selected_id.startswith("prod_"):
        try:
            product_id = int(
                selected_id.replace("product_", "").replace("cat_prod_", "").replace("prod_", "")
            )
            product = get_product(product_id)
            if product:
                send_product_with_image(wa_id, product)
                return True
        except ValueError:
            pass

    elif selected_id.startswith("faq_"):
        try:
            faq_id = int(selected_id.replace("faq_", ""))
            from ..database import get_db_context
            with get_db_context() as conn:
                row = conn.execute(
                    "SELECT content, source_file FROM faq_dataset WHERE id = ?",
                    (faq_id,),
                ).fetchone()
                if row:
                    send_whatsapp_message(wa_id, f"*{row['source_file'] or 'FAQ'}*\n\n{row['content'][:500]}")
                    return True
        except ValueError:
            pass

    elif selected_id.startswith("kb_"):
        try:
            kb_id = int(selected_id.replace("kb_", ""))
            from ..database import get_db_context
            with get_db_context() as conn:
                row = conn.execute(
                    "SELECT title, content FROM knowledge_base WHERE id = ?",
                    (kb_id,),
                ).fetchone()
                if row:
                    send_whatsapp_message(wa_id, f"*{row['title']}*\n\n{row['content'][:500]}")
                    return True
        except ValueError:
            pass

    # Keyword search fallback
    keyword = selected_title.lower().strip()
    faq_results = _fetch_faq_by_keyword(keyword, limit=1)
    if faq_results:
        faq = faq_results[0]
        send_whatsapp_message(wa_id, f"*{faq['title']}*\n\n{faq['answer']}")
        return True

    return False


def send_menu(to: str) -> bool:
    from ..database import list_products as _list_products, get_db_context

    banner_imgs = _fetch_banner_images()
    if banner_imgs and banner_imgs[0].get("url"):
        send_image(to, banner_imgs[0]["url"])

    buttons = []
    categories = _fetch_all_categories()

    with get_db_context() as conn:
        has_catalogue = conn.execute(
            "SELECT id FROM products WHERE category = 'catalogue' AND media_url IS NOT NULL AND is_active = 1 LIMIT 1"
        ).fetchone()

    has_products = bool(_list_products(limit=1))

    if has_catalogue:
        buttons.append({"type": "reply", "reply": {"id": "menu_catalogue", "title": "Brochure"}})
    elif has_products:
        buttons.append({"type": "reply", "reply": {"id": "menu_browse", "title": "Browse Products"}})

    other_cats = [c for c in categories if c not in ("products", "catalogue", "general")]
    for cat in other_cats[:1]:
        buttons.append({"type": "reply", "reply": {"id": f"menu_cat_{cat}", "title": cat.title()}})

    buttons.append({"type": "reply", "reply": {"id": "menu_faq", "title": "FAQ / Help"}})

    if not buttons:
        return send_whatsapp_message(to, WELCOME_MESSAGE)

    return send_interactive_buttons(
        to=to,
        header_text=MENU_HEADER,
        body_text=MENU_BODY,
        buttons=buttons[:3],
        footer_text=MENU_FOOTER,
    )


def send_category_menu(to: str, category: str) -> bool:
    """Send items from a specific category using native WhatsApp interactive list."""
    items = _fetch_items_from_category(category, limit=8)
    if not items:
        return send_whatsapp_message(to, f"No items in '{category}' yet.")

    # Send first image as header visual
    for item in items:
        if item.get("media_url"):
            send_image(to, item["media_url"])
            break

    # Build list sections
    rows = []
    for item in items:
        rows.append({
            "id": item["id"],
            "title": item["title"][:24],
            "description": (item.get("description", "") or "")[:72],
        })

    return send_interactive_list(
        to=to,
        header_text=f"{category.title()}",
        body_text=f"Choose an item from {category}:",
        button_text="View Items",
        sections=[{"title": category.title(), "rows": rows[:10]}],
        footer_text=f"{len(rows)} items available",
    )


def send_products_by_category(to: str) -> bool:
    from ..database import get_db_context

    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category"
        ).fetchall()
        categories = [r[0] for r in rows if r[0]]

    if not categories:
        return send_whatsapp_message(to, "No products available yet. Check back soon!")

    banner_imgs = _fetch_banner_images()
    if banner_imgs and banner_imgs[0].get("url"):
        send_image(to, banner_imgs[0]["url"])

    sections = []
    for cat in categories[:5]:
        items = _fetch_items_from_category(cat, limit=10)
        product_items = [i for i in items if i.get("type") == "product"]
        if product_items:
            cat_rows = []
            for item in product_items:
                cat_rows.append({
                    "id": item["id"],
                    "title": item["title"][:24],
                    "description": (item.get("description", "") or "")[:72],
                })
            sections.append({"title": cat.title(), "rows": cat_rows})

    if not sections:
        return send_whatsapp_message(to, "No products available yet. Check back soon!")

    return send_interactive_list(
        to=to,
        header_text="Our Products",
        body_text="Browse our product range by category:",
        button_text="View Products",
        sections=sections,
        footer_text=f"{len(categories)} categories available",
    )


def _get_admin_document(module: str, default_filename: str, tenant_id: str = None) -> dict | None:
    try:
        from ..database import get_db_context
        with get_db_context() as conn:
            if tenant_id:
                row = conn.execute(
                    "SELECT name, url, file_path FROM admin_files "
                    "WHERE module = ? AND tenant_id = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    (module, tenant_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT name, url, file_path FROM admin_files "
                    "WHERE module = ? AND tenant_id IS NULL "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    (module,),
                ).fetchone()
        if row:
            name = row["name"] or default_filename
            url = row["url"] or ""
            file_path = row["file_path"] or ""
            if url.startswith(("http://", "https://")):
                return {"url": url, "filename": name}
            if file_path and os.path.isfile(file_path):
                resolved = resolve_public_media_url(file_path)
                if resolved:
                    return {"url": resolved, "filename": name}
    except Exception as e:
        logger.warning(f"admin document lookup failed for {module}: {e}")
    return None


def get_catalogue_doc(tenant_id: str = None) -> dict | None:
    """Resolve the tenant-owned catalogue document without crossing tenants."""
    if tenant_id:
        try:
            from shared.tenancy.loader import get_tenant_profile
            from shared.tenancy.resolver import resolve_tenant_for_user
            tid = resolve_tenant_for_user(tenant_id)
            profile = get_tenant_profile(tid)
            url = (profile.notifications.brochure_url or "").strip()
            if url:
                return {
                    "url": url,
                    "filename": profile.notifications.brochure_label or "Service Brochure.pdf",
                }
        except Exception as exc:
            logger.warning(f"tenant brochure profile lookup failed for {tenant_id}: {exc}")

    doc = _get_admin_document("catalogue", "Product Brochure.pdf", tenant_id=tenant_id)
    if doc:
        return doc

    # Only the legacy, non-tenant deployment may use the process-global URL.
    if tenant_id:
        return None
    from routing.config import CATALOGUE_PDF_URL, CATALOGUE_PDF_FILENAME
    return {"url": CATALOGUE_PDF_URL, "filename": CATALOGUE_PDF_FILENAME}


def get_new_arrivals_doc() -> dict | None:
    return _get_admin_document("new_arrival", "New Releases.pdf")


def send_catalogue_pdf(to: str, tenant_id: str = None) -> bool:
    """Send the product catalogue PDF as an interactive document + button."""
    doc = get_catalogue_doc(tenant_id=tenant_id)
    if not doc or not doc.get("url"):
        return False
    from routing.config import (
        CATALOGUE_BUTTON_ID,
        CATALOGUE_BUTTON_TITLE,
        CATALOGUE_BODY_TEXT,
    )
    header_media = {
        "type": "document",
        "document": {"link": doc["url"], "filename": doc["filename"]},
    }
    button = build_button(id=CATALOGUE_BUTTON_ID, title=CATALOGUE_BUTTON_TITLE)
    return send_interactive_buttons(
        to=to,
        body_text=CATALOGUE_BODY_TEXT,
        buttons=[button],
        header_media=header_media,
        footer_text=" ",
    )


def send_new_arrivals_pdf(to: str) -> bool:
    doc = get_new_arrivals_doc()
    if not doc:
        return False
    header_media = {
        "type": "document",
        "document": {"link": doc["url"], "filename": doc["filename"]},
    }
    button = build_button(id="main_menu", title="Main Menu")
    return send_interactive_buttons(
        to=to,
        body_text="Here are our latest new releases.",
        buttons=[button],
        header_media=header_media,
        footer_text=" ",
    )


def mark_as_read(to: str, message_id: str) -> bool:
    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": to,
        "message_type": "read",
        "message_id": message_id,
        "status": "read",
    }
    logger.info(f"MARK_READ | to={to} | msg_id={message_id}")
    try:
        resp = httpx.post(SEND2_SESSION_MSG_URL, json=payload, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"mark_as_read failed: {e}")
        return False


def send_typing_indicator(to: str) -> bool:
    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": to,
        "message_type": "typing",
    }
    try:
        resp = httpx.post(SEND2_SESSION_MSG_URL, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"send_typing_indicator failed (non-critical): {e}")
        return False


def transcribe_voice(media_id: str, mime_type: str = "audio/ogg") -> str:
    try:
        resp = httpx.get(
            f"{SEND2_MEDIA_URL}/{media_id}",
            auth=(SEND2_USERNAME, SEND2_PASSWORD),
            timeout=30,
            stream=True,
        )
        if resp.status_code != 200:
            logger.error(f"Voice download failed: {resp.status_code}")
            return "[Voice message - could not download]"

        import tempfile
        import os
        ext = ".ogg" if "ogg" in mime_type else ".mp3"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            grok_key = os.getenv("GROK_API_KEY")
            if not grok_key:
                return "[Voice message - transcription requires GROK_API_KEY]"

            with open(tmp_path, "rb") as f:
                whisper_resp = httpx.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {grok_key}"},
                    files={"file": (os.path.basename(tmp_path), f, mime_type)},
                    data={"model": "whisper-large-v3-turbo", "response_format": "text"},
                    timeout=60,
                )
            if whisper_resp.status_code == 200:
                text = whisper_resp.text.strip()
                logger.info(f"Voice transcribed: {text[:100]}")
                return text
            else:
                logger.error(f"Whisper failed: {whisper_resp.status_code} {whisper_resp.text[:200]}")
                return "[Voice message - transcription failed]"
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"transcribe_voice failed: {e}")
        return "[Voice message - error]"


def send_whatsapp_flow(
    to: str,
    flow_id: str,
    flow_token: str,
    header_text: str = "",
    body_text: str = "",
    footer_text: str = "",
    button_text: str = "Open",
) -> bool:
    interactive = {
        "type": "flow",
        "body": {"text": body_text or "Please fill out this form:"},
        "action": {
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_token": flow_token,
                "flow_id": flow_id,
                "flow_cta": button_text,
                "flow_action": "navigate",
                "flow_action_payload": {"screen": "INITIAL"},
            },
        },
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": to,
        "message_type": "interactive",
        "message": interactive,
    }

    logger.info(f"OUTGOING | to={to} | type=flow | flow_id={flow_id}")
    try:
        resp = httpx.post(SEND2_SESSION_MSG_URL, json=payload, timeout=30)
        logger.info(f"OUTGOING_RESULT | to={to} | status={resp.status_code} | resp={resp.text[:200]}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"send_whatsapp_flow failed: {e}")
        return False


# ── Standardised API response builder ──
# The router (port 9000) expects "media_url" and "media_type" keys.
# Use this to build your /kb-answer response instead of "media_url".
def make_kb_response(answer: str, media_url: str = None) -> dict:
    result = {"answer": answer}
    if media_url:
        result["media_url"] = media_url
        result["media_type"] = "image"
    return result