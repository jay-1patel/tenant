import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from shared.tenancy import store
from shared.tenancy.loader import validate_merged_profile, build_profile
from shared.tenancy import cache

TID = "l"
payload = store.get_current_payload(TID)
if not payload:
    raise SystemExit("no current payload for tenant l")

btns = payload.setdefault("menu", {}).setdefault("buttons", [])
changed = []
for b in btns:
    if b.get("id") == "menu_benefits" and b.get("intent") != "benefits":
        b["intent"] = "benefits"
        changed.append(("menu_benefits", "benefits"))
    if b.get("id") == "menu_customer_support" and b.get("intent") != "support_request":
        b["intent"] = "support_request"
        changed.append(("menu_customer_support", "support_request"))

print("changed:", changed)
if not changed:
    print("nothing to change")
    raise SystemExit(0)

# Validate the merged profile before persisting (same gate publish uses).
validate_merged_profile(TID, payload)
print("validation OK")

store.save_draft(TID, payload, updated_by="system:fix-benefits-support")
ver = store.publish_version(TID, payload, published_by="system:fix-benefits-support")
print("published version:", ver)

# purge caches so a re-read is fresh
store.invalidate(TID)
try:
    cache.purge(TID)
except Exception as e:
    print("cache purge warn:", e)

prof = build_profile(TID)
for b in prof.menu.buttons:
    if b.id in ("menu_benefits", "menu_customer_support"):
        print(f"  {b.id}: title={b.title!r} intent={b.intent!r}")
