"""SQLite access for tenants + tenant_profile_versions.

All JSON lives in TEXT columns (decision D2) — no jsonb. Postgres is a future
migration, not now.

Publish model:
  * the *working copy* an admin edits lives in the existing ``draft_config``
    table under scope ``tenant_profile:<tenant_id>`` — same draft/publish
    machinery every other dynamic-config scope already uses.
  * publishing validates the fully-merged profile, appends a numbered row to
    ``tenant_profile_versions``, and flips ``is_current``. Old versions are kept.
  * rollback re-points ``is_current`` at an earlier version. Nothing is deleted.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .paths import BACKEND_DIR
import sys as _sys

logger = logging.getLogger("tenancy.store")

if str(BACKEND_DIR) not in _sys.path:
    _sys.path.insert(0, str(BACKEND_DIR))

PROFILE_SCOPE_PREFIX = "tenant_profile:"
VERSION_TTL_SECONDS = 60.0

_version_lock = threading.RLock()
_version_cache: Dict[str, Tuple[float, int]] = {}


def _db():
    import database  # backend/database.py — the sole schema owner
    return database


def profile_scope(tenant_id: str) -> str:
    return f"{PROFILE_SCOPE_PREFIX}{tenant_id}"


def tenant_id_from_scope(scope: str) -> Optional[str]:
    if scope and scope.startswith(PROFILE_SCOPE_PREFIX):
        return scope[len(PROFILE_SCOPE_PREFIX):]
    return None


# ── tenants ───────────────────────────────────────────────────────────────

def ensure_tenant(tenant_id: str, *, slug: str = "", vertical: str = "generic",
                  waba_phone_id: str = "", display_name: str = "",
                  status: str = "active", conn=None) -> bool:
    """Idempotent upsert. Never clobbers an existing waba_phone_id with blank.

    An unbound tenant stores NULL rather than '' so the partial unique index on
    waba_phone_id excludes it and any number of clients can be registered before
    their numbers are bound.
    """
    def _write(connection):
        connection.execute(
            """INSERT INTO tenants (id, slug, waba_phone_id, vertical, status, display_name)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   slug = CASE WHEN excluded.slug != '' THEN excluded.slug ELSE tenants.slug END,
                   waba_phone_id = CASE WHEN excluded.waba_phone_id != ''
                                        THEN excluded.waba_phone_id ELSE tenants.waba_phone_id END,
                   vertical = excluded.vertical,
                   status = excluded.status,
                   display_name = CASE WHEN excluded.display_name != ''
                                       THEN excluded.display_name ELSE tenants.display_name END,
                   updated_at = CURRENT_TIMESTAMP""",
            (tenant_id, slug or tenant_id, waba_phone_id or None, vertical, status, display_name),
        )

    if conn is None:
        with _db().get_db_context() as own_conn:
            _write(own_conn)
    else:
        _write(conn)
    invalidate(tenant_id)
    return True


def get_tenant(tenant_id: str) -> Optional[dict]:
    with _db().get_db_context() as conn:
        try:
            row = conn.execute("SELECT * FROM tenants WHERE id = ?", (str(tenant_id),)).fetchone()
        except Exception as exc:
            # Tolerate a database that has not been migrated yet — the loader
            # falls back to file + vertical defaults rather than hard-failing.
            logger.warning("Could not read tenant %s (schema not migrated?): %s", tenant_id, exc)
            return None
    return dict(row) if row else None


def list_tenants(status: Optional[str] = None) -> List[dict]:
    with _db().get_db_context() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tenants WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tenants ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def normalize_waba_phone_id(value: str) -> str:
    """Normalize a WhatsApp phone binding to digits only.

    Accepts either the Meta phone-number id (all digits) or the WhatsApp
    number itself in ``+91 8000305305`` form. Inbound webhook payloads
    carry the number without the plus sign (``metadata.display_phone_number``),
    so digits-only is the form the resolver matches against.
    """
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not 10 <= len(digits) <= 16:
        raise ValueError(
            "waba_phone_id must be the WhatsApp phone number id or the "
            "number itself in international format (10-16 digits)"
        )
    return digits


def set_waba_phone_id(tenant_id: str, phone_id: str, conn=None) -> bool:
    """Bind a WABA phone-id to a tenant. Refuses to steal an existing binding."""
    phone_id = str(phone_id or "").strip()
    if not phone_id:
        return False
    def _bind(connection):
        clash = connection.execute(
            "SELECT id FROM tenants WHERE waba_phone_id = ? AND id != ?", (phone_id, tenant_id)
        ).fetchone()
        if clash:
            logger.warning(
                "waba_phone_id %s already bound to tenant %s; refusing to rebind to %s",
                phone_id, clash["id"], tenant_id,
            )
            return False
        connection.execute(
            "UPDATE tenants SET waba_phone_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (phone_id, str(tenant_id)),
        )
        return True

    if conn is None:
        with _db().get_db_context() as own_conn:
            ok = _bind(own_conn)
    else:
        ok = _bind(conn)
    if ok:
        invalidate(tenant_id)
    return ok


def find_tenant_by_phone_id(phone_id: str) -> Optional[str]:
    phone_id = str(phone_id or "").strip()
    if not phone_id:
        return None
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT id FROM tenants WHERE waba_phone_id = ?", (phone_id,)
        ).fetchone()
    return row["id"] if row else None


def tenant_id_for_user(wa_id: str) -> Optional[str]:
    """Which tenant a WhatsApp user belongs to, from their conversation state.

    user_states is keyed by wa_id and already carries tenant_id, so this is one
    indexed read. Returns None for a user with no state row.
    """
    wa_id = str(wa_id or "").strip()
    if not wa_id:
        return None
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT tenant_id FROM user_states WHERE wa_id = ?", (wa_id,)
        ).fetchone()
    if not row:
        return None
    tid = (row["tenant_id"] or "").strip()
    return tid or None


def delete_tenant(tenant_id: str, conn=None) -> bool:
    def _delete(connection):
        connection.execute("DELETE FROM tenant_profile_versions WHERE tenant_id = ?", (str(tenant_id),))
        connection.execute("DELETE FROM draft_config WHERE scope = ?", (profile_scope(tenant_id),))
        connection.execute("DELETE FROM published_config WHERE scope = ?", (profile_scope(tenant_id),))
        connection.execute("DELETE FROM tenants WHERE id = ?", (str(tenant_id),))

    if conn is None:
        with _db().get_db_context() as own_conn:
            _delete(own_conn)
    else:
        _delete(conn)
    invalidate(tenant_id)
    return True


# ── version bookkeeping ───────────────────────────────────────────────────

def current_version(tenant_id: str) -> int:
    """Current published version for a tenant. 0 means 'no DB version'."""
    tid = str(tenant_id)
    now = time.monotonic()
    with _version_lock:
        hit = _version_cache.get(tid)
        if hit and hit[0] >= now:
            return hit[1]
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT version FROM tenant_profile_versions "
            "WHERE tenant_id = ? AND is_current = 1 ORDER BY version DESC LIMIT 1",
            (tid,),
        ).fetchone()
    version = int(row["version"]) if row else 0
    with _version_lock:
        _version_cache[tid] = (now + VERSION_TTL_SECONDS, version)
    return version


def invalidate(tenant_id: str) -> None:
    with _version_lock:
        _version_cache.pop(str(tenant_id), None)


def invalidate_all() -> None:
    with _version_lock:
        _version_cache.clear()


def get_current_payload(tenant_id: str) -> Optional[dict]:
    """The DB override layer: the current published version's payload."""
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT payload FROM tenant_profile_versions "
            "WHERE tenant_id = ? AND is_current = 1 ORDER BY version DESC LIMIT 1",
            (str(tenant_id),),
        ).fetchone()
    if not row or not row["payload"]:
        return None
    try:
        return json.loads(row["payload"])
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("tenant %s has unparseable current payload: %s", tenant_id, exc)
        return None


