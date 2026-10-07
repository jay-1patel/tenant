import json
import logging
import secrets
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# SECURITY FIX: Token revocation list to invalidate compromised tokens
REVOKED_TOKENS = set()

from routing.config import ADMIN_SECRET_KEY, ADMIN_JWT_EXPIRY_HOURS, OTP_EXPIRY_MINUTES
from database import (
    get_db_context,
    get_admin_record,
    list_admin_records,
    count_admins_by_role,
    update_admin_record,
    update_admin_email,
    delete_admin,
    set_admin_otp,
    get_admin_otp,
    clear_admin_otp,
)

logger = logging.getLogger("chiki_webhook")

# SECURITY FIX: Rate limiting for auth endpoints
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    RATE_LIMIT_ENABLED = True
except ImportError:
    RATE_LIMIT_ENABLED = False
    logger.warning("slowapi not installed - rate limiting disabled. Install with: pip install slowapi")

# Configure limiter if available
limiter = Limiter(key_func=get_remote_address) if RATE_LIMIT_ENABLED else None

# SECURITY FIX: Password complexity requirements
MIN_PASSWORD_LENGTH = 12
MIN_PASSWORD_SCORE = 3  # 0-4 scale (zxcvbn)
from services.emailer import send_otp_email, is_smtp_configured

# Rate limit exception handler. Registered on the FastAPI app in main.py --
# APIRouter has no exception_handler method.
async def rate_limit_exceeded_handler(request: Request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many requests. Try again in {exc.detail} seconds."},
    )

router = APIRouter(prefix="/api/auth")
security = HTTPBearer(auto_error=False)

# SECURITY FIX: Use strong bcrypt hashing with explicit work factor
SALT_ROUNDS = 12  # Minimum 12 rounds for security (14-16 recommended for sensitive data)

ALL_PERMISSIONS = {
    "manage_admins": "Manage admins (add/edit/delete)",
    "upload_faq": "Upload FAQ files",
    "upload_kb": "Upload KB files",
    "view_files": "View uploaded files",
    "delete_files": "Delete uploaded files",
    "view_products": "View products",
    "edit_delete_products": "Edit/delete products",
    "add_product": "Add products/services to the catalogue",
    "edit_product": "Edit catalogue entries",
    "delete_product": "Remove catalogue entries",
    "manage_services": "Add/edit/delete services",
    "manage_projects": "Edit the projects page",
    "manage_technologies": "Edit the technologies page",
    "manage_careers": "Edit the careers page",
    "manage_benefits": "Edit the benefits page",
    "manage_operations": "Manage operations (products, menus, prices, schemes, campaigns)",
    "chat": "Use admin chat",
    "chat_history": "View chat history",
    "catalogue_new_arrival": "Manage brochure and new releases",
    "view_orders": "View orders",
    "manage_orders": "Edit/delete orders",
    "view_complaints": "View complaints",
    "manage_complaints": "Handle complaints (reply/resolve)",
    "view_customers": "View customers",
    "view_analytics": "View analytics",
    "view_inbox": "Live inbox",
    "view_campaigns": "Campaigns",
    "manage_campaigns": "Create/edit/delete campaigns",
    "view_distributors": "Distributors",
    "manage_distributors": "Add/edit/delete distributors",
}

SUPER_ADMIN_PERMISSIONS = {k: True for k in ALL_PERMISSIONS}


# ---------- permission helpers ----------

def _parse_permissions(raw, default_all: bool = False) -> dict:
    perms = {k: default_all for k in ALL_PERMISSIONS}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    if isinstance(raw, dict):
        for key in ALL_PERMISSIONS:
            if key in raw:
                perms[key] = bool(raw[key])
    return perms


