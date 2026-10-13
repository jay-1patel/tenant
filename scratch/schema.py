import sqlite3

conn = sqlite3.connect(r"C:\keya\leeway_tenant_5\FAQ.DB")
for name in ("customers", "user_sessions", "chat_history"):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
    print(f"{name}: {cols}")
