"""FastAPI route for Audit Logs with dedicated table and filtering."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db
from routes.auth import get_current_admin

router = APIRouter(tags=["audit-logs"])


@router.get("/api/audit-logs")
def list_audit_logs(
    search: Optional[str] = Query(default=None, max_length=200),
    actor: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None, max_length=80),
    category: Optional[str] = Query(default=None, max_length=50),
    days: Optional[int] = Query(default=7, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=10000),
    current_admin: dict = Depends(get_current_admin),
):
    """Get audit logs with deep filtering capabilities."""
    # Check admin access
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    
    # Validate days parameter
    if days is not None and (days < 1 or days > 365):
        raise HTTPException(status_code=422, detail="Days must be between 1 and 365")
    
    # Calculate date range
    from datetime import timedelta
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    # Build SQL query with parameterized inputs
    conn = get_db()
    try:
        where_clauses = []
        params = []
        
        # Date range filter
        where_clauses.append("created_at >= ? AND created_at <= ?")
        params.extend([start_date.isoformat(), end_date.isoformat()])
        
        # Search filter (searches description and metadata)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            where_clauses.append("(description LIKE ? OR metadata LIKE ?)")
            params.extend([search_term, search_term])
        
        # Actor filter
        if actor and actor.strip():
            where_clauses.append("actor = ?")
            params.append(actor.strip())
        
        # Action filter
        if action and action.strip():
            where_clauses.append("action = ?")
            params.append(action.strip())
        
        # Category filter
        if category and category.strip():
            where_clauses.append("category = ?")
            params.append(category.strip())
        
        # Build final query
        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        query = f"""
            SELECT id, created_at as timestamp, actor, action, category, status, description, metadata
            FROM audit_logs 
            WHERE {where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        
        # Get total count
        count_query = f"""
            SELECT COUNT(*) FROM audit_logs 
            WHERE {where_clause}
        """
        total_count = conn.execute(count_query, params[:-2]).fetchone()[0]
        
        # Format results
        events = []
        for row in rows:
            event = dict(row)
            # Convert metadata from JSON string if present
            if event.get("metadata"):
                try:
                    import json
                    event["metadata"] = json.loads(event["metadata"])
                except (json.JSONDecodeError, TypeError):
                    event["metadata"] = {}
            events.append(event)
        
        return {
            "events": events,
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        conn.close()


@router.get("/api/audit-logs/statistics")
def get_audit_logs_statistics(
    days: Optional[int] = Query(default=7, ge=1, le=365),
    current_admin: dict = Depends(get_current_admin),
):
    """Get statistics for audit logs dashboard."""
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    
    from datetime import timedelta
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    conn = get_db()
    try:
        # Total events
        total_query = """
            SELECT COUNT(*) FROM audit_logs 
            WHERE created_at >= ? AND created_at <= ?
        """
        total = conn.execute(total_query, [start_date.isoformat(), end_date.isoformat()]).fetchone()[0]
        
        # By status
        status_query = """
            SELECT status, COUNT(*) as count 
            FROM audit_logs 
            WHERE created_at >= ? AND created_at <= ?
            GROUP BY status
        """
        status_rows = conn.execute(status_query, [start_date.isoformat(), end_date.isoformat()]).fetchall()
        by_status = {row[0]: row[1] for row in status_rows}
        
        # By category
        category_query = """
            SELECT category, COUNT(*) as count 
            FROM audit_logs 
            WHERE created_at >= ? AND created_at <= ?
            GROUP BY category
        """
        category_rows = conn.execute(category_query, [start_date.isoformat(), end_date.isoformat()]).fetchall()
        by_category = {row[0]: row[1] for row in category_rows}
        
        # By action
        action_query = """
            SELECT action, COUNT(*) as count 
            FROM audit_logs 
            WHERE created_at >= ? AND created_at <= ?
            GROUP BY action
        """
        action_rows = conn.execute(action_query, [start_date.isoformat(), end_date.isoformat()]).fetchall()
        by_action = {row[0]: row[1] for row in action_rows}
        
        # By actor
        actor_query = """
            SELECT actor, COUNT(*) as count 
            FROM audit_logs 
            WHERE created_at >= ? AND created_at <= ?
            GROUP BY actor
        """
        actor_rows = conn.execute(actor_query, [start_date.isoformat(), end_date.isoformat()]).fetchall()
        by_actor = {row[0]: row[1] for row in actor_rows}
        
        # By date (daily)
        date_query = """
            SELECT date(created_at) as date, COUNT(*) as count 
            FROM audit_logs 
            WHERE created_at >= ? AND created_at <= ?
            GROUP BY date(created_at)
            ORDER BY date(created_at)
        """
        date_rows = conn.execute(date_query, [start_date.isoformat(), end_date.isoformat()]).fetchall()
        by_date = {row[0]: row[1] for row in date_rows}
        
        return {
            "total_events": total,
            "by_status": by_status,
            "by_category": by_category,
            "by_action": by_action,
            "by_actor": by_actor,
            "by_date": by_date,
            "date_range": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        conn.close()


@router.get("/api/audit-logs/export")
def export_audit_logs(
    format: str = Query(default="csv", max_length=4),
    search: Optional[str] = Query(default=None, max_length=200),
    actor: Optional[str] = Query(default=None, max_length=100),
    action: Optional[str] = Query(default=None, max_length=80),
    category: Optional[str] = Query(default=None, max_length=50),
    days: Optional[int] = Query(default=7, ge=1, le=365),
    current_admin: dict = Depends(get_current_admin),
):
    """Export audit logs as CSV or JSON."""
    if current_admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    
    if format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="Format must be csv or json")
    
    # Get the data
    import json as json_module
    from fastapi.responses import Response
    
    logs_response = list_audit_logs(
        search=search, actor=actor, action=action, category=category, days=days, 
        limit=10000, offset=0, current_admin=current_admin
    )
    
    events = logs_response["events"]
    
    if format == "csv":
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = ["ID", "Timestamp", "Actor", "Action", "Category", "Status", "Description"]
        writer.writerow(headers)
        
        # Write data
        for event in events:
            row = [
                event.get("id", ""),
                event.get("timestamp", ""),
                event.get("actor", ""),
                event.get("action", ""),
                event.get("category", ""),
                event.get("status", ""),
                event.get("description", "")
            ]
            writer.writerow(row)
        
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=audit-logs.csv",
                "Content-Type": "text/csv"
            }
        )
    else:  # JSON
        return Response(
            content=json_module.dumps(events, indent=2, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=audit-logs.json",
                "Content-Type": "application/json"
            }
        )


