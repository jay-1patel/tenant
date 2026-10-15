import sqlite3

conn = sqlite3.connect('faq.db')
c = conn.cursor()
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables in faq.db:', [t[0] for t in tables])
for t in tables:
    name = t[0]
    count = c.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    print(f"  {name}: {count}")

print("\nTenants table content:")
try:
    for row in c.execute("SELECT * FROM tenants").fetchall():
        print(" ", row)
except Exception as e:
    print("  error querying tenants:", e)

conn.close()