def _effective_permissions(role: str, raw) -> dict:
    """Super admins always get everything; admins and sub admins get exactly
    what is stored. An admin is created with every permission on, and a super
    admin can then edit the switches down — the stored set is the truth."""
    if role == "super_admin":
        return dict(SUPER_ADMIN_PERMISSIONS)
    if role == "admin":
        # Rows that predate the permissions column (seeded with its '{}'
        # default) never chose a set — keep them fully enabled rather than
        # locking the tenant's admin out.
        empty = raw is None or raw == {} or (
            isinstance(raw, str) and raw.strip() in ("", "{}", "null")
        )
        if empty:
            return dict(SUPER_ADMIN_PERMISSIONS)
        return _parse_permissions(raw)
    return _parse_permissions(raw)


def has_permission(admin: dict, perm: str) -> bool:
    if not admin:
        return False
    if admin.get("role") == "super_admin":
        return True
    return bool(admin.get("permissions", {}).get(perm))


def require_permission(perm: str):
    def dependency(current_admin: dict = Depends(get_current_admin)):
        if not has_permission(current_admin, perm):
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
        return current_admin
    return dependency


# ---------- helpers ----------

def _hash_password(plain: str) -> str:
    # SECURITY FIX: Use explicit work factor for strong hashing
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=SALT_ROUNDS)).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(username: str) -> str:
    # SECURITY FIX: Add unique token ID (jti) for revocation
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=ADMIN_JWT_EXPIRY_HOURS),
        "jti": str(uuid.uuid4()),  # Unique token identifier for revocation
    }
    return jwt.encode(payload, ADMIN_SECRET_KEY, algorithm="HS256")


def _decode_token(token: str) -> dict:
    # SECURITY FIX: Check for revoked tokens and require specific claims
    try:
        payload = jwt.decode(
            token,
            ADMIN_SECRET_KEY,
            algorithms=["HS256"],  # Only allow HS256
            options={"require": ["exp", "sub", "jti"]},  # Require these claims
        )
        
        # Check if token has been revoked
        if payload.get("jti") in REVOKED_TOKENS:
            logger.warning(f"Revoked token used: jti={payload.get('jti')}")
            raise HTTPException(status_code=401, detail="Token has been revoked")
        
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.MissingRequiredClaimError as e:
        logger.warning(f"Missing required JWT claim: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")


def revoke_token(token: str) -> bool:
    """Revoke a JWT token by adding its jti to the revocation list."""
    try:
        payload = jwt.decode(token, ADMIN_SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False})
        jti = payload.get("jti")
        if jti:
            REVOKED_TOKENS.add(jti)
            logger.info(f"Token revoked: jti={jti}")
            return True
    except Exception as e:
        logger.warning(f"Failed to revoke token: {e}")
    return False


def _admin_count() -> int:
    with get_db_context() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM admins").fetchone()
        return row["cnt"]


def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    token_str = None
    if credentials and credentials.credentials:
        token_str = credentials.credentials
    else:
        token_str = request.query_params.get("token")
    if not token_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _decode_token(token_str)
    username = payload.get("sub")
    with get_db_context() as conn:
        admin = conn.execute(
            "SELECT id, username, role, permissions, email, tenant_id FROM admins WHERE username = ?", (username,)
        ).fetchone()
    if not admin:
        raise HTTPException(status_code=401, detail="Admin not found")
    result = dict(admin) if hasattr(admin, "keys") else dict(admin)
    result["permissions"] = _effective_permissions(result.get("role"), result.get("permissions"))
    return result


# ── Tenant-scoped tokens (Phase 0.5) ──────────────────────────────────────
# A tenant token is an opaque secret stored only as a SHA-256 hash. It carries
# exactly one capability: publish/read that tenant's profile. Cross-tenant
# access is refused even when the token is valid.

def hash_tenant_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _raw_bearer(request: Request, credentials) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    return request.query_params.get("token")


def get_tenant_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict | None:
    """Resolve the caller as a tenant principal, or None if not one.

    Returns {"type": "tenant", "tenant_id": ...} for a valid tenant token.
    Returns None (rather than raising) for anything else so the caller can fall
    back to the admin path.
    """
    raw = _raw_bearer(request, credentials)
    if not raw:
        return None
    from shared.tenancy import store as tenancy_store

    record = tenancy_store.get_tenant_token(hash_tenant_token(raw))
    if not record:
        return None
    return {
        "type": "tenant",
        "tenant_id": record["tenant_id"],
        "token_id": record["id"],
        "label": record.get("label", ""),
    }


