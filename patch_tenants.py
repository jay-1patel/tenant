import re
import os

filepath = "backend/routes/tenant_admin.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add import if missing
if "record_admin_audit_event" not in content:
    content = content.replace(
        "from backend.database import get_db_context",
        "from backend.database import get_db_context, record_admin_audit_event, get_db"
    )

# 1. register_tenant
register_str = """        logger.info(f"Registered new tenant: {tenant_data.company_name} (ID: {tenant_id})")"""
register_repl = """        with get_db_context() as conn:
            try:
                record_admin_audit_event(
                    conn,
                    action="tenant_created",
                    actor=super_admin,
                    resource_type="tenant",
                    resource_id=tenant_id,
                    tenant_id=str(tenant_id),
                    details={"created_tenant": tenant_data.dict()}
                )
            except Exception as e:
                logger.error(f"Audit log failed: {e}")
                
        logger.info(f"Registered new tenant: {tenant_data.company_name} (ID: {tenant_id})")"""
content = content.replace(register_str, register_repl)

# 2. update_tenant_details
update_str = """        if success:
            # Return updated tenant info
            updated_tenant = get_tenant_by_id(tenant_id)"""
update_repl = """        if success:
            # Return updated tenant info
            updated_tenant = get_tenant_by_id(tenant_id)
            with get_db_context() as conn:
                try:
                    record_admin_audit_event(
                        conn,
                        action="tenant_updated",
                        actor=tenant_admin.get('admin'),
                        resource_type="tenant",
                        resource_id=tenant_id,
                        tenant_id=str(tenant_id),
                        details={"before_state": tenant, "after_state": updated_tenant}
                    )
                except Exception as e:
                    logger.error(f"Audit log failed: {e}")"""
content = content.replace(update_str, update_repl)

# 3. delete_tenant_endpoint
delete_str = """        success = delete_tenant(tenant_id)
        
        if success:"""
delete_repl = """        tenant_to_delete = get_tenant_by_id(tenant_id)
        success = delete_tenant(tenant_id)
        
        if success:
            with get_db_context() as conn:
                try:
                    record_admin_audit_event(
                        conn,
                        action="tenant_deleted",
                        actor=super_admin,
                        resource_type="tenant",
                        resource_id=tenant_id,
                        tenant_id=str(tenant_id),
                        details={"deleted_tenant": tenant_to_delete}
                    )
                except Exception as e:
                    logger.error(f"Audit log failed: {e}")"""
content = content.replace(delete_str, delete_repl)

# 4. deactivate_tenant_endpoint
deactivate_str = """        success = deactivate_tenant(tenant_id)
        
        if success:"""
deactivate_repl = """        success = deactivate_tenant(tenant_id)
        
        if success:
            with get_db_context() as conn:
                try:
                    record_admin_audit_event(
                        conn,
                        action="tenant_deactivated",
                        actor=tenant_admin,
                        resource_type="tenant",
                        resource_id=tenant_id,
                        tenant_id=str(tenant_id),
                        details={"before_state": tenant}
                    )
                except Exception as e:
                    logger.error(f"Audit log failed: {e}")"""
content = content.replace(deactivate_str, deactivate_repl)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched tenant_admin.py")
