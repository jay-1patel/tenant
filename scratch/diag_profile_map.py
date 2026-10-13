import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from shared.tenancy.loader import get_tenant_profile
tid = "l"
prof = get_tenant_profile(tid)
print("profile:", prof.tenant_id, prof.vertical)
print("\n-- buttons (id | title | intent | flow) --")
for b in prof.menu.buttons:
    print(f"  {b.id!r:22} | {b.title!r:22} | intent={getattr(b,'intent',None)!r} | flow={getattr(b,'flow',None)!r}")

print("\n-- active intents (name | has_answer | answer_head) --")
for i in prof.active_intents():
    a = (i.answer or "").strip().replace("\n", " ")[:60]
    print(f"  {i.name!r:24} | answer={bool(a)} | {a}")

print("\n-- ALL intents --")
for i in prof.intents:
    a = (i.answer or "").strip().replace("\n", " ")[:50]
    print(f"  {i.name!r:24} enabled={getattr(i,'enabled',None)} answer={bool(a)} | {a}")
