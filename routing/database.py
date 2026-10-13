import os
import importlib.util

_backend_db = os.path.join(os.path.dirname(__file__), "..", "backend", "database.py")
_spec = importlib.util.spec_from_file_location("backend_database", _backend_db)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export every name from backend.database, including single-underscore
# helpers (e.g. `_resolve_tenant`, `_current_tenant`) that backend modules
# import directly via `from database import ...`. Only dunder names are skipped.
for _name in dir(_mod):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_mod, _name)
