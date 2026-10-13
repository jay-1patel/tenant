import sqlite3

conn = sqlite3.connect(r"C:\keya\leeway_tenant_5\FAQ.DB")
for table in ("user_sessions", "user_states", "webhook_logs"):
    before = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    deleted = conn.execute(f"DELETE FROM [{table}]").rowcount
    after = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    conn.commit()
    print(f"{table:14} had {before:5} -> deleted {deleted:5} -> now {after}")
