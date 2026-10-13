import sys, os
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(os.path.join("routing", ".env"))
except Exception as e:
    print("dotenv:", e)
print("DEFAULT_TENANT_ID env:", repr(os.getenv("DEFAULT_TENANT_ID")))
from shared.tenancy.defaults import DEFAULT_TENANT_ID
print("DEFAULT_TENANT_ID const:", repr(DEFAULT_TENANT_ID))
from shared.tenancy import store
print("get_tenant('leewaysoftech'):", store.get_tenant("leewaysoftech"))
try:
    print("list_tenants active:", [t.get("id") for t in store.list_tenants(status="active")])
except Exception as e:
    print("list_tenants ERR:", e)
from shared.tenancy.resolver import resolve_default_tenant
print("resolve_default_tenant:", repr(resolve_default_tenant()))
from database import _resolve_tenant
print("_resolve_tenant():", repr(_resolve_tenant()))
