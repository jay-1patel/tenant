import sqlite3
conn = sqlite3.connect('faq.db')
c = conn.cursor()
c.execute("PRAGMA table_info(tenants)")
print("Columns:", [col[1] for col in c.fetchall()])
rows = c.execute("SELECT * FROM tenants").fetchall()
for r in rows:
    print(r)
conn.close()
