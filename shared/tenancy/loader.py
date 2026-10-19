"""Resolve a tenant's effective profile.

    vertical defaults  ->  clients/<id>/config.json  ->  DB current version

then deep-merge, validate with pydantic, and cache under (tenant_id, version).

A new client is a new data row plus an optional config file. Zero code changes
(decision D5).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from . import cache, store
from .defaults import DEFAULT_FLOWS, DEFAULT_TENANT_ID, get_vertical_defaults
from .merge import collect_strings, merge_layers
from .paths import client_config_path, client_dir
from .schemas import TenantProfile

logger = logging.getLogger("tenancy.loader")


class ProfileValidationError(ValueError):
    """The merged profile failed pydantic validation. Rejected at write time."""


# ── layers ────────────────────────────────────────────────────────────────

def load_file_layer(tenant_id: str) -> Dict[str, Any]:
    """clients/<tenant_id>/config.json. A missing file is not an error."""
    path = client_config_path(tenant_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Could not read profile file for %s at %s: %s", tenant_id, path, exc)
        return {}
    if not isinstance(data, dict):
        logger.error("Profile file for %s must be a JSON object, got %s", tenant_id, type(data).__name__)
        return {}
    return data


def _strip_wrapper(data: Dict[str, Any]) -> Dict[str, Any]:
    """Allow {"tenant_profile": {...}} as a wrapper for admin exports."""
    inner = data.get("tenant_profile")
    return inner if isinstance(inner, dict) else data


def write_client_config_file(tenant_id: str, layer: Dict[str, Any]) -> Optional[str]:
    """Mirror a published override layer back into clients/<id>/config.json.

    The admin console saves edits to the draft/published DB layer only, so the
    on-disk client pack drifts from what was just published. This writes the
    published layer merged over the file's current contents (keyed by name for
    flows / intents / menu buttons), so untouched file content is preserved and
    only the published keys are updated. Vertical defaults are never written -
    the file stays a thin override layer.

    Returns the path written, or None when the tenant has no client pack (we
    never invent one). Raises on I/O errors so the caller can log and continue.
    """
    d = client_dir(tenant_id)
    if not d.exists():
        return None
    path = client_config_path(tenant_id)
    existing = _strip_wrapper(load_file_layer(tenant_id))
    merged = merge_layers(existing, layer or {})
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return str(path)


# ── build ─────────────────────────────────────────────────────────────────

def build_profile(tenant_id: str, *, db_layer: Optional[Dict[str, Any]] = None,
                  file_layer: Optional[Dict[str, Any]] = None,
                  include_db: bool = True) -> TenantProfile:
    """Merge the layers and validate. Raises ProfileValidationError on bad data.

    ``include_db=False`` builds the profile from defaults + file only — used by
    publish to validate a draft against the file baseline, and by the linter.
    """
    tid = str(tenant_id or DEFAULT_TENANT_ID)

    if file_layer is None:
        file_layer = load_file_layer(tid)
    file_layer = _strip_wrapper(file_layer)

    if db_layer is None and include_db:
        db_layer = store.get_current_payload(tid)
    db_layer = _strip_wrapper(db_layer) if db_layer else {}

    # Vertical precedence mirrors the layer precedence: a published override can
    # move a tenant to a different vertical, then the pack file, then whatever
    # vertical the tenant was registered with, then generic.
    record = store.get_tenant(tid) or {}
    vertical = str(
        db_layer.get("vertical")
        or file_layer.get("vertical")
        or record.get("vertical")
        or "generic"
    )

    defaults = get_vertical_defaults(vertical)
    # Reusable flow skeletons sit beneath the vertical's own data. A vertical can
    # add flows; a tenant can override any single flow by shipping one with the
    # same name (merge is keyed on name, not position).
    defaults = merge_layers({"flows": DEFAULT_FLOWS}, defaults)

    merged = merge_layers(defaults, file_layer, db_layer)
    merged["tenant_id"] = tid
    merged.setdefault("vertical", vertical)
    if record.get("display_name") and not merged.get("display_name"):
        merged["display_name"] = record["display_name"]
    if record.get("status"):
        merged["status"] = record["status"]
    merged.pop("version", None)
    merged.pop("source", None)

    try:
        return TenantProfile(**merged)
    except Exception as exc:  # pydantic ValidationError and friends
        raise ProfileValidationError(str(exc)) from exc


# ── public API ────────────────────────────────────────────────────────────

def get_tenant_profile(tenant_id: str = DEFAULT_TENANT_ID) -> TenantProfile:
    """The effective, validated, cached profile for a tenant.

    Never raises for a healthy tenant: a broken DB override layer falls back to
    defaults + file and logs loudly, because taking the bot down over a bad
    config is worse than serving a slightly-off profile.
    """
    tid = str(tenant_id or DEFAULT_TENANT_ID)
    version = store.current_version(tid)

    hit = cache.get(tid, version)
    if hit is not None:
        return hit

    try:
        profile = build_profile(tid)
    except ProfileValidationError as exc:
        logger.error("PROFILE_INVALID | tenant=%s | version=%s | %s", tid, version, exc)
        # Last resort: defaults for the recorded vertical, nothing from disk/DB.
        record = store.get_tenant(tid) or {}
        profile = TenantProfile(
            tenant_id=tid,
            **get_vertical_defaults(str(record.get("vertical") or "generic")),
        )

    profile.version = version
    profile.source = f"v{version}" if version else "file"
    cache.put(profile)
    return profile


def get_cached_profile(tenant_id: str = DEFAULT_TENANT_ID) -> Optional[TenantProfile]:
    """Cache-only lookup. Used by hot paths that must not hit the DB."""
    tid = str(tenant_id or DEFAULT_TENANT_ID)
    return cache.get(tid, store.current_version(tid))


def reload_profile(tenant_id: str = DEFAULT_TENANT_ID) -> TenantProfile:
    """Force a rebuild (used after a file edit on disk)."""
    tid = str(tenant_id or DEFAULT_TENANT_ID)
    cache.purge(tid)
    store.invalidate(tid)
    return get_tenant_profile(tid)


def validate_merged_profile(tenant_id: str, draft: Dict[str, Any]) -> TenantProfile:
    """Validate a candidate draft against defaults + file, ignoring the DB layer.

    This is the gate publish runs *before* writing a version, so an invalid
    profile can never reach the bot.
    """
    return build_profile(
        tenant_id,
        db_layer=draft,
        file_layer=None,
        include_db=False,
    )


# ── introspection helpers (admin UI, linters, eval harness) ───────────────

def profile_strings(profile: TenantProfile, exclude: tuple = ()) -> list[str]:
    """Every string in the profile - the input for the forbidden-term lint.

    ``exclude`` drops whole branches, as dotted paths. The linter needs this:
    ``guardrails.forbidden_terms`` is the list of banned words, so scanning it
    against itself would report every term as a leak of itself.
    """
    payload = profile.to_payload()
    for key_path in exclude:
        parts = key_path.split(".")
        node = payload
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return collect_strings(payload)


def describe_layers(tenant_id: str) -> Dict[str, Any]:
    """Layer-by-layer view for the admin profile editor."""
    tid = str(tenant_id or DEFAULT_TENANT_ID)
    record = store.get_tenant(tid) or {}
    file_layer = load_file_layer(tid)
    db_layer = store.get_current_payload(tid)
    defaults = get_vertical_defaults(str(record.get("vertical") or "generic"))
    return {
        "tenant": record,
        "layers": {
            "defaults": defaults,
            "file": file_layer,
            "db": db_layer,
        },
        "current_version": store.current_version(tid),
        "versions": store.list_versions(tid, limit=20),
    }
