import sqlite3, os
DB = r"C:\keya\leeway_tenant_5\faq.db"
print("DB:", DB, "size:", os.path.getsize(DB))
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
for t in ("chat_history", "webhook_logs", "processed_inbound_messages", "products", "customer_profiles", "customers", "tenants"):
    try:
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n} rows")
    except Exception as e:
        print(f"{t}: ERR {e}")

print("\n-- chat_history last 10 --")
try:
    for r in c.execute("SELECT id, wa_id, substr(message,1,50) m, substr(response,1,50) resp, route, tenant_id, created_at FROM chat_history ORDER BY id DESC LIMIT 10"):
        print(dict(r))
except Exception as e:
    print("err", e)

print("\n-- webhook_logs last 10 --")
try:
    for r in c.execute("SELECT id, direction, endpoint, status_code, created_at FROM webhook_logs ORDER BY id DESC LIMIT 10"):
        print(dict(r))
except Exception as e:
    print("err", e)

print("\n-- processed_inbound_messages last 10 --")
try:
    for r in c.execute("SELECT * FROM processed_inbound_messages ORDER BY rowid DESC LIMIT 10"):
        print(dict(r))
except Exception as e:
    print("err", e)
