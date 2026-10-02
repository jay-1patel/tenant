"""
Handoff timeout monitor.

Periodically checks for conversations stuck in human_handover mode
where no human agent has responded within the configured timeout.
When detected, automatically clears human_handover so the chatbot
resumes handling the conversation.
"""

import asyncio
import logging
import sqlite3

from routing.config import DB_PATH as ROUTING_DB_PATH

logger = logging.getLogger("handoff_timeout")

# How often to check (seconds)
CHECK_INTERVAL = 60

# Max time a handoff can stay active before auto-revert (seconds)
HANDOFF_TIMEOUT_SECONDS = 3600  # 1 hour

TIMEOUT_MESSAGE = (
    "It looks like our team hasn't responded yet. "
    "I'm back to help you! Feel free to ask your question again. 🤖"
)


def _get_stale_handoffs() -> list[str]:
    """Return wa_ids where human_handover=1 and no human reply has arrived
    within the timeout window.

    The cutoff is evaluated by SQLite itself (``datetime('now', ...)``) so it
    always uses the same clock that writes ``updated_at`` via CURRENT_TIMESTAMP.
    ``updated_at`` is bumped every time a human agent replies (see the
    agent-send route), so this fires only when the human agent has gone
    silent for the full timeout.
    """
    if not ROUTING_DB_PATH:
        return []
    try:
        conn = sqlite3.connect(ROUTING_DB_PATH)
        rows = conn.execute(
            "SELECT wa_id FROM user_states "
            "WHERE human_handover = 1 "
            "AND updated_at < datetime('now', ?)",
            (f"-{HANDOFF_TIMEOUT_SECONDS} seconds",),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"Failed to check stale handoffs: {e}")
        return []


def _clear_handover(wa_id: str) -> None:
    """Clear human_handover for a single user."""
    if not ROUTING_DB_PATH:
        return
    try:
        conn = sqlite3.connect(ROUTING_DB_PATH)
        row = conn.execute(
            "SELECT tenant_id FROM user_states WHERE wa_id = ?", (wa_id,)
        ).fetchone()
        tid = row["tenant_id"] if row and row["tenant_id"] else None
        conn.execute(
            "UPDATE user_states SET human_handover = 0, updated_at = CURRENT_TIMESTAMP, "
            "handover_resolved_at = CURRENT_TIMESTAMP WHERE wa_id = ?"
            + (" AND tenant_id = ?" if tid else ""),
            (wa_id, tid) if tid else (wa_id,),
        )
        conn.commit()
        conn.close()
        logger.info(f"HANDOFF_TIMEOUT | Cleared handover for {wa_id}")
    except Exception as e:
        logger.error(f"Failed to clear handover for {wa_id}: {e}")


def _send_timeout_message(wa_id: str) -> None:
    """Send the auto-revert notification to the user."""
    try:
        from routing.config import SEND2_USERNAME, SEND2_PASSWORD
        if SEND2_USERNAME and SEND2_PASSWORD:
            from routing.whatsapp import send_whatsapp_message
            send_whatsapp_message(wa_id, TIMEOUT_MESSAGE)
    except Exception as e:
        logger.error(f"Failed to send timeout message to {wa_id}: {e}")


async def handoff_timeout_monitor(stop_event: asyncio.Event = None) -> None:
    """Background loop that reverts stale handoffs."""
    logger.info(
        "Handoff timeout monitor started (interval=%ds, timeout=%ds)",
        CHECK_INTERVAL, HANDOFF_TIMEOUT_SECONDS,
    )

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Handoff timeout monitor stopping")
            break

        try:
            stale = _get_stale_handoffs()
            if stale:
                logger.info(f"HANDOFF_TIMEOUT | Found {len(stale)} stale handoff(s): {stale}")
                for wa_id in stale:
                    _clear_handover(wa_id)
                    _send_timeout_message(wa_id)
                    # Small delay between messages to avoid rate limits
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Handoff timeout check failed: {e}")

        await asyncio.sleep(CHECK_INTERVAL)
