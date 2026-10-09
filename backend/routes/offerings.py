"""Tenant-scoped records — the content table behind each vertical's panel.

Every tenant owns a table of records (products, services, packages, departments)
and shapes it differently. That shape is data: `shared/tenancy/records.py` seeds
the columns from the tenant's vertical, and this router lets an admin add, rename,
retype and drop them — each change is a real `ALTER TABLE` on `products`, not a
JSON blob pretending to be a schema.

    GET    /api/admin/tenants/{tenant_id}/record-schema
    POST   /api/admin/tenants/{tenant_id}/record-schema/columns
    PUT    /api/admin/tenants/{tenant_id}/record-schema/columns/{key}
    DELETE /api/admin/tenants/{tenant_id}/record-schema/columns/{key}
    POST   /api/admin/tenants/{tenant_id}/record-schema/reset

    GET    /api/admin/tenants/{tenant_id}/offerings
    POST   /api/admin/tenants/{tenant_id}/offerings
    PUT    /api/admin/tenants/{tenant_id}/offerings/{offering_id}
    DELETE /api/admin/tenants/{tenant_id}/offerings/{offering_id}
    GET    /api/admin/tenants/{tenant_id}/offerings/categories

The tenant is a path segment, so ``require_tenant_access()`` checks the token
against the tenant actually addressed - never one supplied in a body or query.
The legacy ``/catalog`` routes stay for the pre-tenant stack and keep resolving
to the default tenant.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from database import (
    delete_product,
    get_db_context,
    get_product,
    list_products,
    save_product,
    update_product,
)
from routes.auth import get_current_admin, has_permission, require_tenant_access, security
from shared.tenancy import records as record_schema

logger = logging.getLogger("offerings")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}", tags=["offerings"])

try:
    from services.audit_context import set_audit_actor
except ImportError:
    from backend.services.audit_context import set_audit_actor


# ── request models ────────────────────────────────────────────────────────

class OfferingIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = "general"
    short_label: str = ""
    short_description: str = ""
    description: str = ""
    price: Optional[str] = None
    detail_url: str = ""
    media_url: str = ""
    media_type: str = "image"
    sort_order: int = 0
    is_active: bool = True
    # Values for the tenant's own columns, keyed by column key.
    values: Dict[str, Any] = Field(default_factory=dict)
    # Legacy vertical detail; folded into `values` so the bot still reads it.
    attrs: Dict[str, Any] = Field(default_factory=dict)


class OfferingPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    short_label: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    detail_url: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    values: Optional[Dict[str, Any]] = None
    attrs: Optional[Dict[str, Any]] = None


class ColumnIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    label: str = ""
    type: str = "text"
    required: bool = False
    options: List[str] = Field(default_factory=list)
    help: str = ""


class ColumnPatch(BaseModel):
    label: Optional[str] = None
    type: Optional[str] = None
    required: Optional[bool] = None
    options: Optional[List[str]] = None
    help: Optional[str] = None
    sort_order: Optional[int] = None


# ── auth ──────────────────────────────────────────────────────────────────

def _require_record_access(perm: str):
    """Admin with `perm`, or a token scoped to this tenant.

    The admin check runs after the tenant-access check on purpose: a tenant token
    is not an admin credential, so decoding it as one would answer 401 to a
    perfectly valid request.
    """
    def dependency(
        request: Request,
        tenant_id: str,
        principal: dict = Depends(require_tenant_access()),
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        if principal.get("type") == "tenant":
            set_audit_actor(principal)
            return principal
        admin = get_current_admin(request, credentials)
        set_audit_actor(admin)
        if not has_permission(admin, perm):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action",
            )
        return principal
    return dependency


read_access = _require_record_access("view_products")


def _require_write_access(action: str):
    """Write access, honouring the vertical-specific catalogue permissions.

    ``edit_delete_products`` remains the all-in-one legacy grant. Tenants whose
    vertical splits the work (products for a shop) can instead grant
    add/edit/delete separately; an IT/software tenant's catalogue is its
    services, so ``manage_services`` covers all three actions there.
    """
    def dependency(
        request: Request,
        tenant_id: str,
        principal: dict = Depends(require_tenant_access()),
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        if principal.get("type") == "tenant":
            set_audit_actor(principal)
            return principal
        admin = get_current_admin(request, credentials)
        set_audit_actor(admin)
        if has_permission(admin, "edit_delete_products"):
            return principal
        vertical = _vertical(tenant_id)
        if vertical == "it_software":
            if has_permission(admin, "manage_services"):
                return principal
        elif action == "create" and has_permission(admin, "add_product"):
            return principal
        elif action == "update" and has_permission(admin, "edit_product"):
            return principal
        elif action == "delete" and has_permission(admin, "delete_product"):
            return principal
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action",
        )
    return dependency
schema_access = _require_record_access("manage_operations")


# ── helpers ───────────────────────────────────────────────────────────────

def _vertical(tenant_id: str) -> str:
    from shared.tenancy.store import get_tenant
    row = get_tenant(tenant_id) or {}
    return str(row.get("vertical") or "")


def _columns(tenant_id: str) -> List[Dict[str, Any]]:
    """The tenant's columns, seeded and reconciled with the physical table."""
    with get_db_context() as conn:
        return record_schema.sync_columns(conn, tenant_id, _vertical(tenant_id))


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "offering"


