"""
Two-level webhook idempotency.

L1: in-process TTL cache (fast, best-effort, worker-local)
L2: webhook_dedup table, INSERT OR IGNORE (atomic, authoritative, cross-worker)
"""
import time
import logging
from database import get_db_context

logger = logging.getLogger("dedup")
_DEDUP_TTL = 300  # 5 minutes
_l1_cache: dict = {}


def _l1_check_and_set(message_id: str) -> bool:
    """True if already seen in THIS worker."""
    now = time.time()
    expired = [k for k, exp in _l1_cache.items() if exp < now]
    for k in expired:
        del _l1_cache[k]
    if message_id in _l1_cache:
        return True
    _l1_cache[message_id] = now + _DEDUP_TTL
    return False


def _l2_check_and_set(message_id: str, wa_id: str) -> bool:
    """True if ANY worker already claimed this message (authoritative)."""
    try:
        with get_db_context() as conn:
            # Check if send2 poller already claimed it
            row = conn.execute(
                "SELECT 1 FROM processed_inbound_messages WHERE message_id = ? LIMIT 1",
                (message_id,),
            ).fetchone()
            if row is not None:
                return True
            cur = conn.execute(
                "INSERT OR IGNORE INTO webhook_dedup (message_id, wa_id, processed_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (message_id, wa_id),
            )
            # Also keep processed_inbound_messages in sync so poller won't re-answer
            conn.execute(
                "INSERT OR IGNORE INTO processed_inbound_messages (message_id, wa_id, channel) "
                "VALUES (?, ?, 'webhook')",
                (message_id, wa_id),
            )
            return cur.rowcount == 0  # ignored insert = already existed
    except Exception as e:
        logger.error(f"Dedup L2 DB error for {message_id}: {e}")
        return False  # fail open — never lose a customer message


def is_duplicate(message_id: str, wa_id: str) -> bool:
    if not message_id:
        return False
    if _l1_check_and_set(message_id):
        return True
    if _l2_check_and_set(message_id, wa_id):
        logger.info(f"Dedup L2 hit (cross-worker): {message_id} from {wa_id}")
        return True
    return False
