"""Fire-and-forget mirror of outbound send2.digital traffic to Hookdeck.

Every request the bot makes to send2.digital (and send2's response) is
POSTed to ``HKDEK_WEBHOOK_URL`` as a ``send2_outbound`` event, so the
Hookdeck dashboard shows exactly what left this server and what send2
replied — without sitting in the send path. Sends never block or fail
because of the tee: the POST runs in a daemon thread with a short
timeout and all errors are swallowed.
"""

import logging
import threading

import httpx

from routing.config import HKDEK_WEBHOOK_URL

logger = logging.getLogger("hookdeck")

_REDACT_KEYS = ("password", "api_key", "apikey", "token", "secret")


def _redact(obj):
    if isinstance(obj, dict):
        return {
            k: ("***" if any(r in str(k).lower() for r in _REDACT_KEYS) else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(i) for i in obj]
    return obj


def tee_outbound(endpoint: str, payload: dict, response_status=None, response_body: str = "", to: str = "") -> None:
    """Mirror one outbound send2.digital request + its response to Hookdeck."""
    if not HKDEK_WEBHOOK_URL:
        return

    event = {
        "type": "send2_outbound",
        "endpoint": endpoint,
        "to": str(to or ""),
        "request": _redact(payload or {}),
        "response": {
            "status": response_status,
            "body": (response_body or "")[:1000],
        },
    }

    def _post():
        try:
            httpx.post(HKDEK_WEBHOOK_URL, json=event, timeout=10)
        except Exception as e:
            logger.debug("hookdeck tee failed: %s", e)

    threading.Thread(target=_post, daemon=True).start()
