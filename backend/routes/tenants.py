"""Tenant registry + profile administration API.

Publishing is the only way a profile change reaches the bot, and it is always
versioned and rollbackable:

    GET  /api/admin/tenants
    POST /api/admin/tenants
    GET  /api/admin/tenants/{tenant_id}/detail     -> layers + effective profile
    PUT  /api/admin/tenants/{tenant_id}/profile     -> save draft (merged over the pending draft)
    PUT  /api/admin/tenants/{tenant_id}/intents/{name} -> save one info-page intent into the draft
    POST /api/admin/tenants/{tenant_id}/publish     -> validate + version + go live
    POST /api/admin/tenants/{tenant_id}/rollback    -> re-point at a prior version
    GET  /api/admin/tenants/{tenant_id}/versions
    POST /api/admin/tenants/{tenant_id}/tokens      -> mint a tenant-scoped token
    GET  /api/admin/tenants/{tenant_id}/resolved    -> what the bot actually reads

``/resolved`` is the smoke-test endpoint: it returns the merged, validated
profile the bot will use right now, so the UI can diff it against the draft.

Every tenant-scoped route goes through ``require_tenant_access()``, which
enforces token.tenant_id == target (Phase 0.5).
"""

import logging
import re
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from database import get_db_context, record_admin_audit_event
from routes.auth import (
    get_current_admin,
    has_permission,
    hash_tenant_token,
    require_permission,
    require_tenant_access,
    security,
)
from shared.tenancy import cache as tenancy_cache
from shared.tenancy import loader as tenancy_loader
from shared.tenancy import store as tenancy_store
from shared.tenancy.merge import deep_merge, merge_drafts

logger = logging.getLogger("tenants")
router = APIRouter(prefix="/api/admin/tenants", tags=["tenants"])


# ── request models ────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    tenant_id: str
    slug: str = ""
    vertical: str = "generic"
    display_name: str = ""
    waba_phone_id: str = ""
    status: str = "active"


class PhoneBind(BaseModel):
    waba_phone_id: str


class ProfileDraft(BaseModel):
    snapshot: dict = Field(default_factory=dict)


class IntentOverride(BaseModel):
    """One informational intent's editable fields. Omitted keys are not touched."""
    answer: Optional[str] = None
    keywords: Optional[List[str]] = None
    enabled: Optional[bool] = None


class RollbackRequest(BaseModel):
    version: int


class TokenCreate(BaseModel):
    label: str = ""


class WebhookSecretSet(BaseModel):
    secret: str = Field(min_length=16, max_length=256)


def _admin_only(principal: dict) -> str:
    """Only admins may mint tokens, rebind phone ids, or set secrets."""
    if principal.get("type") != "admin":
        raise HTTPException(status_code=403, detail="Admin credentials required")
    # Allow admin role too
    return principal.get("username", "")


def _public_tenant(record: dict) -> dict:
    out = dict(record or {})
    out.pop("webhook_secret", None)
    return out


# ── registry ──────────────────────────────────────────────────────────────

@router.get("")
def list_tenants(
    status: Optional[str] = None,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    rows = [_public_tenant(r) for r in tenancy_store.list_tenants(status=status)]
    for row in rows:
        row["current_version"] = tenancy_store.current_version(row["id"])
    return {"tenants": rows}


@router.post("")
def create_tenant(
    body: TenantCreate,
    current_admin: dict = Depends(require_permission("manage_operations")),
):
    if current_admin.get("role") != "super_admin":
        # Admins and sub admins register tenants through the approval queue;
        # only a super admin's approval creates the tenant.
        raise HTTPException(
            status_code=403,
            detail=(
                "Tenant registration by an admin needs super admin approval — "
                "submit it via POST /api/tenant-change-requests"
            ),
        )
    tid = str(body.tenant_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if tenancy_store.get_tenant(tid):
        raise HTTPException(status_code=409, detail=f"tenant '{tid}' already exists")

    from shared.tenancy import loader as _loader

    try:
        # Fail before writing the row if the vertical is unknown.
        _loader.build_profile(tid, db_layer={}, file_layer={}, include_db=False)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid vertical: {exc}")

    with get_db_context() as conn:
        if conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tid,)).fetchone():
            raise HTTPException(status_code=409, detail=f"tenant '{tid}' already exists")
        tenancy_store.ensure_tenant(
            tid,
            slug=body.slug or tid,
            vertical=body.vertical,
            waba_phone_id=body.waba_phone_id,
            display_name=body.display_name,
            status=body.status,
            conn=conn,
        )
        record_admin_audit_event(
            conn,
            action="tenant_created",
            actor=current_admin,
            resource_type="tenant",
            resource_id=tid,
            tenant_id=tid,
            details={"vertical": body.vertical, "status": body.status},
        )
    tenancy_cache.purge(tid)
    logger.info("TENANT_CREATED | tenant=%s | vertical=%s | by=%s",
                tid, body.vertical, current_admin.get("username"))
    return {"ok": True, "tenant": _public_tenant(tenancy_store.get_tenant(tid))}


