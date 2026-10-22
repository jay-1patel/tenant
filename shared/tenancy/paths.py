"""Canonical filesystem locations for the tenancy substrate.

One definition, imported everywhere. ``kb/services/multi_tenant.py`` currently
derives its own ``clients/`` path from ``routing.config.BASE_DIR``; Phase 7
absorbs that module and points it here.
"""

import os
from pathlib import Path

# shared/tenancy/paths.py -> shared/tenancy -> shared -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
ROUTING_DIR = REPO_ROOT / "routing"
KB_DIR = REPO_ROOT / "kb"
EVAL_DIR = REPO_ROOT / "eval"


def _dir_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw and str(raw).strip():
        p = Path(str(raw).strip())
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()
    return default


# Per-tenant config packs: clients/<tenant_id>/config.json + clients/<id>/knowledge/
CLIENTS_DIR = _dir_from_env("CLIENTS_DIR", REPO_ROOT / "clients")


def client_dir(tenant_id: str) -> Path:
    tid = str(tenant_id or "").strip()
    primary = CLIENTS_DIR / tid
    if primary.exists() and (primary / "config.json").exists():
        # Special check: if primary is 'l' without knowledge, prefer leewaysoftech if present
        if tid == "l" and not (primary / "knowledge").exists() and (CLIENTS_DIR / "leewaysoftech").exists():
            return CLIENTS_DIR / "leewaysoftech"
        return primary

    # Direct fallback for leeway variants
    if tid.lower() in ("1", "default", "leeway-softech", "leewaysoftech", "leeway", "l"):
        if (CLIENTS_DIR / "leewaysoftech").exists():
            return CLIENTS_DIR / "leewaysoftech"

    # Fallback: check if tenant_id is an integer ID or slug and resolve via database
    try:
        from . import store
        rec = store.get_tenant(tid)
        if rec:
            slug = str(rec.get("slug") or "")
            for candidate in (slug, slug.replace("-", ""), slug.replace("_", "")):
                if candidate and (CLIENTS_DIR / candidate).exists():
                    return CLIENTS_DIR / candidate
    except Exception:
        pass

    return primary


def client_config_path(tenant_id: str) -> Path:
    return client_dir(tenant_id) / "config.json"


def client_knowledge_dir(tenant_id: str) -> Path:
    return client_dir(tenant_id) / "knowledge"


def ensure_client_dir(tenant_id: str) -> Path:
    d = client_dir(tenant_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "knowledge").mkdir(exist_ok=True)
    return d
