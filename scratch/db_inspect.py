import sqlite3

conn = sqlite3.connect(r"C:\keya\leeway_tenant_5\FAQ.DB")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("tables:", ", ".join(tables))
for t in tables:
    if "session" in t.lower() or "state" in t.lower():
        print(f"  {t} => {conn.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]}")
