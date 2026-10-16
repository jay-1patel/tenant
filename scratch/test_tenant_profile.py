import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from shared.tenancy.loader import get_tenant_profile
from shared.tenancy import store

profile = get_tenant_profile("99destinations")
print("Profile loaded successfully:")
print("Tenant ID:", profile.tenant_id)
print("Display Name:", profile.display_name)
print("Brand:", profile.brand.name)
print("Helpline:", profile.brand.support_phone)
print("Email:", profile.brand.support_email)
print("Buttons:", [b.id for b in profile.menu.visible_buttons(profile.features)])
print("Intents:", profile.active_intent_names())
