import sqlite3

conn = sqlite3.connect('faq.db')
c = conn.cursor()
c.execute("PRAGMA table_info(admin_files)")
print("Columns:", [col[1] for col in c.fetchall()])
c.execute("SELECT * FROM admin_files WHERE tenant_id='dlf'")
rows = c.fetchall()
print(f"Found {len(rows)} files for dlf:")
for r in rows:
    print(r)
conn.close()

