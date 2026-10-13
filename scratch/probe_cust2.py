import sqlite3
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("customers count:", c.execute("SELECT COUNT(*) FROM customers").fetchone()[0])
for r in c.execute("SELECT id, tenant_id, wa_id, name, message_count, first_seen FROM customers"):
    print("  ", dict(r))
