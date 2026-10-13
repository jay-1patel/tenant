import sys, os, json
sys.path.insert(0, os.getcwd())
from shared.tenancy import loader
d = loader.describe_layers("l")
print(json.dumps(d, indent=2, default=str)[:4000])
