import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("tenants schema:", [r[1] for r in c.execute("PRAGMA table_info(tenants)")])
for r in c.execute("SELECT * FROM tenants"):
    print(dict(r))
