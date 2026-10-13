import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "faq.db"
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row

tables = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("TABLES:", tables)

for t in ("customers", "orders", "complaints", "chat_history", "user_states"):
    if t not in tables:
        print(f"\n== {t}: MISSING ==")
        continue
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    cnt = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"\n== {t}: rows={cnt} ==")
    print("   cols:", cols)

if "customers" in tables:
    print("\ncustomers sample:")
    for r in c.execute("SELECT * FROM customers LIMIT 5"):
        print("  ", dict(r))
