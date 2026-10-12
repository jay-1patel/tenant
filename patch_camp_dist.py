import os

# --- PATCH CAMPAIGNS.PY ---
filepath = "backend/routes/campaigns.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

if "record_admin_audit_event" not in content:
    content = content.replace(
        "from backend.database import get_db_context",
        "from backend.database import get_db_context, record_admin_audit_event"
    )

# 1. create_campaign
create_str = """        campaign_id = cursor.lastrowid
        
        return {"status": "success", "campaign_id": campaign_id, "message": "Campaign created successfully"}"""
create_repl = """        campaign_id = cursor.lastrowid
        try:
            record_admin_audit_event(
                conn,
                action="campaign_created",
                actor=current_admin,
                resource_type="campaign",
                resource_id=campaign_id,
                tenant_id=tenant_id,
                details={"created_campaign": {"name": campaign.name, "type": campaign.type}}
            )
        except Exception:
            pass
        return {"status": "success", "campaign_id": campaign_id, "message": "Campaign created successfully"}"""
content = content.replace(create_str, create_repl)

# 2. update_campaign
update_str = """        cursor = conn.execute(
            f"UPDATE campaigns SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND tenant_id = ?",
            values
        )
        
        if cursor.rowcount == 0:"""
update_repl = """        before = conn.execute("SELECT * FROM campaigns WHERE id = ? AND tenant_id = ?", (campaign_id, tenant_id)).fetchone()
        cursor = conn.execute(
            f"UPDATE campaigns SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND tenant_id = ?",
            values
        )
        
        if cursor.rowcount == 0:"""
update_str2 = """        return {"status": "success", "message": "Campaign updated successfully"}"""
update_repl2 = """        after = conn.execute("SELECT * FROM campaigns WHERE id = ? AND tenant_id = ?", (campaign_id, tenant_id)).fetchone()
        try:
            record_admin_audit_event(
                conn,
                action="campaign_updated",
                actor=current_admin,
                resource_type="campaign",
                resource_id=campaign_id,
                tenant_id=tenant_id,
                details={"before_state": dict(before) if before else None, "after_state": dict(after) if after else None}
            )
        except Exception:
            pass
        return {"status": "success", "message": "Campaign updated successfully"}"""
content = content.replace(update_str, update_repl)
content = content.replace(update_str2, update_repl2)

# 3. delete_campaign
delete_str = """        cursor = conn.execute("DELETE FROM campaigns WHERE id = ? AND tenant_id = ?", (campaign_id, tenant_id))
        
        if cursor.rowcount == 0:"""
delete_repl = """        before = conn.execute("SELECT * FROM campaigns WHERE id = ? AND tenant_id = ?", (campaign_id, tenant_id)).fetchone()
        cursor = conn.execute("DELETE FROM campaigns WHERE id = ? AND tenant_id = ?", (campaign_id, tenant_id))
        
        if cursor.rowcount == 0:"""
delete_str2 = """        return {"status": "success", "message": "Campaign deleted successfully"}"""
delete_repl2 = """        try:
            record_admin_audit_event(
                conn,
                action="campaign_deleted",
                actor=current_admin,
                resource_type="campaign",
                resource_id=campaign_id,
                tenant_id=tenant_id,
                details={"deleted_campaign": dict(before) if before else None}
            )
        except Exception:
            pass
        return {"status": "success", "message": "Campaign deleted successfully"}"""
content = content.replace(delete_str, delete_repl)
content = content.replace(delete_str2, delete_repl2)

# 4. duplicate_campaign
dup_str = """        new_id = cursor.lastrowid
        
        return {"status": "success", "campaign_id": new_id, "message": "Campaign duplicated successfully"}"""
dup_repl = """        new_id = cursor.lastrowid
        try:
            record_admin_audit_event(
                conn,
                action="campaign_duplicated",
                actor=current_admin,
                resource_type="campaign",
                resource_id=new_id,
                tenant_id=tenant_id,
                details={"source_campaign_id": campaign_id, "new_campaign_id": new_id}
            )
        except Exception:
            pass
        return {"status": "success", "campaign_id": new_id, "message": "Campaign duplicated successfully"}"""
content = content.replace(dup_str, dup_repl)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)


# --- PATCH DISTRIBUTORS.PY ---
filepath = "backend/routes/distributors.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

if "record_admin_audit_event" not in content:
    content = content.replace(
        "from backend.database import get_db_context",
        "from backend.database import get_db_context, record_admin_audit_event"
    )

dist_create_str = """        return {"status": "success", "message": "Distributor created successfully"}"""
dist_create_repl = """        try:
            record_admin_audit_event(
                conn,
                action="distributor_created",
                actor=current_admin,
                resource_type="distributor",
                resource_id=wa_id,
                tenant_id=tenant_id,
                details={"distributor_wa_id": wa_id, "name": distributor.name}
            )
        except Exception:
            pass
        return {"status": "success", "message": "Distributor created successfully"}"""
content = content.replace(dist_create_str, dist_create_repl)

dist_update_str = """        result = conn.execute(
            f"UPDATE distributors SET {', '.join(fields)} WHERE wa_id = ? AND tenant_id = ?",
            values,
        )
        if result.rowcount == 0:"""
dist_update_repl = """        before = conn.execute("SELECT * FROM distributors WHERE wa_id = ? AND tenant_id = ?", (wa_id, tenant_id)).fetchone()
        result = conn.execute(
            f"UPDATE distributors SET {', '.join(fields)} WHERE wa_id = ? AND tenant_id = ?",
            values,
        )
        if result.rowcount == 0:"""
dist_update_str2 = """        return {"status": "success", "message": "Distributor updated successfully"}"""
dist_update_repl2 = """        after = conn.execute("SELECT * FROM distributors WHERE wa_id = ? AND tenant_id = ?", (wa_id, tenant_id)).fetchone()
        try:
            record_admin_audit_event(
                conn,
                action="distributor_updated",
                actor=current_admin,
                resource_type="distributor",
                resource_id=wa_id,
                tenant_id=tenant_id,
                details={"before_state": dict(before) if before else None, "after_state": dict(after) if after else None}
            )
        except Exception:
            pass
        return {"status": "success", "message": "Distributor updated successfully"}"""
content = content.replace(dist_update_str, dist_update_repl)
content = content.replace(dist_update_str2, dist_update_repl2)

dist_delete_str = """        result = conn.execute(
            "DELETE FROM distributors WHERE wa_id = ? AND tenant_id = ?",
            (wa_id, tenant_id),
        )
        if result.rowcount == 0:"""
dist_delete_repl = """        before = conn.execute("SELECT * FROM distributors WHERE wa_id = ? AND tenant_id = ?", (wa_id, tenant_id)).fetchone()
        result = conn.execute(
            "DELETE FROM distributors WHERE wa_id = ? AND tenant_id = ?",
            (wa_id, tenant_id),
        )
        if result.rowcount == 0:"""
dist_delete_str2 = """        return {"status": "success", "message": "Distributor deleted successfully"}"""
dist_delete_repl2 = """        try:
            record_admin_audit_event(
                conn,
                action="distributor_deleted",
                actor=current_admin,
                resource_type="distributor",
                resource_id=wa_id,
                tenant_id=tenant_id,
                details={"deleted_distributor": dict(before) if before else None}
            )
        except Exception:
            pass
        return {"status": "success", "message": "Distributor deleted successfully"}"""
content = content.replace(dist_delete_str, dist_delete_repl)
content = content.replace(dist_delete_str2, dist_delete_repl2)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched campaigns.py and distributors.py")