def get_version(tenant_id: str, version: int) -> Optional[dict]:
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM tenant_profile_versions WHERE tenant_id = ? AND version = ?",
            (str(tenant_id), int(version)),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    try:
        out["payload"] = json.loads(out["payload"]) if out["payload"] else {}
    except (json.JSONDecodeError, TypeError):
        out["payload"] = {}
    out["is_current"] = bool(out.get("is_current"))
    return out


def list_versions(tenant_id: str, limit: int = 50) -> List[dict]:
    with _db().get_db_context() as conn:
        rows = conn.execute(
            """SELECT id, tenant_id, version, published_by, created_at, is_current
                 FROM tenant_profile_versions
                WHERE tenant_id = ?
                ORDER BY version DESC LIMIT ?""",
            (str(tenant_id), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def _set_current(conn, tenant_id: str, version: int) -> None:
    conn.execute(
        "UPDATE tenant_profile_versions SET is_current = 0 WHERE tenant_id = ? AND is_current = 1",
        (str(tenant_id),),
    )
    conn.execute(
        "UPDATE tenant_profile_versions SET is_current = 1 WHERE tenant_id = ? AND version = ?",
        (str(tenant_id), int(version)),
    )


def publish_version(tenant_id: str, payload: dict, published_by: str = "", conn=None) -> int:
    """Append a new version and make it current. Returns the new version number.

    The caller is responsible for validating the merged profile *before* this —
    this function only persists an already-validated payload.
    """
    tid = str(tenant_id)
    body = json.dumps(payload, ensure_ascii=False)
    def _publish(connection):
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM tenant_profile_versions WHERE tenant_id = ?",
            (tid,),
        ).fetchone()
        next_version = int(row["v"]) + 1
        # Insert with is_current = 0: the partial unique index
        # ux_tenant_profile_current only allows ONE current row per tenant, so
        # _set_current must clear the previous one first. Inserting as current
        # straight away violates the index on every publish after the first.
        connection.execute(
            """INSERT INTO tenant_profile_versions
                   (tenant_id, version, payload, published_by, created_at, is_current)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 0)""",
            (tid, next_version, body, published_by or ""),
        )
        _set_current(connection, tid, next_version)
        # Mirror into published_config so the generic config surfaces stay consistent.
        connection.execute(
            """INSERT INTO published_config (scope, snapshot_json, published_by, published_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(scope) DO UPDATE SET
                   snapshot_json = excluded.snapshot_json,
                   published_by = excluded.published_by,
                   published_at = CURRENT_TIMESTAMP""",
            (profile_scope(tid), body, published_by or ""),
        )
        connection.execute(
            "INSERT INTO publish_history (scope, snapshot_json, published_by, published_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (profile_scope(tid), body, published_by or ""),
        )
        return next_version

    if conn is None:
        with _db().get_db_context() as own_conn:
            next_version = _publish(own_conn)
    else:
        next_version = _publish(conn)
    invalidate(tid)
    return next_version


def rollback(tenant_id: str, version: int, conn=None) -> bool:
    """Re-point is_current at an earlier version. Nothing is deleted."""
    tid = str(tenant_id)
    def _rollback(connection):
        row = connection.execute(
            "SELECT payload FROM tenant_profile_versions WHERE tenant_id = ? AND version = ?",
            (tid, int(version)),
        ).fetchone()
        if not row:
            return False
        _set_current(connection, tid, int(version))
        connection.execute(
            """INSERT INTO published_config (scope, snapshot_json, published_by, published_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(scope) DO UPDATE SET
                   snapshot_json = excluded.snapshot_json,
                   published_by = excluded.published_by,
                   published_at = CURRENT_TIMESTAMP""",
            (profile_scope(tid), row["payload"], "rollback"),
        )
        connection.execute(
            "INSERT INTO publish_history (scope, snapshot_json, published_by, published_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (profile_scope(tid), row["payload"], "rollback"),
        )
        return True

    if conn is None:
        with _db().get_db_context() as own_conn:
            ok = _rollback(own_conn)
    else:
        ok = _rollback(conn)
    if ok:
        invalidate(tid)
    return ok


# ── draft (working copy) ──────────────────────────────────────────────────

# A working copy nobody publishes within this window is stale by design:
# reading it after the lease expires discards it (see get_draft_config).
DRAFT_TTL_DAYS = 7.0


def get_draft(tenant_id: str) -> Optional[dict]:
    return _db().get_draft_config(
        profile_scope(tenant_id), default=None, max_age_days=DRAFT_TTL_DAYS
    )


def save_draft(tenant_id: str, payload: dict, updated_by: str = "", conn=None) -> bool:
    return _db().save_draft_config(profile_scope(tenant_id), payload, updated_by=updated_by, conn=conn)


def get_published_mirror(tenant_id: str) -> Optional[dict]:
    return _db().get_published_config(profile_scope(tenant_id), default=None)


# ── tokens ────────────────────────────────────────────────────────────────

def list_tenant_tokens(tenant_id: str) -> List[dict]:
    with _db().get_db_context() as conn:
        rows = conn.execute(
            "SELECT id, tenant_id, label, created_by, created_at, revoked_at "
            "FROM tenant_tokens WHERE tenant_id = ? ORDER BY id DESC",
            (str(tenant_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_tenant_token(token_hash: str) -> Optional[dict]:
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM tenant_tokens WHERE token_hash = ? AND revoked_at IS NULL",
            (str(token_hash),),
        ).fetchone()
    return dict(row) if row else None


def create_tenant_token(tenant_id: str, token_hash: str, label: str = "", created_by: str = "", conn=None) -> int:
    def _create(connection):
        cur = connection.execute(
            "INSERT INTO tenant_tokens (tenant_id, token_hash, label, created_by) VALUES (?, ?, ?, ?)",
            (str(tenant_id), token_hash, label, created_by),
        )
        return int(cur.lastrowid)

    if conn is None:
        with _db().get_db_context() as own_conn:
            return _create(own_conn)
    return _create(conn)


def revoke_tenant_token(token_id: int, conn=None) -> bool:
    def _revoke(connection):
        cur = connection.execute(
            "UPDATE tenant_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE id = ? AND revoked_at IS NULL",
            (int(token_id),),
        )
        return cur.rowcount > 0

    if conn is None:
        with _db().get_db_context() as own_conn:
            return _revoke(own_conn)
    return _revoke(conn)


def get_tenant_webhook_secret(tenant_id: str) -> str:
    """Per-tenant HMAC secret for outbound CRM webhooks.

    Falls back to the tenant's published profile so a secret can live in data
    rather than code. Returns "" when neither is set — the caller must then skip
    signing and log a warning.
    """
    with _db().get_db_context() as conn:
        row = conn.execute(
            "SELECT webhook_secret FROM tenants WHERE id = ?", (str(tenant_id),)
        ).fetchone()
    if row and row["webhook_secret"]:
        return row["webhook_secret"]
    payload = get_current_payload(tenant_id) or {}
    channels = (payload.get("notifications") or {}).get("channels") or []
    for ch in channels:
        if isinstance(ch, dict) and ch.get("type") == "webhook" and ch.get("secret"):
            return str(ch["secret"])
    return ""


def tenant_stats(tenant_id: str) -> Dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "current_version": current_version(tenant_id),
        "versions": list_versions(tenant_id, limit=10),
    }
