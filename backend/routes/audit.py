"""Superadmin-only query API for durable admin activity history with export and statistics."""

import json
import csv
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from database import get_db, safe_audit_details
from routes.auth import get_current_admin

router = APIRouter(tags=["audit-history"])


@router.get("/api/admin/audit-history")
def list_audit_history(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    actor: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None, max_length=80),
    category: Optional[str] = Query(default=None, max_length=30),
    tenant_id: Optional[str] = Query(default=None, max_length=100),
    outcome: Optional[str] = Query(default=None, max_length=20),
    search: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    sort_by: Optional[str] = Query(default=None, max_length=50),
    sort_order: Optional[str] = Query(default="desc", max_length=4),
    current_admin: dict = Depends(get_current_admin),
):
    """List audit history events with filtering and sorting."""
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access is required")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    if outcome and outcome not in {"success", "failure"}:
        raise HTTPException(status_code=422, detail="outcome must be success or failure")

    # Valid sort columns and directions
    valid_sort_columns = {
        "created_at", "action", "actor_username", "target_username",
        "outcome", "tenant_id", "tenant_name", "tenant_slug", "ip_address", "resource_type", "id"
    }
    valid_sort_directions = {"asc", "desc"}
    
    if sort_by and sort_by not in valid_sort_columns:
        raise HTTPException(status_code=422, detail=f"Invalid sort column: {sort_by}")
    if sort_order and sort_order not in valid_sort_directions:
        raise HTTPException(status_code=422, detail="sort_order must be asc or desc")

    where = ["datetime(created_at) >= datetime('now', '-365 days')"]
    params = []
    
    if start_date:
        where.append("date(created_at) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        where.append("date(created_at) <= ?")
        params.append(end_date.isoformat())
    
    for column, value in (("actor_username", actor), ("action", action), ("tenant_id", tenant_id), ("outcome", outcome)):
        if value:
            where.append(f"{column} = ?")
            params.append(value.strip())
    
    if category:
        category_actions = {
            "authentication": ("login", "first_admin_created", "admin_password_reset", "admin_password_reset_via_otp", "password_changed"),
            "accounts": (
                "first_admin_created", "admin_created", "admin_updated", "admin_deleted",
                "admin_password_reset", "admin_password_reset_via_otp", "password_changed",
            ),
            "tenant_setup": (
                "tenant_created", "tenant_deleted", "tenant_profile_draft_saved",
                "tenant_intent_draft_saved", "tenant_profile_published", "tenant_profile_rolled_back",
                "tenant_phone_id_bound", "tenant_webhook_secret_configured", "tenant_token_created",
                "tenant_token_revoked", "config_draft_saved", "config_draft_built", "config_published",
            ),
            "api_access": ("api_access_request_submitted", "api_access_request_reviewed"),
            "menus": ("menu_settings_updated", "menu_item_updated", "menu_item_created", "menu_item_deleted", "menu_reordered", "menu_reset"),
            "schema": ("record_schema_column_created", "record_schema_column_updated", "record_schema_column_deleted", "record_schema_reset"),
            "products": ("product_created", "product_updated", "product_deleted", "product_deleted_hard"),
            "files": ("file_uploaded", "file_deleted"),
            "complaints": ("complaint_created", "complaint_updated", "complaint_deleted", "complaint_resolved", "complaint_replied"),
            "catalog": ("product_created", "product_updated", "product_deleted", "product_deleted_hard", "file_uploaded", "file_deleted"),
            "orders": ("order_updated", "order_deleted", "order_created"),
            "campaigns": ("campaign_created", "campaign_updated", "campaign_deleted"),
        }
        if category not in category_actions:
            raise HTTPException(status_code=422, detail="Unknown audit category")
        actions = category_actions[category]
        where.append(f"action IN ({', '.join('?' for _ in actions)})")
        params.extend(actions)
    
    if search and search.strip():
        term = f"%{search.strip()}%"
        where.append(
            "(actor_username LIKE ? OR actor_label LIKE ? OR target_username LIKE ? OR "
            "resource_type LIKE ? OR resource_id LIKE ? OR action LIKE ? OR tenant_id LIKE ? OR "
            "tenant_name LIKE ? OR tenant_slug LIKE ? OR ip_address LIKE ? OR user_agent LIKE ? OR details_json LIKE ?)"
        )
        params.extend([term] * 12)
    
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    
    # Sorting
    sort_column = sort_by or "created_at"
    sort_direction = sort_order or "desc"
    order_by = f"ORDER BY {sort_column} {sort_direction}"

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM admin_audit_events{clause}", params).fetchone()[0]
        
        # Get column mapping for sorting
        column_map = {
            "created_at": "created_at",
            "action": "action", 
            "actor_username": "actor_username",
            "target_username": "target_username",
            "outcome": "outcome",
            "tenant_id": "tenant_id",
            "tenant_name": "tenant_name",
            "tenant_slug": "tenant_slug",
            "ip_address": "ip_address",
            "resource_type": "resource_type",
            "id": "id"
        }
        
        actual_sort_column = column_map.get(sort_column, "created_at")
        
        rows = conn.execute(
            f"""SELECT id, created_at, actor_id, actor_username, actor_role,
                       action, outcome, resource_type, resource_id, target_username,
                       tenant_id, tenant_name, tenant_slug, actor_kind, actor_label,
                       details_json, ip_address, user_agent
                FROM admin_audit_events{clause}
                ORDER BY {actual_sort_column} {sort_direction}, id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()

    events = []
    for row in rows:
        event = dict(row)
        try:
            event["details"] = safe_audit_details(json.loads(event.pop("details_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            event["details"] = {}
        event["tenant_label"] = " · ".join(
            part for part in (event.get("tenant_name"), event.get("tenant_slug"), event.get("tenant_id")) if part
        ) or "Platform"
        events.append(event)
    
    return {"events": events, "total": total, "limit": limit, "offset": offset}


@router.get("/api/admin/audit-statistics")
def get_audit_statistics(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    actor: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None, max_length=80),
    category: Optional[str] = Query(default=None, max_length=30),
    tenant_id: Optional[str] = Query(default=None, max_length=100),
    outcome: Optional[str] = Query(default=None, max_length=20),
    search: Optional[str] = Query(default=None, max_length=120),
    current_admin: dict = Depends(get_current_admin),
):
    """Get aggregated statistics for audit events."""
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access is required")

    where = ["datetime(created_at) >= datetime('now', '-365 days')"]
    params = []
    
    if start_date:
        where.append("date(created_at) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        where.append("date(created_at) <= ?")
        params.append(end_date.isoformat())
    for column, value in (("actor_username", actor), ("action", action), ("tenant_id", tenant_id), ("outcome", outcome)):
        if value:
            where.append(f"{column} = ?")
            params.append(value.strip())
    if category:
        category_actions = {
            "authentication": ("login", "first_admin_created", "admin_password_reset", "admin_password_reset_via_otp", "password_changed"),
            "accounts": (
                "first_admin_created", "admin_created", "admin_updated", "admin_deleted",
                "admin_password_reset", "admin_password_reset_via_otp", "password_changed",
            ),
            "tenant_setup": (
                "tenant_created", "tenant_deleted", "tenant_profile_draft_saved",
                "tenant_intent_draft_saved", "tenant_profile_published", "tenant_profile_rolled_back",
                "tenant_phone_id_bound", "tenant_webhook_secret_configured", "tenant_token_created",
                "tenant_token_revoked", "config_draft_saved", "config_draft_built", "config_published",
            ),
            "api_access": ("api_access_request_submitted", "api_access_request_reviewed"),
            "menus": ("menu_settings_updated", "menu_item_updated", "menu_item_created", "menu_item_deleted", "menu_reordered", "menu_reset"),
            "schema": ("record_schema_column_created", "record_schema_column_updated", "record_schema_column_deleted", "record_schema_reset"),
            "products": ("product_created", "product_updated", "product_deleted", "product_deleted_hard"),
            "files": ("file_uploaded", "file_deleted"),
            "complaints": ("complaint_created", "complaint_updated", "complaint_deleted", "complaint_resolved", "complaint_replied"),
            "catalog": ("product_created", "product_updated", "product_deleted", "product_deleted_hard", "file_uploaded", "file_deleted"),
            "orders": ("order_updated", "order_deleted", "order_created"),
            "campaigns": ("campaign_created", "campaign_updated", "campaign_deleted"),
        }
        if category in category_actions:
            actions = category_actions[category]
            where.append(f"action IN ({', '.join('?' for _ in actions)})")
            params.extend(actions)
    if search and search.strip():
        term = f"%{search.strip()}%"
        where.append(
            "(actor_username LIKE ? OR actor_label LIKE ? OR target_username LIKE ? OR "
            "resource_type LIKE ? OR resource_id LIKE ? OR action LIKE ? OR tenant_id LIKE ? OR "
            "tenant_name LIKE ? OR tenant_slug LIKE ? OR ip_address LIKE ? OR user_agent LIKE ? OR details_json LIKE ?)"
        )
        params.extend([term] * 12)
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    conn = get_db()
    try:
        # Total events
        total = conn.execute(f"SELECT COUNT(*) FROM admin_audit_events{clause}", params).fetchone()[0]
        
        # By outcome
        outcome_stats = conn.execute(
            f"""SELECT outcome, COUNT(*) as count 
                FROM admin_audit_events{clause} 
                GROUP BY outcome""", 
            params
        ).fetchall()
        
        by_outcome = {"success": 0, "failure": 0}
        for row in outcome_stats:
            if row[0] in by_outcome:
                by_outcome[row[0]] = row[1]
        
        # By action
        action_stats = conn.execute(
            f"""SELECT action, COUNT(*) as count 
                FROM admin_audit_events{clause} 
                GROUP BY action""", 
            params
        ).fetchall()
        
        by_action = {row[0]: row[1] for row in action_stats}
        
        # By date (daily)
        date_stats = conn.execute(
            f"""SELECT date(created_at) as audit_date, COUNT(*) as count 
                FROM admin_audit_events{clause} 
                GROUP BY date(created_at) 
                ORDER BY audit_date""", 
            params
        ).fetchall()
        
        by_date = {row[0]: row[1] for row in date_stats}
        
        # By category
        category_map = {
            "login": "authentication",
            "first_admin_created": "accounts",
            "admin_created": "accounts",
            "admin_updated": "accounts", 
            "admin_deleted": "accounts",
            "admin_password_reset": "accounts",
            "admin_password_reset_via_otp": "accounts",
            "password_changed": "accounts",
            "tenant_created": "tenant_setup",
            "tenant_deleted": "tenant_setup",
            "tenant_profile_draft_saved": "tenant_setup",
            "tenant_intent_draft_saved": "tenant_setup",
            "tenant_profile_published": "tenant_setup",
            "tenant_profile_rolled_back": "tenant_setup",
            "tenant_phone_id_bound": "tenant_setup",
            "tenant_webhook_secret_configured": "tenant_setup",
            "tenant_token_created": "tenant_setup",
            "tenant_token_revoked": "tenant_setup",
            "config_draft_saved": "tenant_setup",
            "config_draft_built": "tenant_setup",
            "config_published": "tenant_setup",
            "api_access_request_submitted": "api_access",
            "api_access_request_reviewed": "api_access",
            "product_created": "products",
            "product_updated": "products",
            "product_deleted": "products",
            "product_deleted_hard": "products",
            "file_uploaded": "files",
            "file_deleted": "files",
            "complaint_created": "complaints",
            "complaint_updated": "complaints",
            "complaint_deleted": "complaints",
            "complaint_resolved": "complaints",
            "complaint_replied": "complaints",
            "order_updated": "orders",
            "order_deleted": "orders",
            "order_created": "orders",
            "campaign_created": "campaigns",
            "campaign_updated": "campaigns",
            "campaign_deleted": "campaigns"
        }
        
        category_stats = conn.execute(
            f"""SELECT action, COUNT(*) as count 
                FROM admin_audit_events{clause} 
                GROUP BY action""", 
            params
        ).fetchall()
        
        by_category: dict = {"authentication": 0, "accounts": 0, "tenant_setup": 0, "api_access": 0}
        for action, count in category_stats:
            cat = category_map.get(action, "other")
            by_category[cat] = by_category.get(cat, 0) + count
        
        # By actor
        actor_stats = conn.execute(
            f"""SELECT actor_username, COUNT(*) as count 
                FROM admin_audit_events{clause} 
                GROUP BY actor_username""", 
            params
        ).fetchall()
        
        by_actor = {row[0]: row[1] for row in actor_stats}
        
    finally:
        conn.close()
    
    return {
        "total_events": total,
        "by_outcome": by_outcome,
        "by_action": by_action,
        "by_date": by_date,
        "by_category": by_category,
        "by_actor": by_actor
    }


@router.get("/api/admin/audit-export")
def export_audit_history(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    actor: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None, max_length=80),
    category: Optional[str] = Query(default=None, max_length=30),
    tenant_id: Optional[str] = Query(default=None, max_length=100),
    outcome: Optional[str] = Query(default=None, max_length=20),
    search: Optional[str] = Query(default=None, max_length=120),
    format: str = Query(default="csv", max_length=4),
    columns: str = Query(default="", max_length=500),
    limit: int = Query(default=10000, ge=1, le=50000),
    current_admin: dict = Depends(get_current_admin),
):
    """Export audit history as CSV or JSON."""
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access is required")
    
    if format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="Format must be csv or json")
    
    where = ["datetime(created_at) >= datetime('now', '-365 days')"]
    params = []
    
    if start_date:
        where.append("date(created_at) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        where.append("date(created_at) <= ?")
        params.append(end_date.isoformat())
    for column, value in (("actor_username", actor), ("action", action), ("tenant_id", tenant_id), ("outcome", outcome)):
        if value:
            where.append(f"{column} = ?")
            params.append(value.strip())
    if category:
        category_actions = {
            "authentication": ("login", "first_admin_created", "admin_password_reset", "admin_password_reset_via_otp", "password_changed"),
            "accounts": (
                "first_admin_created", "admin_created", "admin_updated", "admin_deleted",
                "admin_password_reset", "admin_password_reset_via_otp", "password_changed",
            ),
            "tenant_setup": (
                "tenant_created", "tenant_deleted", "tenant_profile_draft_saved",
                "tenant_intent_draft_saved", "tenant_profile_published", "tenant_profile_rolled_back",
                "tenant_phone_id_bound", "tenant_webhook_secret_configured", "tenant_token_created",
                "tenant_token_revoked", "config_draft_saved", "config_draft_built", "config_published",
            ),
            "api_access": ("api_access_request_submitted", "api_access_request_reviewed"),
            "menus": ("menu_settings_updated", "menu_item_updated", "menu_item_created", "menu_item_deleted", "menu_reordered", "menu_reset"),
            "schema": ("record_schema_column_created", "record_schema_column_updated", "record_schema_column_deleted", "record_schema_reset"),
            "products": ("product_created", "product_updated", "product_deleted", "product_deleted_hard"),
            "files": ("file_uploaded", "file_deleted"),
            "complaints": ("complaint_created", "complaint_updated", "complaint_deleted", "complaint_resolved", "complaint_replied"),
            "catalog": ("product_created", "product_updated", "product_deleted", "product_deleted_hard", "file_uploaded", "file_deleted"),
            "orders": ("order_updated", "order_deleted", "order_created"),
            "campaigns": ("campaign_created", "campaign_updated", "campaign_deleted"),
        }
        if category in category_actions:
            actions = category_actions[category]
            where.append(f"action IN ({', '.join('?' for _ in actions)})")
            params.extend(actions)
    if search and search.strip():
        term = f"%{search.strip()}%"
        where.append(
            "(actor_username LIKE ? OR actor_label LIKE ? OR target_username LIKE ? OR "
            "resource_type LIKE ? OR resource_id LIKE ? OR action LIKE ? OR tenant_id LIKE ? OR "
            "tenant_name LIKE ? OR tenant_slug LIKE ? OR ip_address LIKE ? OR user_agent LIKE ? OR details_json LIKE ?)"
        )
        params.extend([term] * 12)
    
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    
    conn = get_db()
    try:
        rows = conn.execute(
            f"""SELECT id, created_at, actor_id, actor_username, actor_role, action, outcome,
                       resource_type, resource_id, target_username, tenant_id, tenant_name,
                       tenant_slug, actor_kind, actor_label, details_json, ip_address, user_agent
                FROM admin_audit_events{clause}
                ORDER BY created_at DESC, id DESC LIMIT ?""",
            [*params, limit],
        ).fetchall()
    finally:
        conn.close()

    events = []
    for row in rows:
        event = dict(row)
        try:
            event["details"] = safe_audit_details(json.loads(event.pop("details_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            event["details"] = {}
        event["tenant_label"] = " · ".join(
            part for part in (event.get("tenant_name"), event.get("tenant_slug"), event.get("tenant_id")) if part
        ) or "Platform"
        events.append(event)
    
    # Parse requested columns
    requested_columns = columns.split(",") if columns else [
        "id", "created_at", "action", "actor_id", "actor_username", "actor_role", "actor_kind", "actor_label", "target_username",
        "outcome", "tenant_id", "tenant_name", "tenant_slug", "tenant_label", "resource_type", "resource_id",
        "ip_address", "user_agent", "details"
    ]
    
    if format == "csv":
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = []
        column_mappings = {
            "id": "ID",
            "created_at": "Date/Time",
            "action": "Action",
            "actor_id": "Actor ID",
            "actor_username": "Actor",
            "actor_role": "Actor Role",
            "actor_kind": "Actor Kind",
            "actor_label": "Actor Label",
            "target_username": "Target User",
            "outcome": "Outcome",
            "tenant_id": "Tenant ID",
            "tenant_name": "Tenant Name",
            "tenant_slug": "Tenant Slug",
            "tenant_label": "Tenant",
            "resource_type": "Resource Type",
            "resource_id": "Resource ID",
            "ip_address": "IP Address",
            "user_agent": "User Agent",
            "details": "Details"
        }
        
        for col in requested_columns:
            headers.append(column_mappings.get(col, col.replace("_", " ").title()))
        
        writer.writerow(headers)
        
        # Write rows
        for event in events:
            row_data = []
            for col in requested_columns:
                value = event.get(col)
                if value is None:
                    row_data.append("")
                elif isinstance(value, dict):
                    row_data.append(json.dumps(value))
                else:
                    row_data.append(str(value))
            writer.writerow(row_data)
        
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=audit-history.csv",
                "Content-Type": "text/csv"
            }
        )
    else:
        # Generate JSON
        export_events = []
        for event in events:
            export_event = {}
            for col in requested_columns:
                value = event.get(col)
                if isinstance(value, dict):
                    export_event[col] = value
                else:
                    export_event[col] = value
            export_events.append(export_event)
        
        return Response(
            content=json.dumps(export_events, indent=2, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=audit-history.json",
                "Content-Type": "application/json"
            }
        )


@router.get("/api/admin/audit-history/{event_id}")
def get_audit_event(
    event_id: int,
    current_admin: dict = Depends(get_current_admin),
):
    """Get details for a specific audit event."""
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access is required")
    
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT id, created_at, actor_id, actor_username, actor_role, action, outcome,
                       resource_type, resource_id, target_username, tenant_id, tenant_name,
                       tenant_slug, actor_kind, actor_label, details_json, ip_address, user_agent
                FROM admin_audit_events WHERE id = ?""",
            [event_id],
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        
        event = dict(row)
        try:
            event["details"] = safe_audit_details(json.loads(event.pop("details_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            event["details"] = {}
        event["tenant_label"] = " · ".join(
            part for part in (event.get("tenant_name"), event.get("tenant_slug"), event.get("tenant_id")) if part
        ) or "Platform"
        return event
    finally:
        conn.close()