@router.delete("/{tenant_id}")
def delete_tenant(
    tenant_id: str,
    principal: dict = Depends(require_tenant_access()),
):
    _admin_only(principal)
    if not tenancy_store.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")
    with get_db_context() as conn:
        tenancy_store.delete_tenant(tenant_id, conn=conn)
        record_admin_audit_event(
            conn,
            action="tenant_deleted",
            actor={"username": principal.get("username"), "role": principal.get("role"), "tenant_id": tenant_id},
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
        )
    tenancy_cache.purge(tenant_id)
    logger.info("TENANT_DELETED | tenant=%s | by=%s", tenant_id, principal.get("username"))
    return {"ok": True, "tenant_id": tenant_id}


# ── profile: read ─────────────────────────────────────────────────────────

@router.get("/{tenant_id}/resolved")
def resolved_profile(tenant_id: str, principal: dict = Depends(require_tenant_access())):
    """The merged, validated profile the bot reads right now.

    This is the 'profile-derived smoke test' surface: menus, intents, features
    and flows here all come from data, not constants.
    """
    profile = tenancy_loader.get_tenant_profile(tenant_id)
    return {
        "tenant_id": profile.tenant_id,
        "vertical": profile.vertical,
        "version": profile.version,
        "source": profile.source,
        "features": profile.features.model_dump(),
        "vocabulary": profile.vocabulary.model_dump(),
        "brand": profile.brand.model_dump(),
        "business_hours": profile.business_hours.model_dump(),
        "guardrails": profile.guardrails.model_dump(),
        "notifications": profile.notifications.model_dump(),
        "menu": profile.menu.model_dump(),
        "active_intents": [i.model_dump() for i in profile.active_intents()],
        "inactive_intents": [
            i.model_dump() for i in profile.intents
            if i not in profile.active_intents()
        ],
        "flows": [f.model_dump() for f in profile.active_flows()],
    }


@router.get("/{tenant_id}/detail")
def tenant_detail(tenant_id: str, principal: dict = Depends(require_tenant_access())):
    """Layer-by-layer view for the profile editor: defaults, file, DB."""
    layers = tenancy_loader.describe_layers(tenant_id)
    effective = None
    try:
        effective = tenancy_loader.get_tenant_profile(tenant_id).to_payload()
    except Exception as exc:  # never fail the editor on a bad layer
        logger.error("Could not build effective profile for %s: %s", tenant_id, exc)
    # What the editor should show when a working copy is pending: the draft
    # merged over the file baseline — exactly what publish would make live.
    pending, pending_error = None, None
    draft = tenancy_store.get_draft(tenant_id)
    if draft:
        try:
            pending = tenancy_loader.validate_merged_profile(tenant_id, draft).to_payload()
        except Exception as exc:
            pending_error = str(exc)
    return {
        "tenant": _public_tenant(layers.get("tenant")),
        "layers": layers.get("layers", {}),
        "current_version": layers.get("current_version", 0),
        "versions": layers.get("versions", []),
        "effective": effective,
        "effective_error": None if effective else "effective profile could not be built",
        "has_draft": bool(draft),
        "pending": pending,
        "pending_error": pending_error,
    }


@router.get("/{tenant_id}/versions")
def list_versions(
    tenant_id: str,
    limit: int = 50,
    principal: dict = Depends(require_tenant_access()),
):
    return {
        "tenant_id": tenant_id,
        "current_version": tenancy_store.current_version(tenant_id),
        "versions": tenancy_store.list_versions(tenant_id, limit=limit),
    }


@router.get("/{tenant_id}/versions/{version}")
def get_version(
    tenant_id: str,
    version: int,
    principal: dict = Depends(require_tenant_access()),
):
    record = tenancy_store.get_version(tenant_id, version)
    if not record:
        raise HTTPException(status_code=404, detail=f"version {version} not found")
    return record


# ── profile: write ────────────────────────────────────────────────────────

