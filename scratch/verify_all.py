import sys, os, sqlite3, json

# 1) Simulate the running server's import order: routing/ first, so `import database`
#    resolves to routing/database.py (the shim). The shim must expose private
#    helpers the backend modules import directly.
sys.path.insert(0, os.path.join(os.getcwd(), "routing"))
import database  # noqa: E402
print("1) database module ->", database.__file__)
print("   has _resolve_tenant:", hasattr(database, "_resolve_tenant"))
print("   has touch_customer :", hasattr(database, "touch_customer"))
print("   has get_db_context :", hasattr(database, "get_db_context"))
print("   has _current_tenant:", hasattr(database, "_current_tenant"))

# 2) The failing customers query for tenant 'l' (was 500: no such column customer_name)
conn = sqlite3.connect("faq.db"); conn.row_factory = sqlite3.Row
rows = conn.execute(
    """SELECT wa_id FROM (
           SELECT wa_id FROM orders WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION SELECT wa_id FROM complaints WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION SELECT wa_id FROM chat_history WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION SELECT wa_id FROM user_states WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION SELECT wa_id FROM customers WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
       )""",
    ("l", "l", "l", "l", "l"),
).fetchall()
wa_ids = [r["wa_id"] for r in rows]
print("2) customers query OK, wa_ids:", wa_ids)
for wa_id in wa_ids:
    nm = conn.execute(
        "SELECT customer_name FROM orders WHERE tenant_id=? AND wa_id=? AND customer_name IS NOT NULL AND customer_name != '' ORDER BY id DESC LIMIT 1",
        ("l", wa_id),
    ).fetchone()
print("   orders.customer_name selection OK")

# 3) Campaign sync recipients: union of customers + distributors for tenant 'l'
cust = [r["wa_id"] for r in conn.execute(
    "SELECT wa_id FROM customers WHERE tenant_id='l' AND wa_id IS NOT NULL AND wa_id != ''")]
dist = [r["wa_id"] for r in conn.execute(
    "SELECT wa_id FROM distributors WHERE tenant_id='l' AND wa_id IS NOT NULL AND wa_id != ''")]
print("3) recipient sources -> customers:", cust, "| distributors:", dist)
