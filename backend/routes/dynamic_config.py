"""Admin-editable dynamic config endpoints.

Provides CRUD + publish/draft semantics for scopes like:
    products, b2c_menu, b2b_menu, price_list, schemes, campaigns, faq

Published config is what the bot reads. Draft config is what admins edit.
Publishing copies the current draft to published and appends to history.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from database import (
    get_db_context,
    record_admin_audit_event,
    get_published_config,
    get_draft_config,
    save_draft_config,
    publish_config,
    get_publish_history,
    build_products_snapshot,
    get_published_products,
    get_products_by_category,
)
from routes.auth import get_current_admin, require_permission

logger = logging.getLogger("dynamic_config")
router = APIRouter(prefix="/api/admin/dynamic", tags=["dynamic-config"])


class ConfigPayload(BaseModel):
    scope: str
    snapshot: Optional[dict] = {}


VALID_SCOPES = {
    "products",
    "b2c_menu",
    "b2b_menu",
    "price_list",
    "schemes",
    "campaigns",
    "faq",
    "admin_settings",
    "tenant_profile",
}

# Scopes that are versioned and tenant-scoped rather than single-row.
TENANT_SCOPED = {"tenant_profile"}


def _require_tenant(scope: str, tenant_id: Optional[str]) -> str:
    """tenant_profile is the one scope that needs a tenant dimension."""
    if scope not in TENANT_SCOPED:
        return ""
    tid = str(tenant_id or "").strip()
    if not tid:
        raise HTTPException(
            status_code=400,
            detail=f"scope '{scope}' requires a tenant_id",
        )
    return tid


def _validate_scope(scope: str) -> None:
    if scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{scope}'. Valid scopes: {sorted(VALID_SCOPES)}",
        )


@router.get("/{scope}")
def get_config(
    scope: str,
    tenant_id: Optional[str] = None,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    """Return published and draft snapshots for a scope."""
    _validate_scope(scope)
    if scope in TENANT_SCOPED:
        tid = _require_tenant(scope, tenant_id)
        from shared.tenancy import store as tenancy_store

        published = tenancy_store.get_current_payload(tid)
        draft = tenancy_store.get_draft(tid)
        return {
            "scope": scope,
            "tenant_id": tid,
            "published": published,
            "draft": draft,
            "has_draft": draft is not None,
            "version": tenancy_store.current_version(tid),
        }
    published = get_published_config(scope, default=None)
    draft = get_draft_config(scope, default=None)
    return {
        "scope": scope,
        "published": published,
        "draft": draft,
        "has_draft": draft is not None,
    }


@router.put("/{scope}")
def save_config(
    scope: str,
    payload: dict,
    request: Request,
    tenant_id: Optional[str] = None,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    """Save a draft snapshot for a scope. Does not affect the live bot."""
    _validate_scope(scope)
    snapshot = payload if isinstance(payload, dict) else payload.get("snapshot", {})
    username = current_admin.get("username", "")
    if scope in TENANT_SCOPED:
        tid = _require_tenant(scope, tenant_id)
        from shared.tenancy import store as tenancy_store

        with get_db_context() as conn:
            tenancy_store.save_draft(tid, snapshot, updated_by=username, conn=conn)
            record_admin_audit_event(
                conn,
                action="tenant_profile_draft_saved",
                actor=current_admin,
                resource_type="tenant_profile",
                resource_id=tid,
                tenant_id=tid,
                details={"changed_sections": sorted(snapshot.keys())},
            )
        logger.info(f"TENANT_PROFILE_DRAFT_SAVED | tenant={tid} | by={username}")
        return {"ok": True, "scope": scope, "tenant_id": tid, "has_draft": True}
    with get_db_context() as conn:
        ok = save_draft_config(scope, snapshot, updated_by=username, conn=conn)
        if ok:
            record_admin_audit_event(
                conn,
                action="config_draft_saved",
                actor=current_admin,
                resource_type="configuration",
                resource_id=scope,
                details={"scope": scope},
            )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save draft")
    logger.info(f"DRAFT_SAVED | scope={scope} | by={username}")
    return {"ok": True, "scope": scope, "has_draft": True}



@router.post("/{scope}/build-draft")
def build_draft(
    scope: str,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    """Regenerate the draft snapshot from the current DB rows (products only)."""
    _validate_scope(scope)
    if scope != "products":
        raise HTTPException(
            status_code=400,
            detail=f"build-draft is only supported for scope 'products'",
        )
    snapshot = build_products_snapshot()
    username = current_admin.get("username", "")
    with get_db_context() as conn:
        ok = save_draft_config(scope, snapshot, updated_by=username, conn=conn)
        if ok:
            record_admin_audit_event(
                conn,
                action="config_draft_built",
                actor=current_admin,
                resource_type="configuration",
                resource_id=scope,
                details={"scope": scope},
            )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save draft")
    logger.info(f"DRAFT_BUILT | scope={scope} | by={username}")
    return {"ok": True, "scope": scope, "has_draft": True}


@router.post("/{scope}/publish")
def publish(
    scope: str,
    tenant_id: Optional[str] = None,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    """Publish the current draft snapshot so the bot picks it up."""
    _validate_scope(scope)
    username = current_admin.get("username", "")

    if scope in TENANT_SCOPED:
        return _publish_tenant_profile(scope, tenant_id, username, actor=current_admin)

    # For products, the canonical draft is auto-generated from the products table.
    if scope == "products":
        snapshot = build_products_snapshot()

    with get_db_context() as conn:
        if scope == "products":
            save_draft_config(scope, snapshot, updated_by=username, conn=conn)
        ok = publish_config(scope, published_by=username, conn=conn)
        if ok:
            record_admin_audit_event(
                conn,
                action="config_published",
                actor=current_admin,
                resource_type="configuration",
                resource_id=scope,
                tenant_id=tenant_id,
                details={"scope": scope},
            )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"No draft exists for scope '{scope}' to publish",
        )
    logger.info(f"PUBLISHED | scope={scope} | by={username}")
    return {"ok": True, "scope": scope, "published": True}


def _publish_tenant_profile(scope: str, tenant_id: Optional[str], username: str, actor: dict | None = None) -> dict:
    """Validate the merged profile, then append a new version and go live.

    Validation runs against defaults + file + draft BEFORE the write, so an
    invalid profile can never reach the bot. On success the cache is purged and
    the loader picks up the new version on the next message.
    """
    from shared.tenancy import loader as tenancy_loader
    from shared.tenancy import store as tenancy_store
    from shared.tenancy import cache as tenancy_cache

    tid = _require_tenant(scope, tenant_id)
    draft = tenancy_store.get_draft(tid)
    if draft is None:
        raise HTTPException(
            status_code=400,
            detail=f"No draft exists for tenant '{tid}' to publish",
        )

    try:
        profile = tenancy_loader.validate_merged_profile(tid, draft)
    except tenancy_loader.ProfileValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Profile failed validation, nothing published: {exc}",
        )

    with get_db_context() as conn:
        version = tenancy_store.publish_version(tid, draft, published_by=username, conn=conn)
        if actor:
            record_admin_audit_event(
                conn,
                action="tenant_profile_published",
                actor=actor,
                resource_type="tenant_profile",
                resource_id=tid,
                tenant_id=tid,
                details={"version": version},
            )
    tenancy_cache.purge(tid)
    logger.info(f"TENANT_PROFILE_PUBLISHED | tenant={tid} | version={version} | by={username}")
    return {
        "ok": True,
        "scope": scope,
        "tenant_id": tid,
        "published": True,
        "version": version,
        "vertical": profile.vertical,
        "active_intents": profile.active_intent_names(),
    }



# ── Convenience: published products for the bot ───────────────────────────

@router.get("/products/feed")
def products_feed(
    category: Optional[str] = None,
    limit: int = 100,
):
    """Public-ish feed of published products (used by bot workflows)."""
    return {"products": get_published_products(category=category, limit=limit)}


@router.get("/{scope}/history")
def history(
    scope: str,
    limit: int = 20,
    tenant_id: Optional[str] = None,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    """Return recent publish events for a scope."""
    _validate_scope(scope)
    if scope in TENANT_SCOPED:
        tid = _require_tenant(scope, tenant_id)
        from shared.tenancy import store as tenancy_store

        return {
            "scope": scope,
            "tenant_id": tid,
            "history": [
                {**v, "published_at": v.get("created_at")}
                for v in tenancy_store.list_versions(tid, limit=limit)
            ],
        }
    return {"scope": scope, "history": get_publish_history(scope, limit=limit)}

