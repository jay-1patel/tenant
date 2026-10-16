import sqlite3

conn = sqlite3.connect("faq.db")
c = conn.cursor()
c.execute("SELECT id, source_file, content_type, content, tenant_id FROM faq_dataset LIMIT 3")
for r in c.fetchall():
    print(r)
conn.close()
