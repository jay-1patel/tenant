import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from shared.tenancy.loader import get_tenant_profile
p = get_tenant_profile("l")
print("brand:", json.dumps(p.brand.to_payload() if hasattr(p.brand, "to_payload") else p.brand.__dict__, indent=2, ensure_ascii=False))
try:
    print("notifications:", json.dumps(p.notifications.to_payload() if hasattr(p.notifications, "to_payload") else p.notifications.__dict__, indent=2, ensure_ascii=False))
except Exception as e:
    print("notifications err", e)
print("vocabulary:", getattr(p, "vocabulary", None))

# intents of interest
for name in ("benefits", "careers", "projects", "support_request", "contact_human", "service_enquiry"):
    i = p.intent(name)
    if i:
        print(f"\nintent {name}: enabled={i.enabled} flow={getattr(i,'flow',None)} req={getattr(i,'requires_feature',None)}")
        print("  answer:", (i.answer or "")[:200])
        print("  keywords:", getattr(i, "keywords", None))
