import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
try:
    rows = list(c.execute("SELECT scope, updated_by, updated_at, payload FROM draft_config"))
except Exception as e:
    print("no draft_config:", e); raise SystemExit
print("draft scopes:", [(r["scope"], r["updated_at"]) for r in rows])
for r in rows:
    if "tenant_profile" in (r["scope"] or ""):
        try: p = json.loads(r["payload"] or "{}")
        except Exception: p = {}
        feats = p.get("features")
        print("scope=", r["scope"], "keys=", list(p.keys()), "features.campaigns=", (feats or {}).get("campaigns"), "distributors=", (feats or {}).get("distributors"))
