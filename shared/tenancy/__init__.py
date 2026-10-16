"""Tenant profile substrate.

The only behavioural source of truth for a brand. ``backend/`` imports this
(decision D1); ``kb/`` and ``routing/`` adopt it in Phase 7.

    from shared.tenancy import get_tenant_profile, require_feature
    profile = get_tenant_profile("troogood")
    if profile.feature_on("cart"):
        ...
"""

from .cache import stats as cache_stats, purge as purge_cache
from .defaults import DEFAULT_TENANT_ID, VERTICAL_DEFAULTS, get_vertical_defaults, list_verticals
from .gating import (
    FeatureDisabled,
    guard,
    intent_allowed,
    intent_refusal,
    is_enabled,
    refusal_message,
    require,
)
from .hours import greeting_for, is_business_hours, is_open_for, select_flow_name
from .lint import lint_profile, lint_tenant
from .loader import (
    ProfileValidationError,
    build_profile,
    describe_layers,
    get_tenant_profile,
    reload_profile,
    validate_merged_profile,
)
from .paths import CLIENTS_DIR, client_config_path, client_dir, client_knowledge_dir, ensure_client_dir
from .records import (
    COLUMN_TYPES,
    DEFAULT_COLUMNS,
    SYSTEM_COLUMNS,
    ColumnError,
    default_columns_for,
    sync_columns,
)
from .resolver import bind_phone_id, resolve_tenant_for_phone, resolve_tenant_from_payload
from .schemas import (
    FEATURE_FLAGS,
    STEP_TYPES,
    VERTICALS,
    Brand,
    BusinessHours,
    Features,
    FlowSpec,
    FlowStep,
    Guardrails,
    IntentSpec,
    MenuButton,
    MenuSpec,
    NotificationChannel,
    Notifications,
    TenantProfile,
    Vocabulary,
    is_valid_phone,
    is_valid_phone_input,
)
from .store import (
    create_tenant_token,
    ensure_tenant,
    get_tenant,
    get_tenant_token,
    list_tenant_tokens,
    list_tenants,
    revoke_tenant_token,
)

__all__ = [
    # loader
    "get_tenant_profile", "reload_profile", "build_profile",
    "validate_merged_profile", "describe_layers", "ProfileValidationError",
    # lint
    "lint_profile", "lint_tenant",
    # resolver
    "resolve_tenant_from_payload", "resolve_tenant_for_phone", "bind_phone_id",
    # gating
    "require", "is_enabled", "guard", "refusal_message", "FeatureDisabled",
    "intent_allowed", "intent_refusal",
    # hours
    "is_open_for", "is_business_hours", "select_flow_name", "greeting_for",
    # schemas
    "TenantProfile", "Features", "Vocabulary", "Brand", "MenuSpec", "MenuButton",
    "IntentSpec", "FlowSpec", "FlowStep", "Guardrails", "BusinessHours",
    "Notifications", "NotificationChannel", "FEATURE_FLAGS", "STEP_TYPES", "VERTICALS",
    "is_valid_phone", "is_valid_phone_input",
    # defaults
    "VERTICAL_DEFAULTS", "get_vertical_defaults", "list_verticals", "DEFAULT_TENANT_ID",
    # store
    "ensure_tenant", "get_tenant", "list_tenants", "create_tenant_token",
    "get_tenant_token", "list_tenant_tokens", "revoke_tenant_token",
    # records
    "COLUMN_TYPES", "DEFAULT_COLUMNS", "SYSTEM_COLUMNS", "ColumnError",
    "default_columns_for", "sync_columns",
    # paths / cache
    "CLIENTS_DIR", "client_dir", "client_config_path", "client_knowledge_dir",
    "ensure_client_dir", "purge_cache", "cache_stats",
]
