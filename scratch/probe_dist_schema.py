import sqlite3
c = sqlite3.connect("faq.db")
print("distributors schema:")
for r in c.execute("PRAGMA table_info(distributors)"):
    print("  ", r)
print("tables containing 'distribut' or 'contact':")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    n=r[0]
    if "distribut" in n.lower() or "contact" in n.lower():
        cols=[x[1] for x in c.execute(f"PRAGMA table_info({n})")]
        print("  ", n, "->", cols)
print("distributors rowcount:", c.execute("SELECT COUNT(*) FROM distributors").fetchone()[0])
