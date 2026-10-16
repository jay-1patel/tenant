import sqlite3

conn = sqlite3.connect("faq.db")
c = conn.cursor()
row = c.execute("SELECT id, company_name, slug, vertical FROM tenants WHERE slug='ltfinance'").fetchone()
print("ltfinance tenant row:", row)
conn.close()