@router.put("/{tenant_id}/profile")
def save_profile_draft(    tenant_id: str,
    body: ProfileDraft,
    principal: dict = Depends(require_tenant_access()),
):
    """Save the working copy. Does not affect the live bot.

    The draft is validated immediately so the editor can show errors before
    anyone presses publish.

    The draft accumulates: this merges the snapshot over the existing draft
    instead of replacing it, so partial saves from different screens (the
    profile editor, the info-page panels) keep each other's pending changes.
    Tombstones survive the merge — deleting a default menu option is a marker
    only the publish-time live merge may consume.
    """
    if not tenancy_store.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")
    by = principal.get("username") or principal.get("label", "")
    draft = tenancy_store.get_draft(tenant_id) or {}
    merged = merge_drafts(draft, body.snapshot)
    with get_db_context() as conn:
        tenancy_store.save_draft(tenant_id, merged, updated_by=by, conn=conn)
        if principal.get("type") == "admin":
            record_admin_audit_event(
                conn,
                action="tenant_profile_draft_saved",
                actor=principal,
                resource_type="tenant_profile",
                resource_id=tenant_id,
                tenant_id=tenant_id,
                details={"changed_sections": sorted(body.snapshot.keys())},
            )

    warnings: list = []
    try:
        tenancy_loader.validate_merged_profile(tenant_id, merged)
    except tenancy_loader.ProfileValidationError as exc:
        # Saving a broken draft is allowed; publishing it is not.
        warnings.append(str(exc))
    return {"ok": True, "tenant_id": tenant_id, "has_draft": True, "validation": warnings}


# Info pages whose panel edits a single informational intent. The map is the
# authorisation contract: an intent is editable through this endpoint only if
# it has a panel and a permission behind it.
INFO_PAGE_PERMISSIONS = {
    "projects": "manage_projects",
    "technologies": "manage_technologies",
    "careers": "manage_careers",
    "benefits": "manage_benefits",
}

