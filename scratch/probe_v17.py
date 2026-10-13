import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
for v in (17, 16):
    r = c.execute("SELECT payload FROM tenant_profile_versions WHERE tenant_id='l' AND version=?", (v,)).fetchone()
    p = json.loads(r["payload"] or "{}")
    f = p.get("features") or {}
    print(f"v{v}: campaigns={f.get('campaigns')} distributors={f.get('distributors')} human_handover={f.get('human_handover')} complaints={f.get('complaints')}")
