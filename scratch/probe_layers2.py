import sys, os, json
sys.path.insert(0, os.getcwd())
from shared.tenancy import loader
d = loader.describe_layers("l")
layers = d.get("layers", {})
for name, layer in layers.items():
    feats = (layer or {}).get("features") if isinstance(layer, dict) else None
    print(name, "->", feats)
print("merged features:", d.get("resolved", {}).get("features") if "resolved" in d else "n/a")
