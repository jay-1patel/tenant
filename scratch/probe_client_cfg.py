import json
p = json.load(open("clients/leewaysoftech/config.json", encoding="utf-8"))
print("top keys:", list(p.keys()))
inner = p.get("profile") if "profile" in p else p
feats = inner.get("features")
print("features:", json.dumps(feats, indent=2) if feats else feats)
print("display_name:", inner.get("display_name"))
