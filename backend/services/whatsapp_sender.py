"""
Shared WhatsApp sender.

This is the single shared WhatsApp client used by the bot workflows
(``bots.distributor_b2b`` and ``bots.customer_b2c``) and the orchestrator.

It exposes exactly:

    send_text_message(wa_id, text)
    send_image_message(wa_id, media_url, caption)
    send_button_message(wa_id, body, buttons)
    send_list_menu(wa_id, header, body, button_text, sections)

Senders record outgoing messages during capture. By default they also deliver
messages live; callers can request capture-only mode and send the captured
messages themselves (``begin_capture(capture_only=True)`` / ``drain_captured()``).
"""

import logging
from contextvars import ContextVar

logger = logging.getLogger("whatsapp_sender")

# Outgoing-message capture buffer shared by all personas during a single
# orchestrator invocation.
_captured: ContextVar[list | None] = ContextVar("whatsapp_capture", default=None)
_capture_only: ContextVar[bool] = ContextVar("whatsapp_capture_only", default=False)


def begin_capture(capture_only: bool = False):
    """Start request-local capture; optionally suppress live delivery."""
    capture_token = _captured.set([])
    live_token = _capture_only.set(capture_only)
    return capture_token, live_token


def end_capture(tokens) -> None:
    """Restore the previous request-local capture state."""
    capture_token, live_token = tokens
    _captured.reset(capture_token)
    _capture_only.reset(live_token)


def drain_captured() -> list:
    """Return captured outgoing messages and clear the current buffer."""
    items = _captured.get()
    if items is None:
        return []
    result = list(items)
    items.clear()
    return result


def _record(payload: dict) -> None:
    items = _captured.get()
    if items is not None:
        items.append(payload)


def _live_sender(kind: str):
    """Lazily import the concrete send2.digital sender for a message kind.

    Returns a callable ``(wa_id, *args) -> bool`` that performs a real send, or
    ``None`` if delivery is suppressed or unavailable.
    """
    if _capture_only.get():
        return None
    try:
        if kind == "text":
            from kb.services.whatsapp import send_whatsapp_message
            return lambda wa_id, text: send_whatsapp_message(wa_id, text, "text")
        if kind == "image":
            from kb.services.whatsapp import send_whatsapp_message, resolve_public_media_url
            def _img(wa_id, media_url, caption=""):
                url = media_url
                try:
                    resolved = resolve_public_media_url(media_url)
                    if resolved:
                        url = resolved
                except Exception as e:
                    logger.warning(f"image url resolve failed: {e}")
                return send_whatsapp_message(wa_id, url, "image")
            return _img
        if kind == "document":
            from kb.services.whatsapp import send_document
            return lambda wa_id, doc_url, filename=None: send_document(wa_id, doc_url, filename)
        if kind == "buttons":
            from routing.whatsapp import send_whatsapp_list_menu, normalize_reply_buttons
            def _btns(wa_id, body, buttons, header_media=None):
                # When using Send2, quick-reply buttons return Message: null on click in incoming-report.
                # Sending options via list menu guarantees Send2 captures and returns the option title.
                api_buttons = normalize_reply_buttons(buttons)
                rows = []
                for b in api_buttons:
                    r = b.get("reply", {})
                    bid = r.get("id", "")
                    btitle = r.get("title", "")[:24]
                    if bid and btitle:
                        rows.append({"id": bid, "title": btitle, "description": ""})
                if rows:
                    header_title = "Options"
                    try:
                        from shared.tenancy.resolver import resolve_tenant_for_user
                        from shared.tenancy.loader import get_tenant_profile
                        p = get_tenant_profile(resolve_tenant_for_user(wa_id))
                        if p and p.brand and p.brand.name:
                            header_title = p.brand.name
                    except Exception:
                        pass
                    return send_whatsapp_list_menu(
                        to=wa_id,
                        header_text=header_title,
                        body_text=body,
                        button_text="Select Option",
                        sections=[{"title": "Options", "rows": rows}],
                    )
                from kb.services.whatsapp import send_interactive_buttons
                return send_interactive_buttons(
                    to=wa_id, body_text=body, buttons=buttons,
                    header_media=header_media, footer_text=None,
                )
            return _btns
        if kind == "list":
            from routing.whatsapp import send_whatsapp_list_menu
            return lambda wa_id, header, body, button_text, sections: send_whatsapp_list_menu(
                to=wa_id,
                header_text=header,
                body_text=body,
                button_text=button_text,
                sections=sections,
            )
    except Exception as e:  # pragma: no cover - depends on app runtime
        logger.warning(f"live sender import failed for {kind}: {e}")
    return None


async def send_text_message(wa_id: str, text: str) -> bool:
    """Send (or capture) a plain text message."""
    logger.info(f"SEND_TEXT | to={wa_id} | chars={len(text or '')}")
    sender = _live_sender("text")
    if sender is None:
        _record({"type": "text", "text": text or "", "sent_live": False})
        return True  # capture-only fallback (e.g. simulator)
    try:
        sent = bool(sender(wa_id, text or ""))
        _record({"type": "text", "text": text or "", "sent_live": sent})
        return sent
    except Exception as e:
        logger.error(f"SEND_TEXT_FAILED | to={wa_id} | error={e}")
        _record({"type": "text", "text": text or "", "sent_live": False})
        return False


async def send_image_message(wa_id: str, media_url: str, caption: str = "") -> bool:
    """Send (or capture) an image message with an optional caption."""
    _record({"type": "image", "media_url": media_url or "", "caption": caption or ""})
    logger.info(f"SEND_IMAGE | to={wa_id} | url_len={len(media_url or '')} | caption_len={len(caption or '')}")
    sender = _live_sender("image")
    if sender is None:
        return True
    try:
        return bool(sender(wa_id, media_url or "", caption or ""))
    except Exception as e:
        logger.error(f"SEND_IMAGE_FAILED | to={wa_id} | error={e}")
        return False


