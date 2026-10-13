import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("draft_config schema:", [r[1] for r in c.execute("PRAGMA table_info(draft_config)")])
for r in c.execute("SELECT * FROM draft_config"):
    d = dict(r)
    scope = d.get("scope")
    print("scope=", scope, "updated_at=", d.get("updated_at"))
    for k, v in d.items():
        if isinstance(v, str) and v.strip().startswith("{"):
            try: p = json.loads(v)
            except Exception: continue
            feats = p.get("features")
            print("   json col", k, "keys=", list(p.keys()))
            if feats: print("   campaigns=", feats.get("campaigns"), "distributors=", feats.get("distributors"))
