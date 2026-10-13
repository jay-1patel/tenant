import sys, os, json, sqlite3
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
import database
DB = database.DB_PATH
print("DB:", DB)
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

def summarize(payload):
    try:
        p = json.loads(payload) if isinstance(payload, str) else payload
    except Exception:
        return "<unparseable>"
    if isinstance(p, dict) and "tenant_profile" in p:
        p = p["tenant_profile"]
    menu = (p or {}).get("menu") or {}
    btns = menu.get("buttons") or []
    return [(b.get("id"), b.get("intent"), b.get("flow"), b.get("requires_feature")) for b in btns]

print("\n=== tenant_profile_versions ===")
for r in c.execute("SELECT version, is_current, published_by, created_at, payload FROM tenant_profile_versions WHERE tenant_id='l' ORDER BY version"):
    print(f"\n-- v{r['version']} current={r['is_current']} by={r['published_by']} at={r['created_at']}")
    for b in summarize(r["payload"]):
        print("   ", b)

print("\n=== draft_config ===")
for r in c.execute("SELECT scope, substr(snapshot_json,1,1) ok, updated_at FROM draft_config WHERE scope LIKE 'tenant_profile:%'"):
    print(dict(r))
row = c.execute("SELECT snapshot_json FROM draft_config WHERE scope='tenant_profile:l'").fetchone()
if row:
    print("\nDRAFT tenant_profile:l buttons:")
    for b in summarize(row["snapshot_json"]):
        print("   ", b)
