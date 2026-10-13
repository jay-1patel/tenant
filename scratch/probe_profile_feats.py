import sys, os
sys.path.insert(0, os.getcwd())
from shared.tenancy.loader import get_tenant_profile
p = get_tenant_profile("l")
feats = p.features.model_dump() if hasattr(p.features, "model_dump") else p.features
print("features:", feats)
print("campaigns:", feats.get("campaigns"), "| distributors:", feats.get("distributors"))