def _unique_slug(name: str, exclude_id: int = None) -> str:
    """`slug` is UNIQUE across the table, not per tenant, so the loop is global."""
    base = _slugify(name)
    candidate = base
    counter = 1
    while True:
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM products WHERE slug = ?", (candidate,)
            ).fetchone()
        if row and row["id"] != exclude_id:
            counter += 1
            candidate = f"{base}-{counter}"
            continue
        return candidate


def _public(item: dict, columns: Optional[List[Dict[str, Any]]] = None) -> dict:
    values = record_schema.present(columns, item) if columns else {}
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "slug": item.get("slug"),
        "category": item.get("category"),
        "short_label": item.get("short_label"),
        "short_description": item.get("short_description"),
        "description": item.get("description"),
        "price": item.get("price"),
        "detail_url": item.get("detail_url"),
        "media_url": item.get("media_url"),
        "media_type": item.get("media_type"),
        "attrs": item.get("attrs_json") or {},
        "values": values,
        "sort_order": item.get("sort_order") or 0,
        "is_active": bool(item.get("is_active", 1)),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def _prepare_values(
    columns: List[Dict[str, Any]], values: Dict[str, Any], attrs: Dict[str, Any]
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Coerce submitted cells, and mirror them into attrs for the bot.

    The bot reads records through `attrs_json`, which every retrieval path
    already understands. Writing the same values there as well as in the typed
    column means a new column is searchable the moment it is added, with no
    change to the retrieval stack.
    """
    merged = {**(attrs or {}), **(values or {})}
    clean, errors = record_schema.coerce_record(columns, merged)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Some cells need attention.", "cells": errors},
        )
    attrs_json = {
        k: v for k, v in clean.items()
        if v is not None and str(v) != ""
    }
    return clean, attrs_json


#: Presentation columns (price, link, image) that the forms also send as
#: top-level record fields. Seed them into the cells so a column the admin
#: marked required validates, whatever path the value arrived by.
_SHARED_TOP_FIELDS = ("price", "detail_url", "media_url")


def _cell_values(values: Optional[Dict[str, Any]], body) -> Dict[str, Any]:
    merged = dict(values or {})
    for field in _SHARED_TOP_FIELDS:
        value = getattr(body, field, None)
        if value is not None and field not in merged:
            merged[field] = value
    return merged


def _write_cells(tenant_id: str, offering_id: int, columns: List[Dict[str, Any]], clean: Dict[str, Any]):
    """Push coerced values into the physical columns the admin created."""
    dynamic = {c["key"] for c in columns if not c["is_system"]}
    updates = {k: v for k, v in clean.items() if k in dynamic}
    if not updates:
        return
    with get_db_context() as conn:
        # A registered column can drift from the physical table (schema seeded
        # before the column existed). The value still reaches the bot through
        # the attrs_json mirror, so skip the dead column rather than 500.
        physical = set(record_schema.existing_columns(conn))
        updates = {k: v for k, v in updates.items() if k in physical}
        if not updates:
            return
        assignments = ", ".join(f'"{k}" = ?' for k in updates)
        conn.execute(
            f"UPDATE products SET {assignments} WHERE id = ? AND tenant_id = ?",
            list(updates.values()) + [offering_id, tenant_id],
        )


# ── column schema ─────────────────────────────────────────────────────────
# Declared before the offerings routes so the literal path segments win.

@router.get("/record-schema")
def get_record_schema(tenant_id: str, principal: dict = Depends(read_access)):
    return {"tenant_id": tenant_id, "vertical": _vertical(tenant_id), "columns": _columns(tenant_id)}


@router.post("/record-schema/columns")
def create_record_column(tenant_id: str, body: ColumnIn, principal: dict = Depends(schema_access)):
    try:
        with get_db_context() as conn:
            record_schema.seed_columns(conn, tenant_id, _vertical(tenant_id))
            column = record_schema.create_column(
                conn,
                tenant_id,
                key=body.key,
                label=body.label,
                col_type=body.type,
                required=body.required,
                options=body.options,
                help=body.help,
            )
    except record_schema.ColumnError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="record_schema_column_created", actor=principal, resource_type="record_schema_column", resource_id=f"{tenant_id}/{body.key}", tenant_id=tenant_id, details={"column_key": body.key, "column_label": body.label[:100], "column_type": body.type})
    return {"status": "created", "column": column, "columns": _columns(tenant_id)}


@router.put("/record-schema/columns/{key}")
def patch_record_column(tenant_id: str, key: str, body: ColumnPatch, principal: dict = Depends(schema_access)):
    try:
        with get_db_context() as conn:
            record_schema.seed_columns(conn, tenant_id, _vertical(tenant_id))
            column = record_schema.update_column(
                conn,
                tenant_id,
                key,
                label=body.label,
                col_type=body.type,
                required=body.required,
                options=body.options,
                help=body.help,
                sort_order=body.sort_order,
            )
    except record_schema.ColumnError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="record_schema_column_updated", actor=principal, resource_type="record_schema_column", resource_id=f"{tenant_id}/{key}", tenant_id=tenant_id, details={"column_key": key, "changed_fields": [name for name, value in body.model_dump(exclude_unset=True).items() if value is not None]})
    return {"status": "updated", "column": column, "columns": _columns(tenant_id)}


@router.delete("/record-schema/columns/{key}")
def delete_record_column(tenant_id: str, key: str, principal: dict = Depends(schema_access)):
    try:
        with get_db_context() as conn:
            record_schema.seed_columns(conn, tenant_id, _vertical(tenant_id))
            dropped = record_schema.remove_column(conn, tenant_id, key)
    except record_schema.ColumnError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="record_schema_column_deleted", actor=principal, resource_type="record_schema_column", resource_id=f"{tenant_id}/{key}", tenant_id=tenant_id, details={"column_key": key, "database_column_dropped": dropped})
    return {
        "status": "deleted",
        "key": key,
        "database_column_dropped": dropped,
        "columns": _columns(tenant_id),
    }


@router.post("/record-schema/reset")
def reset_record_schema(tenant_id: str, principal: dict = Depends(schema_access)):
    """Drop this tenant's own columns and re-seed from its vertical defaults."""
    with get_db_context() as conn:
        columns = record_schema.reset_columns(conn, tenant_id, _vertical(tenant_id))
        record_admin_audit_event(conn, action="record_schema_reset", actor=principal, resource_type="record_schema", resource_id=tenant_id, tenant_id=tenant_id, details={"vertical": _vertical(tenant_id), "column_count": len(columns)})
    return {"status": "reset", "vertical": _vertical(tenant_id), "columns": columns}


# ── records ───────────────────────────────────────────────────────────────

@router.get("/offerings")
def list_offerings(
    tenant_id: str,
    category: Optional[str] = None,
    include_inactive: bool = False,
    limit: int = 200,
    principal: dict = Depends(read_access),
):
    items = list_products(
        category=category,
        active_only=not include_inactive,
        limit=max(1, min(limit, 500)),
        tenant_id=tenant_id,
    )
    columns = _columns(tenant_id)
    return {"count": len(items), "columns": columns, "offerings": [_public(i, columns) for i in items]}


@router.get("/offerings/categories")
def list_offering_categories(tenant_id: str, principal: dict = Depends(read_access)):
    with get_db_context() as conn:
        rows = conn.execute(
            """SELECT DISTINCT category FROM products
               WHERE tenant_id = ? AND is_active = 1 AND category IS NOT NULL
               ORDER BY category""",
            (tenant_id,),
        ).fetchall()
    return {"categories": [r[0] for r in rows if r[0]]}


@router.post("/offerings")
def create_offering(tenant_id: str, body: OfferingIn, principal: dict = Depends(_require_write_access("create"))):
    columns = _columns(tenant_id)
    clean, attrs_json = _prepare_values(columns, _cell_values(body.values, body), body.attrs)

    offering_id = save_product(
        name=body.name.strip(),
        slug=_unique_slug(body.name),
        category=(body.category or "general").strip(),
        description=body.description,
        short_description=body.short_description,
        price=(body.price or "").strip() or None,
        media_url=body.media_url or None,
        media_type=body.media_type or "image",
        sort_order=body.sort_order,
        attrs_json=attrs_json,
        short_label=body.short_label or None,
        detail_url=body.detail_url or None,
        tenant_id=tenant_id,
        actor=principal,
    )
    if not body.is_active:
        update_product(offering_id, is_active=0, tenant_id=tenant_id)
    _write_cells(tenant_id, offering_id, columns, clean)
    item = get_product(offering_id, tenant_id=tenant_id)
    return {"status": "created", "offering": _public(item, columns)}


@router.put("/offerings/{offering_id}")
def patch_offering(tenant_id: str, offering_id: int, body: OfferingPatch, principal: dict = Depends(_require_write_access("update"))):
    if not get_product(offering_id, tenant_id=tenant_id):
        raise HTTPException(status_code=404, detail="Record not found for this tenant")

    columns = _columns(tenant_id)
    updates: Dict[str, Any] = body.model_dump(
        exclude_unset=True, exclude_none=True, exclude={"values", "attrs"}
    )
    if "name" in updates and updates["name"]:
        updates["name"] = updates["name"].strip()
        updates["slug"] = _unique_slug(updates["name"], exclude_id=offering_id)
    if "is_active" in updates:
        updates["is_active"] = 1 if updates["is_active"] else 0
    if "price" in updates and not str(updates["price"]).strip():
        updates["price"] = None
    if "media_url" in updates and not str(updates["media_url"]).strip():
        updates["media_url"] = None

    if body.values is not None or body.attrs is not None:
        clean, attrs_json = _prepare_values(columns, _cell_values(body.values, body), body.attrs or {})
        updates["attrs_json"] = attrs_json
    else:
        clean = {}

    if updates:
        update_product(offering_id, tenant_id=tenant_id, actor=principal, **updates)
    _write_cells(tenant_id, offering_id, columns, clean)
    return {
        "status": "updated",
        "offering": _public(get_product(offering_id, tenant_id=tenant_id), columns),
    }


@router.delete("/offerings/{offering_id}")
def remove_offering(
    tenant_id: str,
    offering_id: int,
    hard: bool = False,
    principal: dict = Depends(_require_write_access("delete")),
):
    if not get_product(offering_id, tenant_id=tenant_id):
        raise HTTPException(status_code=404, detail="Record not found for this tenant")
    delete_product(offering_id, hard=hard, tenant_id=tenant_id, actor=principal)
    return {"status": "deleted" if hard else "deactivated", "id": offering_id}
