import sqlite3
import sys

c = sqlite3.connect("faq.db")
c.row_factory = sqlite3.Row

print("=== tenants ===")
tcols = [r[1] for r in c.execute("PRAGMA table_info(tenants)")]
print("  cols:", tcols)
for r in c.execute("SELECT * FROM tenants"):
    print("  ", dict(r))

for t in ("chat_history", "user_states", "customers", "orders", "complaints", "products"):
    try:
        rows = c.execute(
            f"SELECT tenant_id, COUNT(*) AS n FROM {t} GROUP BY tenant_id"
        ).fetchall()
    except Exception as e:
        print(f"=== {t}: ERR {e}")
        continue
    print(f"=== {t} by tenant_id ===")
    for r in rows:
        print("  ", dict(r))

print("=== recent chat_history ===")
for r in c.execute(
    "SELECT id, wa_id, tenant_id, route, substr(message,1,20) m, created_at "
    "FROM chat_history ORDER BY id DESC LIMIT 8"
):
    print("  ", dict(r))

print("=== resolve_default_tenant ===")
sys.path.insert(0, "backend")
try:
    from shared.tenancy.resolver import resolve_default_tenant
    print("  ", repr(resolve_default_tenant()))
except Exception as e:
    print("  ERR", e)