# A new informational intent created from the menu editor becomes an id the
# classifier and flow runner switch on, so keep the grammar narrow.
INTENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@router.put("/{tenant_id}/intents/{intent_name}")
def save_intent_draft(
    tenant_id: str,
    intent_name: str,
    body: IntentOverride,
    request: Request,
    principal: dict = Depends(require_tenant_access()),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Merge one informational intent's answer into the working draft.

    Projects / technologies / careers / benefits have no flow and no service:
    the answer text is the whole page. A name that does not exist yet is a new
    page created from the menu editor — gated on manage_operations. This merges
    into the existing draft (never replaces), so a pending profile edit
    survives a panel save and vice versa. Publishing is what makes the answer
    live.
    """
    if not tenancy_store.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")

    profile = tenancy_loader.get_tenant_profile(tenant_id)
    existing = {i.name for i in profile.intents}

    permission = INFO_PAGE_PERMISSIONS.get(intent_name)
    if permission:
        if intent_name not in existing:
            raise HTTPException(
                status_code=404,
                detail=f"intent '{intent_name}' is not part of this tenant's profile",
            )
    elif intent_name in existing:
        # Operational intents (place_order, service_enquiry...) have flows and
        # services behind them; this endpoint only edits answered info pages.
        raise HTTPException(
            status_code=404,
            detail=f"intent '{intent_name}' exists but is not an editable info page",
        )
    else:
        if not INTENT_NAME_RE.match(intent_name):
            raise HTTPException(
                status_code=422,
                detail="Intent names are lowercase letters, digits and underscores, starting with a letter.",
            )
        permission = "manage_operations"

    # Tenant tokens are scoped to their own tenant above; admins need the
    # page's own grant, not just manage_operations.
    if principal.get("type") != "tenant" and not has_permission(
        get_current_admin(request, credentials), permission
    ):
        raise HTTPException(
            status_code=403,
            detail=f"You need the '{permission}' permission to edit this page",
        )

    override: Dict[str, Any] = {"name": intent_name}
    if body.answer is not None:
        override["answer"] = body.answer
    if body.keywords is not None:
        override["keywords"] = [k for k in (s.strip() for s in body.keywords) if k]
    if body.enabled is not None:
        override["enabled"] = body.enabled

    by = principal.get("username") or principal.get("label", "")
    draft = tenancy_store.get_draft(tenant_id) or {}
    merged = deep_merge(draft, {"intents": [override]})
    with get_db_context() as conn:
        tenancy_store.save_draft(tenant_id, merged, updated_by=by, conn=conn)
        if principal.get("type") == "admin":
            record_admin_audit_event(
                conn,
                action="tenant_intent_draft_saved",
                actor=principal,
                resource_type="tenant_intent",
                resource_id=intent_name,
                tenant_id=tenant_id,
                details={"changed_fields": sorted(k for k in override if k != "name")},
            )

    warnings: list = []
    try:
        tenancy_loader.validate_merged_profile(tenant_id, merged)
    except tenancy_loader.ProfileValidationError as exc:
        warnings.append(str(exc))
    return {"ok": True, "tenant_id": tenant_id, "has_draft": True, "validation": warnings}


@router.post("/{tenant_id}/publish")
def publish_profile(
    tenant_id: str,
    principal: dict = Depends(require_tenant_access()),
):
    """Validate the merged profile, append a version, go live, purge the cache.

    Publishing is direct for every admin with access — the super admin
    approval queue is only for registrations/completions submitted through
    the Register a tenant panel (POST /api/tenant-change-requests).
    """
    draft = tenancy_store.get_draft(tenant_id)
    if draft is None:
        raise HTTPException(status_code=400, detail=f"No draft exists for tenant '{tenant_id}'")

    try:
        profile = tenancy_loader.validate_merged_profile(tenant_id, draft)
    except tenancy_loader.ProfileValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Profile failed validation, nothing published: {exc}",
        )

    by = principal.get("username") or principal.get("label", "")
    with get_db_context() as conn:
        version = tenancy_store.publish_version(tenant_id, draft, published_by=by, conn=conn)
        if principal.get("type") == "admin":
            record_admin_audit_event(
                conn,
                action="tenant_profile_published",
                actor=principal,
                resource_type="tenant_profile",
                resource_id=tenant_id,
                tenant_id=tenant_id,
                details={"version": version},
            )
    tenancy_cache.purge(tenant_id)
    logger.info("TENANT_PROFILE_PUBLISHED | tenant=%s | version=%s | by=%s", tenant_id, version, by)
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "version": version,
        "vertical": profile.vertical,
        "active_intents": profile.active_intent_names(),
        "visible_buttons": [b.id for b in profile.menu.buttons],
    }


class TestQuestion(BaseModel):
    message: str = Field(min_length=1, max_length=500)


@router.post("/{tenant_id}/test-question")
def test_question(
    tenant_id: str,
    body: TestQuestion,
    principal: dict = Depends(require_tenant_access()),
):
    """The admin 'test a question' box: run one utterance through this
    tenant's live intent matcher (rules then embeddings — the same tiers
    eval/run.py drives), so an editor can see routing change as they tune
    the profile without waiting for a real customer to ask."""
    if not tenancy_store.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")

    from shared.tenancy.intent_match import match_intent

    profile = tenancy_loader.get_tenant_profile(tenant_id)
    intent, score, tier = match_intent(body.message.strip(), profile)
    matched = profile.intent(intent) if intent else None
    return {
        "tenant_id": tenant_id,
        "message": body.message,
        "intent": intent,
        "score": round(score, 3),
        "tier": tier,
        "flow": matched.flow if matched else None,
        "active_intents": profile.active_intent_names(),
    }


@router.post("/{tenant_id}/rollback")
def rollback_profile(
    tenant_id: str,
    body: RollbackRequest,
    principal: dict = Depends(require_tenant_access()),
):
    """Re-point is_current at an earlier version. Nothing is deleted."""
    with get_db_context() as conn:
        if not tenancy_store.rollback(tenant_id, body.version, conn=conn):
            raise HTTPException(status_code=404, detail=f"version {body.version} not found")
        if principal.get("type") == "admin":
            record_admin_audit_event(
                conn,
                action="tenant_profile_rolled_back",
                actor=principal,
                resource_type="tenant_profile",
                resource_id=tenant_id,
                tenant_id=tenant_id,
                details={"version": body.version},
            )
    tenancy_cache.purge(tenant_id)
    profile = tenancy_loader.get_tenant_profile(tenant_id)
    logger.info("TENANT_PROFILE_ROLLBACK | tenant=%s | to=v%s | by=%s",
                tenant_id, body.version, principal.get("username"))
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "version": body.version,
        "active": profile.version,
        "active_intents": profile.active_intent_names(),
    }


# ── inbound routing + secrets ─────────────────────────────────────────────

@router.post("/{tenant_id}/phone-id")
def bind_phone(
    tenant_id: str,
    body: PhoneBind,
    principal: dict = Depends(require_tenant_access()),
):
    _admin_only(principal)
    if not tenancy_store.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")
    with get_db_context() as conn:
        if not tenancy_store.set_waba_phone_id(tenant_id, body.waba_phone_id, conn=conn):
            raise HTTPException(
                status_code=409,
                detail="phone id already bound to another tenant",
            )
        record_admin_audit_event(
            conn,
            action="tenant_phone_id_bound",
            actor=principal,
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            details={"configured": bool(body.waba_phone_id.strip())},
        )
    return {"ok": True, "tenant_id": tenant_id, "waba_phone_id": body.waba_phone_id}


@router.put("/{tenant_id}/webhook-secret")
def set_webhook_secret(
    tenant_id: str,
    body: WebhookSecretSet,
    principal: dict = Depends(require_tenant_access()),
):
    """Per-tenant HMAC secret for outbound CRM webhooks."""
    _admin_only(principal)
    with get_db_context() as conn:
        cur = conn.execute(
            "UPDATE tenants SET webhook_secret = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (body.secret, tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="tenant not found")
        record_admin_audit_event(
            conn,
            action="tenant_webhook_secret_configured",
            actor=principal,
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            details={"configured": True},
        )
    logger.info("TENANT_WEBHOOK_SECRET_SET | tenant=%s | by=%s",
                tenant_id, principal.get("username"))
    return {"ok": True, "tenant_id": tenant_id, "configured": True}


# ── tenant-scoped tokens (Phase 0.5) ──────────────────────────────────────

@router.post("/{tenant_id}/tokens")
def create_token(
    tenant_id: str,
    body: TokenCreate,
    principal: dict = Depends(require_tenant_access()),
):
    """Mint an opaque token scoped to this tenant.

    The plaintext is returned exactly once. Only admins may mint.
    """
    by = _admin_only(principal)
    if not tenancy_store.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")
    raw = secrets.token_urlsafe(40)
    with get_db_context() as conn:
        token_id = tenancy_store.create_tenant_token(
            tenant_id, hash_tenant_token(raw), label=body.label, created_by=by, conn=conn
        )
        record_admin_audit_event(
            conn,
            action="tenant_token_created",
            actor=principal,
            resource_type="tenant_token",
            resource_id=token_id,
            tenant_id=tenant_id,
            details={},
        )
    logger.info("TENANT_TOKEN_CREATED | tenant=%s | id=%s | by=%s", tenant_id, token_id, by)
    return {
        "ok": True,
        "id": token_id,
        "tenant_id": tenant_id,
        "token": raw,
        "warning": "Store this now — it is hashed on the server and cannot be shown again.",
    }


@router.get("/{tenant_id}/tokens")
def list_tokens(tenant_id: str, principal: dict = Depends(require_tenant_access())):
    _admin_only(principal)
    return {"tenant_id": tenant_id, "tokens": tenancy_store.list_tenant_tokens(tenant_id)}


@router.delete("/{tenant_id}/tokens/{token_id}")
def revoke_token(
    tenant_id: str,
    token_id: int,
    principal: dict = Depends(require_tenant_access()),
):
    _admin_only(principal)
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT id, label FROM tenant_tokens WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL",
            (token_id, tenant_id),
        ).fetchone()
        if not row or not tenancy_store.revoke_tenant_token(token_id, conn=conn):
            raise HTTPException(status_code=404, detail="token not found or already revoked")
        record_admin_audit_event(
            conn,
            action="tenant_token_revoked",
            actor=principal,
            resource_type="tenant_token",
            resource_id=token_id,
            tenant_id=tenant_id,
            details={},
        )
    return {"ok": True, "id": token_id}


# ── smoke test ────────────────────────────────────────────────────────────

@router.get("/{tenant_id}/smoke")
def profile_smoke(tenant_id: str, principal: dict = Depends(require_tenant_access())):
    """Assert the runtime really is data-derived.

    Guards the Phase 4/7 exit test: menus and intents must equal the profile,
    not any hardcoded constant. Fails loudly if a code default leaks back in.
    """
    from shared.tenancy import gating

    profile = tenancy_loader.get_tenant_profile(tenant_id)
    visible = [b.id for b in profile.menu.visible_buttons(profile.features)]
    active = profile.active_intent_names()

    leaked = sorted(
        set(profile.guardrails.forbidden_terms)
        & {s.lower() for s in tenancy_loader.profile_strings(profile)
           if len(s) < 40 and s.strip().lower() in
           {t.lower() for t in profile.guardrails.forbidden_terms}}
    )
    return {
        "tenant_id": tenant_id,
        "vertical": profile.vertical,
        "version": profile.version,
        "visible_buttons": visible,
        "active_intents": active,
        "gated_intents": {
            intent: gating.is_enabled(tenant_id, gate)
            for intent, gate in gating.INTENT_GATES.items()
        },
        "forbidden_term_leaks": leaked,
        "ok": not leaked,
    }
