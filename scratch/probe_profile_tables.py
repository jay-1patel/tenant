import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("profile/version tables:")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    n = r["name"]
    if "profile" in n.lower() or "version" in n.lower():
        cols=[x[1] for x in c.execute(f"PRAGMA table_info({n})")]
        print("  ", n, "->", cols, "rows=", c.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0])
