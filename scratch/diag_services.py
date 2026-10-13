import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.services import service_answers
from backend.services.intent_answers import answer_for_menu_title, answer_for_text as ia_text
from shared.tenancy.loader import get_tenant_profile
from shared.tenancy.resolver import resolve_tenant_for_user

wa = "919512777899"
tid = resolve_tenant_for_user(wa)
print("resolved tenant:", tid)

prof = get_tenant_profile(tid)
print("profile tenant_id:", prof.tenant_id, "vertical:", prof.vertical)
print("feature offerings:", prof.feature_on("offerings"))
try:
    i = prof.intent("service_enquiry")
    print("service_enquiry intent:", i, "enabled:", getattr(i, "enabled", None), "answer:", repr(getattr(i, "answer", None)))
except Exception as e:
    print("intent err", e)

print("--- service_answers.answer_for_text('our services') ---")
print(service_answers.answer_for_text(wa, "our services"))

print("--- intent_answers.answer_for_menu_title('🛠️ Our Services') ---")
print(repr(answer_for_menu_title(wa, "🛠️ Our Services")))

print("--- intent_answers.answer_for_text('our services') ---")
print(repr(ia_text(wa, "our services")))

print("--- list_products ---")
try:
    from database import list_products
    ps = list_products(active_only=True, limit=100, tenant_id=tid)
    print("count:", len(ps))
    for p in ps[:12]:
        print(" -", p.get("id"), repr(p.get("name")), "| short:", repr((p.get("short_description") or "")[:60]))
except Exception as e:
    import traceback; traceback.print_exc()
