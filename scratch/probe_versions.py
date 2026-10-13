import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
rows = list(c.execute("SELECT version, is_current, created_at, payload FROM tenant_profile_versions WHERE tenant_id='l' ORDER BY version"))
print("versions for 'l':", [(r["version"], r["is_current"], r["created_at"]) for r in rows])
for r in rows:
    try:
        payload = json.loads(r["payload"] or "{}")
    except Exception as e:
        payload = {}
    feats = payload.get("features")
    print(f"  v{r['version']} current={r['is_current']} features.campaigns={None if not feats else feats.get('campaigns')} distributors={None if not feats else feats.get('distributors')} keys={list(payload.keys()) if payload else None}")
