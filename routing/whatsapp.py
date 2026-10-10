import logging
import requests
import httpx
from routing.config import (
    SEND2_USERNAME,
    SEND2_PASSWORD,
    SEND2_SESSION_SEND_URL,
    SEND2_LIST_MENU_URL,
    SEND2_QUICK_BUTTON_URL,
)

logger = logging.getLogger("chiki_webhook")

VALID_MSG_TYPES = ("text", "image", "video", "audio", "document")


def _resolve_media_url(media_url: str) -> str:
    """Make a media URL absolute. send2.digital needs a public http(s) URL.

    Relative server paths (e.g. ``/uploaded_files/x.pdf``) are prefixed with the
    configured public base URL; otherwise a broken ``https:///...`` URL results.
    """
    if not media_url:
        return media_url
    if media_url.startswith(("http://", "https://")):
        return media_url
    from routing.config import PUBLIC_BASE_URL
    base = (PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return base + "/" + media_url.lstrip("/")
    return "https://" + media_url


def _normalize_msg_type(msg_type: str) -> str:
    """Map FAQ/other media labels to the WhatsApp media types send2 accepts."""
    if not msg_type:
        return "text"
    mt = msg_type.lower()
    if mt in ("pdf", "doc", "docx", "xlsx", "csv"):
        return "document"
    if mt == "jpg":
        return "image"
    if mt == "png":
        return "image"
    if mt in VALID_MSG_TYPES:
        return mt
    return "text"


def normalize_whatsapp_formatting(text: str) -> str:
    """
    Normalize Markdown-ish emphasis so WhatsApp renders true bold/italic
    (*bold* / _italic_) instead of showing literal asterisks.
    """
    if not text:
        return text or ""
    import re
    # Markdown **bold** / __bold__ -> WhatsApp *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"*\1*", text)
    return text


def send_whatsapp_message(to, text, msg_type="text", timeout=15, retries=2):
    if msg_type != "text":
        # Media (image/video/audio/document) sends are disabled across the
        # project — only text messages are sent to customers anymore.
        logger.info(f"MEDIA_SEND_DISABLED | to={to} | type={msg_type} | url={str(text)[:120]}")
        return False

    text = normalize_whatsapp_formatting(text)

    payload = {
        "user_name": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "contact_no": to,
        "message_type": "text",
        "message": text,
        "messaging_product": "whatsapp",
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                SEND2_SESSION_SEND_URL,
                json=payload,
                timeout=timeout,
            )
            logger.info(f"Reply sent to {to} [{msg_type}], status={resp.status_code}, body={resp.text[:300]}")
            body = (resp.text or "").lower()
            # send2.digital replies 200 with "Your Message ID : ... , Message
            # Sent Successfully" for session-msg-send; other endpoints return
            # JSON {"success": true}. Anything else (INVALID PARAMETER, the
            # OPT OUT notice, ...) is a failure even with status 200.
            return resp.status_code == 200 and (
                '"success":true' in body
                or '"success":1' in body
                or "message sent successfully" in body
            )
        except Exception as e:
            last_err = e
            logger.warning(f"send2.digital send failed for {msg_type} (attempt {attempt}/{retries}): {e}")
    logger.error(f"send2.digital send failed for {msg_type} after {retries} attempts: {last_err}")
    return False


def send_whatsapp_list_menu(to, header_text, body_text, button_text, sections, footer_text=None):
    api_sections = []
    for section in sections:
        api_section = {
            "title": section.get("title", ""),
            "rows": []
        }
        for row in section.get("rows", []):
            api_row = {
                "id": row.get("id", ""),
                "title": row.get("title", ""),
                "description": row.get("description", ""),
            }
            api_section["rows"].append(api_row)
        api_sections.append(api_section)

    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": to,
        "headertext": header_text or " ",
        "bodytext": body_text or " ",
        "footertext": footer_text or " ",
        "buttontext": button_text or "Menu",
        "total_number_section": len(api_sections),
        "total_rows": sum(len(section.get("rows", [])) for section in api_sections),
        "sections": api_sections,
    }
    try:
        logger.info(f"LIST_MENU_REQUEST | to={to} | sections={len(api_sections)} | rows={sum(len(s.get('rows', [])) for s in api_sections)}")
        with httpx.Client(timeout=30) as client:
            resp = client.post(SEND2_LIST_MENU_URL, json=payload)
        logger.info(f"LIST_MENU_RESPONSE | to={to} | status={resp.status_code} | body={resp.text[:300]}")
        return resp.status_code == 200 and ("Message Sent Successfully" in resp.text or "success" in resp.text.lower())
    except Exception as e:
        logger.error(f"send2.digital list menu send failed: {e}")
        return False


def _truncate_body(text: str, limit: int = 1020) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit // 2:
        cut = cut[:last_space]
    return cut.rstrip() + "\n…"


def send_whatsapp_interactive(to, text, buttons, footer=None):
    """Send an interactive button message via send2.digital Quick Button API.

    `buttons` is a list of button objects in the send2.digital format, e.g.:
        [{"type": "reply", "reply": {"id": "check_moq", "title": "Check MOQ by product"}}]
    """
    if not buttons or len(buttons) == 0:
        logger.warning("No buttons provided for interactive message")
        return False

    if len(buttons) > 3:
        logger.warning(f"Too many buttons ({len(buttons)}), limiting to 3")
        buttons = buttons[:3]

    # NOTE: headertext and footertext must be NON-EMPTY strings, otherwise
    # send2.digital rejects the whole request with {"error":"INVALID PARAMETER"}.
    payload = {
        "username": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "number": to,
        "headertype": "text",
        "headertext": " ",
        "bodytext": _truncate_body(normalize_whatsapp_formatting(text)),
        "footertext": footer or " ",
        "total_buttons": len(buttons),
        "buttons": buttons,
    }
    try:
        resp = requests.post(
            SEND2_QUICK_BUTTON_URL,
            json=payload,
            timeout=30,
        )
        logger.info(f"Interactive reply sent to {to}, status={resp.status_code}, body={resp.text[:300]}")
        return resp.status_code == 200 and '"success":true' in resp.text
    except Exception as e:
        logger.error(f"send2.digital interactive send failed: {e}")
        return False
