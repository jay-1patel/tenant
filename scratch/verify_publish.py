import sqlite3, json
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
for r in c.execute("SELECT version, is_current, published_by, created_at FROM tenant_profile_versions WHERE tenant_id='l' ORDER BY version DESC LIMIT 4"):
    print(dict(r))
