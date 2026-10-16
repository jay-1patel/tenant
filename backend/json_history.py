"""Append every chat exchange to a per-tenant, per-day JSON file.

The SQLite ``chat_history`` table stays the primary store (the admin console and
APIs read from it). This module writes an additional, human-readable JSON audit
trail alongside each insert, one file per tenant per calendar day:

    <PROJECT_ROOT>/exports/logs/<tenant_id>/<YYYY-MM-DD>.json

Each file is a JSON object::

    {
      "tenant_id": "l",
      "date": "2026-10-16",
      "updated_at": "2026-10-16T11:30:00",
      "count": 3,
      "messages": [
        {"wa_id": "...", "sender_name": "...", "message": "...",
         "response": "...", "route": "send2", "created_at": "..."},
        ...
      ]
    }

Writes are guarded by a process lock and made atomic (temp file + replace) so a
crash mid-write cannot leave a half-written, invalid JSON file.
"""

import json
import os
import re
import logging
import threading
from datetime import datetime

logger = logging.getLogger("json_history")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
LOG_ROOT = os.path.join(PROJECT_ROOT, "exports", "logs")

_LOCK = threading.Lock()
_SAFE_TENANT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_tenant(tenant_id: str | None) -> str:
    """Filesystem-safe tenant folder name; unknown tenants go to `_default`."""
    name = _SAFE_TENANT.sub("_", (tenant_id or "").strip()) or "_default"
    # Guard against path traversal via dots only.
    name = name.strip(".") or "_default"
    return name


def _file_path(tenant_id: str | None, day: str) -> str:
    return os.path.join(LOG_ROOT, _safe_tenant(tenant_id), f"{day}.json")


def append_chat(
    wa_id: str,
    sender_name: str,
    message: str,
    response: str,
    route: str = "faq",
    tenant_id: str | None = None,
    created_at: str | None = None,
) -> None:
    """Append one exchange to the tenant's daily JSON log.

    Never raises: a logging failure must not break message handling.
    """
    try:
        created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        day = created_at[:10]
        record = {
            "wa_id": wa_id,
            "sender_name": sender_name or "",
            "message": message,
            "response": response,
            "route": route,
            "created_at": created_at,
        }
        path = _file_path(tenant_id, day)
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {"tenant_id": tenant_id, "date": day, "messages": []}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict) and isinstance(loaded.get("messages"), list):
                        data = loaded
                    elif isinstance(loaded, list):
                        data = {"tenant_id": tenant_id, "date": day, "messages": loaded}
                except (json.JSONDecodeError, OSError):
                    # Corrupt file: keep a backup once, then start fresh.
                    try:
                        os.replace(path, path + ".corrupt")
                    except OSError:
                        pass
            data["tenant_id"] = tenant_id
            data["date"] = day
            data["messages"].append(record)
            data["count"] = len(data["messages"])
            data["updated_at"] = datetime.now().isoformat(timespec="seconds")

            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
    except Exception as e:  # pragma: no cover - best-effort audit trail
        logger.warning(f"json_history append failed for {wa_id}: {e}")
