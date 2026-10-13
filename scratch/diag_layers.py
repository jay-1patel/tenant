import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from shared.tenancy import store
from shared.tenancy.loader import describe_layers

tid = "l"
d = describe_layers(tid)
print("tenant record:", d["tenant"])
print("current_version:", d["current_version"])
print("versions:", d["versions"])

for layer in ("defaults", "file", "db"):
    data = d["layers"][layer] or {}
    print(f"\n===== {layer} layer =====")
    menu = (data.get("menu") or {})
    btns = menu.get("buttons") or []
    if btns:
        print(f"  menu.key={menu.get('key')!r} buttons:")
        for b in btns:
            print(f"    {b.get('id')!r:26} title={b.get('title')!r:22} intent={b.get('intent')!r} flow={b.get('flow')!r} req={b.get('requires_feature')!r}")
    intents = data.get("intents") or []
    if intents:
        print("  intents:")
        for i in intents:
            print(f"    {i.get('name')!r:24} answer={'Y' if (i.get('answer') or '').strip() else '-'} enabled={i.get('enabled')}")
