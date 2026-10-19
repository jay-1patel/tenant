"""
Seed and ensure all 7 clients from clients/ into faq.db tenants table and create scoped admin accounts.
"""
import os
import sys
import json
import sqlite3
import bcrypt

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))

from shared.tenancy.store import ensure_tenant, list_tenants

def main():
    db_path = "faq.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    clients_dir = "clients"
    seeded = []

    for client_id in sorted(os.listdir(clients_dir)):
        cfg_path = os.path.join(clients_dir, client_id, "config.json")
        if not os.path.exists(cfg_path):
            continue
        with open(cfg_path) as f:
            cfg = json.load(f)

        name = (
            cfg.get("display_name")
            or cfg.get("name")
            or (cfg.get("brand") or {}).get("name")
            or client_id.replace("_", " ").title()
        )
        vertical = cfg.get("vertical") or "generic"
        
        # Ensure tenant in DB
        ensure_tenant(
            client_id,
            slug=client_id,
            vertical=vertical,
            display_name=name,
            status="active"
        )
        seeded.append((client_id, name, vertical))

    # Also ensure default
    ensure_tenant("default", slug="default", vertical="generic", display_name="Default Tenant", status="active")

    # Now create or update tenant-scoped admins
    # Password for all scoped admins: TenantPass123!
    password_hash = bcrypt.hashpw(b"TenantPass123!", bcrypt.gensalt(12)).decode("utf-8")
    
    tenant_admins = [
        ("admin_99dest", "99destinations"),
        ("admin_leeway", "leewaysoftech"),
        ("admin_ltf", "ltfinance"),
        ("admin_meridian", "meridianbank"),
        ("admin_northwind", "northwindcapital"),
        ("admin_troogood", "troogood"),
        ("admin_wanderly", "wanderly"),
    ]

    for username, tid in tenant_admins:
        cursor.execute("SELECT id FROM admins WHERE tenant_id = ? AND role = 'admin'", (tid,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE admins SET username = ?, password_hash = ? WHERE id = ?",
                (username, password_hash, row["id"])
            )
        else:
            cursor.execute(
                """INSERT INTO admins (username, password_hash, role, permissions, tenant_id)
                   VALUES (?, ?, 'admin', '{}', ?)""",
                (username, password_hash, tid)
            )

    # For default, update tenant_admin password to TenantPass123!
    cursor.execute(
        "UPDATE admins SET password_hash = ? WHERE username = 'tenant_admin'",
        (password_hash,)
    )

    conn.commit()
    conn.close()

    print(f"Successfully seeded {len(seeded)} tenants and {len(tenant_admins)} scoped admin users:")
    for cid, name, vert in seeded:
        print(f"  - Tenant: {cid:18} | Vertical: {vert:12} | Name: {name}")

if __name__ == "__main__":
    main()