async def send_document_message(wa_id: str, doc_url: str, filename: str = None) -> bool:
    """Send (or capture) a document (e.g. PDF) message."""
    _record({"type": "document", "media_url": doc_url or "", "filename": filename or ""})
    logger.info(f"SEND_DOCUMENT | to={wa_id} | url_len={len(doc_url or '')} | name={filename}")
    sender = _live_sender("document")
    if sender is None:
        return True
    try:
        return bool(sender(wa_id, doc_url or "", filename))
    except Exception as e:
        logger.error(f"SEND_DOCUMENT_FAILED | to={wa_id} | error={e}")
        return False


async def send_catalogue_message(wa_id: str) -> bool:
    """Send (or capture) the product catalogue PDF as an interactive document
    with a single reply button (send2.digital "interactive" type=button body).

    This is the one and only way the catalogue is delivered: the PDF is sent
    directly from a permanent public URL (see routing/config.py) — catalogue
    PDFs are never imported into the products table. The PDF is resolved
    dynamically (get_catalogue_doc) so a newly uploaded catalogue replaces
    the old one without code/env changes.
    """
    from kb.services.whatsapp import get_catalogue_doc
    from routing.config import (
        CATALOGUE_BUTTON_ID,
        CATALOGUE_BUTTON_TITLE,
        CATALOGUE_BODY_TEXT,
    )
    doc = get_catalogue_doc()
    header_media = {
        "type": "document",
        "document": {"link": doc["url"], "filename": doc["filename"]},
    }
    buttons = [
        {"type": "reply", "reply": {"id": CATALOGUE_BUTTON_ID, "title": CATALOGUE_BUTTON_TITLE}}
    ]
    _record({
        "type": "buttons",
        "text": CATALOGUE_BODY_TEXT or "",
        "buttons": buttons,
        "header_media": header_media,
    })
    logger.info(f"SEND_CATALOGUE | to={wa_id} | pdf={doc['url']}")
    sender = _live_sender("buttons")
    if sender is None:
        return True
    try:
        return bool(sender(wa_id, CATALOGUE_BODY_TEXT or "Choose an option:", buttons, header_media))
    except Exception as e:
        logger.error(f"SEND_CATALOGUE_FAILED | to={wa_id} | error={e}")
        return False


async def send_new_arrivals_message(wa_id: str) -> bool:
    """Send or capture the new releases PDF as an interactive document."""
    from kb.services.whatsapp import get_new_arrivals_doc

    doc = get_new_arrivals_doc()
    if not doc:
        return False
    buttons = [
        {"type": "reply", "reply": {"id": "main_menu", "title": "Main Menu"}}
    ]
    header_media = {
        "type": "document",
        "document": {"link": doc["url"], "filename": doc["filename"]},
    }
    body = "Here are our latest new releases."
    _record({
        "type": "buttons",
        "text": body,
        "buttons": buttons,
        "header_media": header_media,
    })
    logger.info(f"SEND_NEW_ARRIVALS | to={wa_id}")
    sender = _live_sender("buttons")
    if sender is None:
        return True
    try:
        return bool(sender(wa_id, body, buttons, header_media))
    except Exception as e:
        logger.error(f"SEND_NEW_ARRIVALS_FAILED | to={wa_id} | error={e}")
        return False


async def send_button_message(wa_id: str, body: str, buttons: list, header_media: dict = None) -> bool:
    """Send (or capture) an interactive button message.

    header_media: optional dict like {"type": "image", "image": {"link": "https://..."}}
    to attach media as the message header in the SAME API call (no separate
    media message needed).
    """
    logger.info(f"SEND_BUTTONS | to={wa_id} | buttons={len(buttons or [])} | header={'yes' if header_media else 'no'}")
    sender = _live_sender("buttons")
    if sender is None:
        _record({
            "type": "buttons", "text": body or "", "buttons": buttons or [],
            "header_media": header_media or None, "sent_live": False,
        })
        return True
    try:
        sent = bool(sender(wa_id, body or "", buttons or [], header_media))
        _record({
            "type": "buttons", "text": body or "", "buttons": buttons or [],
            "header_media": header_media or None, "sent_live": sent,
        })
        return sent
    except Exception as e:
        logger.error(f"SEND_BUTTONS_FAILED | to={wa_id} | error={e}")
        _record({
            "type": "buttons", "text": body or "", "buttons": buttons or [],
            "header_media": header_media or None, "sent_live": False,
        })
        return False


async def send_list_menu(
    wa_id: str,
    header: str,
    body: str,
    button_text: str,
    sections: list,
) -> bool:
    """Send (or capture) a list menu message."""
    logger.info(f"SEND_LIST | to={wa_id} | sections={len(sections or [])}")
    sender = _live_sender("list")
    if sender is None:
        _record(
            {
                "type": "list",
                "header": header or "",
                "body": body or "",
                "button_text": button_text or "",
                "sections": sections or [],
                "sent_live": False,
            }
        )
        return True
    try:
        sent = bool(sender(wa_id, header or "", body or "", button_text or "", sections or []))
        _record(
            {
                "type": "list",
                "header": header or "",
                "body": body or "",
                "button_text": button_text or "",
                "sections": sections or [],
                "sent_live": sent,
            }
        )
        return sent
    except Exception as e:
        logger.error(f"SEND_LIST_FAILED | to={wa_id} | error={e}")
        _record(
            {
                "type": "list",
                "header": header or "",
                "body": body or "",
                "button_text": button_text or "",
                "sections": sections or [],
                "sent_live": False,
            }
        )
        return False
