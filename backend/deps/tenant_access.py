"""
Tenant-access dependency helpers used by the offerings router.

These two functions — _require_read_access and _require_write_access — are
FastAPI dependency *factories*. They return a coroutine that FastAPI calls
on every request to verify the caller has access to the addressed tenant.

How FastAPI Depends() works with factories:
  - _require_read_access        → called with no args, returns an async function
  - _require_write_access("edit") → called with an action string, returns an async function
  - FastAPI injects the returned async function into Depends()
  - The async function receives (request, tenant_id) automatically from the path
  - It returns a "principal" dict that the route handler can use for audit logging

For the test environment this just checks that the tenant exists.
Production can extend this to validate JWT tokens and role-based permissions.
"""

from fastapi import Depends, HTTPException, Request
from typing import Callable, Coroutine, Any


def _load_store():
    """Import the tenancy store lazily to avoid circular imports at startup."""
    try:
        from shared.tenancy import store
        return store
    except Exception:
        return None


def _build_dep(action: str):
    """Return an async dependency function that checks tenant existence."""
    async def dep(request: Request, tenant_id: str) -> dict:
        store = _load_store()
        if not store:
            raise HTTPException(status_code=403, detail="Tenant store unavailable")
        tenant_rec = store.get_tenant(tenant_id)
        if not tenant_rec:
            raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
        # Return a principal dict — routes use this for audit logging only.
        return {
            "id": tenant_rec.get("id", tenant_id),
            "tenant_id": tenant_id,
            "action": action,
        }
    return dep


def _require_read_access():
    """
    Dependency for GET routes — verifies the tenant exists.
    Usage:  principal: dict = Depends(_require_read_access)
    """
    return _build_dep("read")


def _require_write_access(action: str = "write"):
    """
    Dependency factory for POST/PUT/DELETE routes.
    Usage:  principal: dict = Depends(_require_write_access("create"))
            principal: dict = Depends(_require_write_access("edit"))
    """
    return _build_dep(action)