def require_tenant_access():
    """Dependency: the caller must be an admin or THIS tenant's token.

    Enforces ``token.tenant_id == target`` (Phase 0.5). A super admin passes for
    any tenant; a sub admin needs manage_operations; a tenant token is bound to
    its own tenant and nothing else.

    ``tenant_id`` below is a path parameter: FastAPI fills it from the route
    (``/tenants/{tenant_id}/...``), so the check is always against the tenant
    actually addressed, never a value supplied in a request body.
    """
    def dependency(
        request: Request,
        tenant_id: str,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        target = str(tenant_id or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="tenant_id is required")

        raw = _raw_bearer(request, credentials)
        if not raw:
            raise HTTPException(status_code=401, detail="Not authenticated")

        principal = get_tenant_principal(request, credentials)
        if principal is not None:
            if principal["tenant_id"] != target:
                logger.warning(
                    "Tenant token scope violation: token for %s tried to touch %s",
                    principal["tenant_id"], target,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Token is scoped to tenant '{principal['tenant_id']}'",
                )
            return {"type": "tenant", "tenant_id": target,
                    "label": principal.get("label", "")}

        admin = get_current_admin(request, credentials)
        if not has_permission(admin, "manage_operations"):
            raise HTTPException(
                status_code=403, detail="You do not have permission to manage tenant profiles"
            )
        # Enforce tenant scoping for non-super-admins
        role = admin.get("role")
        if role != "super_admin":
            admin_tenant = admin.get("tenant_id")
            if admin_tenant and admin_tenant != target:
                raise HTTPException(
                    status_code=403, detail=f"Admin is scoped to tenant '{admin_tenant}'"
                )
            # If admin has no tenant_id set yet, they may still access (backcompat) but better to scope
        return {"type": "admin", "username": admin.get("username", ""), "role": admin.get("role", "")}

    return dependency




# ---------- request schemas ----------

class FirstAdminRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateAdminRequest(BaseModel):
    username: str
    password: str
    role: str = "sub_admin"
    permissions: Optional[dict] = None
    email: Optional[str] = None
    tenant_id: Optional[str] = None


class UpdateAdminRequest(BaseModel):
    role: Optional[str] = None
    permissions: Optional[dict] = None
    email: Optional[str] = None
    tenant_id: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RequestOtpRequest(BaseModel):
    username: str


class ResetPasswordRequest(BaseModel):
    username: str
    otp: str
    new_password: str


class ResetAdminPasswordRequest(BaseModel):
    new_password: str


# ---------- routes ----------

@router.get("/status")
def auth_status():
    """Public: returns whether any admin accounts exist."""
    return {"has_admins": _admin_count() > 0}


@router.post("/first-admin")
# SECURITY FIX: Rate limiting - 5 requests per minute for first admin creation
@limiter.limit("5/minute") if RATE_LIMIT_ENABLED else lambda f: f
async def create_first_admin(request: Request, body: FirstAdminRequest):
    """Create the very first admin. Only works when zero admins exist."""
    # SECURITY FIX: Validate password strength
    _validate_password_strength(body.password)
    
    if _admin_count() > 0:
        raise HTTPException(
            status_code=403,
            detail="Admin already exists. Use /api/auth/create with an admin token.",
        )

    hashed = _hash_password(body.password)
    role = "super_admin"
    email = (body.email or "").strip() or None
    with get_db_context() as conn:
        conn.execute(
            "INSERT INTO admins (username, password_hash, role, permissions, email, tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
            (body.username, hashed, role, json.dumps(SUPER_ADMIN_PERMISSIONS), email, None),
        )

    token = _create_token(body.username)
    logger.info(f"First admin created (super admin): {body.username}")
    return {
        "status": "ok",
        "token": token,
        "username": body.username,
        "role": role,
        "permissions": dict(SUPER_ADMIN_PERMISSIONS),
        "tenant_id": None,
    }


@router.post("/login")
# SECURITY FIX: Rate limiting - 5 requests per minute for login attempts
@limiter.limit("5/minute") if RATE_LIMIT_ENABLED else lambda f: f
async def admin_login(request: Request, body: LoginRequest):
    """Authenticate an admin and return a JWT."""
    with get_db_context() as conn:
        admin = conn.execute(
            "SELECT id, username, password_hash, role, permissions, tenant_id FROM admins WHERE username = ?",
            (body.username,),
        ).fetchone()

    if not admin or not _verify_password(body.password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    admin_dict = dict(admin)
    token = _create_token(admin_dict["username"])
    logger.info(f"Admin logged in: {admin_dict['username']}")
    return {
        "status": "ok",
        "token": token,
        "username": admin_dict["username"],
        "role": admin_dict["role"],
        "permissions": _effective_permissions(admin_dict["role"], admin_dict["permissions"]),
        "tenant_id": admin_dict.get("tenant_id"),
    }


@router.post("/create")
def create_admin(body: CreateAdminRequest, current_admin: dict = Depends(get_current_admin)):
    """Create a new admin. Requires the manage_admins permission."""
    if not has_permission(current_admin, "manage_admins"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to manage admins",
        )
    if _admin_count() == 0:
        raise HTTPException(
            status_code=403,
            detail="No admins exist yet. Use /api/auth/first-admin first.",
        )

    # SECURITY FIX: Validate password strength for new admins
    _validate_password_strength(body.password)
    
    # Normalize role
    role = body.role or "sub_admin"
    if role not in ("super_admin", "admin", "sub_admin"):
        # Try to normalize
        if role == "subadmin" or role == "sub-admin":
            role = "sub_admin"
        elif role == "superadmin" or role == "super-admin":
            role = "super_admin"
        else:
            role = "sub_admin"

    current_role = current_admin.get("role")
    if role == "super_admin" and current_role != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can create another super admin")
    if role == "admin" and current_role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only super admin or admin can create an admin")
    if role == "sub_admin" and current_role != "admin":
        raise HTTPException(status_code=403, detail="Sub-admin can only be created by admin")

    # A new admin starts with every permission on (default_all=True); the
    # super admin can then edit the switches. Sub admins start with none.
    permissions = (
        dict(SUPER_ADMIN_PERMISSIONS)
        if role == "super_admin"
        else _parse_permissions(body.permissions, default_all=(role == "admin"))
    )

    email = (body.email or "").strip() or None

    # Determine tenant scope
    tenant_id = body.tenant_id
    if tenant_id is not None and isinstance(tenant_id, str):
        tenant_id = tenant_id.strip() or None
    if current_role != "super_admin":
        # Only a super admin chooses the tenant; every other creator is
        # strictly scoped to their own tenant.
        tenant_id = current_admin.get("tenant_id")
    # If super_admin creating super_admin, tenant_id is None

    with get_db_context() as conn:
        try:
            conn.execute(
                "INSERT INTO admins (username, password_hash, role, permissions, email, tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
                (body.username, _hash_password(body.password), role, json.dumps(permissions), email, tenant_id),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="Username already taken")

    logger.info(f"Admin created by {current_admin['username']}: {body.username} ({role})")
    return {"status": "ok", "username": body.username, "role": role, "permissions": permissions, "email": email, "tenant_id": tenant_id, "created_by": current_admin["username"]}


@router.get("/admins")
def list_admins(current_admin: dict = Depends(require_permission("manage_admins"))):
    """List all admin accounts with their roles and permissions."""
    result = []
    for a in list_admin_records():
        result.append({
            "username": a["username"],
            "email": a.get("email"),
            "role": a["role"],
            "permissions": _effective_permissions(a["role"], a["permissions"]),
            "created_at": a.get("created_at"),
            "tenant_id": a.get("tenant_id"),
        })
    return {"admins": result}


@router.patch("/admins/{username}")
def update_admin(username: str, body: UpdateAdminRequest, current_admin: dict = Depends(get_current_admin)):
    """Update an admin's role and/or permissions. Requires the manage_admins permission."""
    if not has_permission(current_admin, "manage_admins"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage admins")

    target = get_admin_record(username)
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")

    is_self = username == current_admin["username"]

    if is_self and (body.role is not None or body.permissions is not None):
        raise HTTPException(
            status_code=403,
            detail="You cannot change your own role or permissions. Ask another admin with manage admins permission.",
        )

    new_role = body.role
    if new_role is not None:
        # Normalize
        if new_role in ("superadmin", "super-admin"):
            new_role = "super_admin"
        elif new_role in ("subadmin", "sub-admin"):
            new_role = "sub_admin"
        elif new_role == "admin":
            new_role = "admin"
        if new_role not in ("super_admin", "admin", "sub_admin"):
            new_role = target["role"]

        current_role = current_admin.get("role")
        if new_role == "super_admin" and current_role != "super_admin":
            raise HTTPException(status_code=403, detail="Only a super admin can promote to super admin")
        if target["role"] == "super_admin" and new_role != "super_admin" and current_role != "super_admin":
            raise HTTPException(status_code=403, detail="Only a super admin can demote a super admin")
        if target["role"] == "super_admin" and new_role != "super_admin" and count_admins_by_role("super_admin") <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last super admin")
    else:
        new_role = target["role"]

    if body.permissions is not None:
        permissions = _parse_permissions(body.permissions, default_all=False)
    else:
        permissions = _parse_permissions(target["permissions"])

    if new_role == "super_admin":
        permissions = dict(SUPER_ADMIN_PERMISSIONS)
    elif new_role == "admin" and target["role"] != "admin":
        # Promoting to admin grants the full set up front; a super admin can
        # edit the switches down afterwards.
        permissions = dict(SUPER_ADMIN_PERMISSIONS)

    # Only a super admin may re-scope an admin to another tenant; for everyone
    # else tenant_id is left untouched (None means "no change" here).
    tenant_id = body.tenant_id if current_admin.get("role") == "super_admin" else None

    update_admin_record(username, new_role, permissions, tenant_id=tenant_id)

    if body.email is not None:
        email = body.email.strip() or None
        update_admin_email(username, email)

    logger.info(f"Admin updated by {current_admin['username']}: {username} ({new_role})")
    return {"status": "ok", "username": username, "role": new_role, "permissions": permissions}


@router.delete("/admins/{username}")
def delete_admin_endpoint(username: str, current_admin: dict = Depends(get_current_admin)):
    """Delete an admin account. Requires the manage_admins permission."""
    if not has_permission(current_admin, "manage_admins"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage admins")

    if username == current_admin["username"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    target = get_admin_record(username)
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")

    if target["role"] == "super_admin":
        raise HTTPException(status_code=403, detail="Super admin accounts cannot be deleted")

    delete_admin(username)
    logger.info(f"Admin deleted by {current_admin['username']}: {username}")
    return {"status": "ok", "username": username}


@router.post("/admins/{username}/reset-password")
def reset_admin_password(username: str, body: ResetAdminPasswordRequest, current_admin: dict = Depends(get_current_admin)):
    """Reset another admin's password. Requires the manage_admins permission."""
    if not has_permission(current_admin, "manage_admins"):
        raise HTTPException(status_code=403, detail="You do not have permission to manage admins")

    if not body.new_password or len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    target = get_admin_record(username)
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")

    if username == current_admin["username"]:
        raise HTTPException(
            status_code=403,
            detail="Use Change Password to reset your own password.",
        )

    # Hierarchy rules
    current_role = current_admin.get("role")
    target_role = target.get("role")
    if target_role == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot change password of super admin")
    if target_role == "admin" and current_role != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can change password of an admin")
    if target_role == "sub_admin" and current_role != "admin" and current_role != "super_admin":
        raise HTTPException(status_code=403, detail="Only admin or super admin can change password of sub-admin")

    hashed = _hash_password(body.new_password)
    with get_db_context() as conn:
        conn.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (hashed, username,),
        )

    logger.info(f"Password reset for admin {username} by {current_admin['username']}")
    return {"status": "ok", "message": "Password reset successfully"}


@router.get("/me")
def admin_me(current_admin: dict = Depends(get_current_admin)):
    """Return the currently authenticated admin."""
    return {
        "username": current_admin["username"],
        "role": current_admin["role"],
        "permissions": current_admin["permissions"],
        "tenant_id": current_admin.get("tenant_id"),
    }


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, current_admin: dict = Depends(get_current_admin)):
    """Change the current admin's password."""
    with get_db_context() as conn:
        admin = conn.execute(
            "SELECT password_hash FROM admins WHERE username = ?",
            (current_admin["username"],),
        ).fetchone()

    if not admin or not _verify_password(body.current_password, admin["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")

    # SECURITY FIX: Validate new password strength
    _validate_password_strength(body.new_password)

    hashed = _hash_password(body.new_password)
    with get_db_context() as conn:
        conn.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (hashed, current_admin["username"],),
        )

    logger.info(f"Password changed for admin: {current_admin['username']}")
    return {"status": "ok", "message": "Password changed successfully"}


def _validate_password_strength(password: str):
    """Validate password meets security requirements. SECURITY FIX."""
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")
    
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    
    # Check for common patterns (simple check without external library)
    if password.lower() in ['password', '12345678', 'qwerty', 'admin']:
        raise HTTPException(
            status_code=400,
            detail="Password is too common"
        )
    
    # Check for complexity
    if not any(c.isupper() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one uppercase letter"
        )
    if not any(c.islower() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one lowercase letter"
        )
    if not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one digit"
        )
    if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one special character"
        )


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    visible = local[:1] if len(local) > 1 else local[:1]
    masked_local = visible + "*" * max(len(local) - 1, 1)
    return f"{masked_local}@{domain}"


@router.post("/request-otp")
# SECURITY FIX: Rate limiting - 5 requests per minute for OTP requests
@limiter.limit("5/minute") if RATE_LIMIT_ENABLED else lambda f: f
async def request_otp(request: Request, body: RequestOtpRequest):
    """Generate a password-reset OTP and email it to the admin. No JWT required."""
    with get_db_context() as conn:
        admin = conn.execute(
            "SELECT id, email FROM admins WHERE username = ?",
            (body.username,),
        ).fetchone()

    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    email = admin["email"]
    if not email:
        raise HTTPException(
            status_code=400,
            detail="No email is linked to this admin. Ask a super admin to set one.",
        )

    otp = f"{secrets.randbelow(1000000):06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
    set_admin_otp(body.username, otp, expires_at)

    if not send_otp_email(email, otp, OTP_EXPIRY_MINUTES):
        raise HTTPException(
            status_code=503,
            detail="Failed to send OTP email. Check that SMTP is configured in the backend .env.",
        )

    logger.info(f"OTP sent to admin: {body.username}")
    return {
        "status": "ok",
        "message": "OTP sent to your email",
        "email_masked": _mask_email(email),
        "expires_minutes": OTP_EXPIRY_MINUTES,
    }


@router.post("/reset-password")
# SECURITY FIX: Rate limiting - 5 requests per minute for password reset
@limiter.limit("5/minute") if RATE_LIMIT_ENABLED else lambda f: f
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Reset an admin's password using an emailed OTP. No JWT required."""
    record = get_admin_otp(body.username)
    if not record:
        raise HTTPException(status_code=400, detail="No OTP requested for this admin")

    expires_at = datetime.fromisoformat(record["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        clear_admin_otp(body.username)
        raise HTTPException(status_code=400, detail="OTP has expired. Request a new one.")

    if not bcrypt.checkpw(body.otp.encode(), record["otp_code"].encode()):
        raise HTTPException(status_code=403, detail="Invalid OTP")

    hashed = _hash_password(body.new_password)
    with get_db_context() as conn:
        conn.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (hashed, body.username,),
        )
    clear_admin_otp(body.username)

    logger.info(f"Password reset for admin: {body.username}")
    return {"status": "ok", "message": "Password reset successfully"}
