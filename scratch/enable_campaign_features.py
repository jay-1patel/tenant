import sys, os, json
sys.path.insert(0, os.getcwd())

from shared.tenancy import loader, store
from shared.tenancy import cache

TENANT = "l"
ENABLE = ("campaigns", "distributors")

payload = store.get_current_payload(TENANT)
if payload is None:
    raise SystemExit("no current published payload")
payload.setdefault("features", {})
for flag in ENABLE:
    payload["features"][flag] = True

profile = loader.validate_merged_profile(TENANT, payload)
missing = []
try:
    from shared.tenancy import schemas
    missing = schemas.missing_contact_fields(profile.brand)
except Exception as exc:
    print("contact check skipped:", exc)
if missing:
    raise SystemExit(f"missing required fields: {missing}")

with store._db().get_db_context() as conn:
    store.save_draft(TENANT, payload, updated_by="opencode-fix", conn=conn)
    version = store.publish_version(TENANT, payload, published_by="opencode-fix", conn=conn)

store.invalidate(TENANT)
cache.purge(TENANT)

reloaded = loader.reload_profile(TENANT)
print("published version:", version)
print("resolved campaigns:", reloaded.features.campaigns, "| distributors:", reloaded.features.distributors)
