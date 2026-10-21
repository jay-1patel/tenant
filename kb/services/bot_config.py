import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from routing.config import BASE_DIR, BUSINESS_NAME, logger

_CONFIG_PATH = BASE_DIR.parent / "kb" / "bot.config.json"
_config_cache: Optional[Dict] = None
_client_config_cache: Dict[str, Dict] = {}
_client_config_timestamps: Dict[str, datetime] = {}
_CLIENT_CONFIG_TTL = timedelta(minutes=5)


def load_bot_config(reload: bool = False) -> Dict:
    global _config_cache
    if _config_cache is not None and not reload:
        return _config_cache

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _config_cache = raw
        logger.info(f"Bot config loaded from {_CONFIG_PATH}")
        return _config_cache
    except FileNotFoundError:
        logger.warning(f"bot.config.json not found at {_CONFIG_PATH}, using defaults")
        _config_cache = _default_config()
        return _config_cache
    except Exception as e:
        logger.error(f"Failed to load bot.config.json: {e}")
        _config_cache = _default_config()
        return _config_cache


def _default_config() -> Dict:
    return {
        "name": f"{BUSINESS_NAME} Assistant",
        "personality": (
            f"You are a friendly sales representative for {BUSINESS_NAME}. "
            "Your goal is to help customers find products, answer questions about the business, and drive sales. "
            "Be warm, professional, and conversational — like a helpful shopkeeper. "
            "Use natural language, not robotic replies. "
            "You only answer questions related to this business's products, services, and policies. "
            "If asked about anything unrelated, politely say you can only help with business-related questions. "
            "If asked for contact details, provide them directly when available; otherwise say you don't have them here and suggest the official website or packaging."
        ),
        "business_knowledge": "./knowledge/",
        "tools": ["search_products", "get_product_details", "get_faq_answer", "list_categories", "get_products_by_category", "get_contact_details", "human_handover"],
        "guardrails": (
            "NEVER make up product details, prices, or availability. "
            "NEVER answer questions about topics outside this business. "
            "If you don't know something, say 'I'll check with our team and get back to you.' "
            "Keep answers short, helpful, and focused on what the customer needs."
        ),
        "escalation_rules": {
            "trigger_phrases": ["angry", "complaint", "problem", "human", "person", "speak to", "talk to manager"],
            "max_failed_attempts": 2,
            "escalation_message": "I'll connect you with our team. Someone will follow up shortly.",
        },
        "response_settings": {
            "max_tokens": 1500,
            "temperature": 0.3,
            "similarity_threshold": 0.40,
            "context_window": 3,
            "memory_ttl_minutes": 30,
            "memory_max_messages": 10,
        },
        "welcome_message": f"Hi! Welcome to {BUSINESS_NAME}. How can I help you today?",
        "fallback_message": "I apologize, but I don't have that information available. Please try asking about our products, or type 'menu' to see main options.",
        "languages": ["en"],
        "session": {"window_hours": 24},
        "contact_details": {
            "phone": "",
            "email": "",
            "website": "",
            "address": "",
        },
    }


def get_config_value(key: str, default: Any = None) -> Any:
    cfg = load_bot_config()
    return cfg.get(key, default)


def get_personality() -> str:
    cfg = load_bot_config()
    personality = cfg.get("personality", "")
    return personality.replace("{BUSINESS_NAME}", BUSINESS_NAME)


def get_guardrails() -> str:
    cfg = load_bot_config()
    return cfg.get("guardrails", "")


def get_tools() -> List[str]:
    cfg = load_bot_config()
    return cfg.get("tools", [])


def get_escalation_rules() -> Dict:
    cfg = load_bot_config()
    rules = cfg.get("escalation_rules", {}) or {}
    # Normalize trigger phrases: ensure they are strings, trimmed, lowercased and unique
    triggers = rules.get("trigger_phrases", [])
    seen = set()
    cleaned = []
    for t in triggers:
        if not isinstance(t, str):
            continue
        key = t.strip().lower()
        if key and key not in seen:
            seen.add(key)
            cleaned.append(key)
    rules["trigger_phrases"] = cleaned
    return rules


def get_response_settings() -> Dict:
    cfg = load_bot_config()
    defaults = {
        "max_tokens": 1500,
        "temperature": 0.4,
        "similarity_threshold": 0.40,
        "context_window": 3,
        "memory_ttl_minutes": 30,
        "memory_max_messages": 10,
    }
    settings = cfg.get("response_settings", {})
    defaults.update(settings)
    return defaults


def get_contact_details() -> Dict:
    cfg = load_bot_config()
    details = cfg.get("contact_details", {}) or {}
    if not isinstance(details, dict):
        return {}
    return {
        "phone": details.get("phone", "").strip(),
        "email": details.get("email", "").strip(),
        "website": details.get("website", "").strip(),
        "address": details.get("address", "").strip(),
    }


def contact_details_available() -> bool:
    details = get_contact_details()
    return any(details.values())


def get_fallback_message() -> str:
    cfg = load_bot_config()
    return cfg.get("fallback_message", "I'm sorry, I don't have that information.")


def get_welcome_message() -> str:
    cfg = load_bot_config()
    return cfg.get("welcome_message", "Welcome! How can I help you today?")


def get_languages() -> List[str]:
    cfg = load_bot_config()
    return cfg.get("languages", ["en"])


def reload_config() -> Dict:
    global _config_cache
    _config_cache = None
    return load_bot_config(reload=True)


def update_config(updates: Dict) -> bool:
    global _config_cache
    try:
        cfg = load_bot_config()
        cfg.update(updates)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        _config_cache = cfg
        logger.info("Bot config updated and saved")
        return True
    except Exception as e:
        logger.error(f"Failed to update bot config: {e}")
        return False


# ============================================
# PRODUCTION-READY MULTI-CLIENT CONFIG SYSTEM
# ============================================

def _validate_client_config(config: Dict, client_id: str) -> bool:
    """Validate that client config has all required fields for production."""
    required_fields = ["client_id", "name", "business_name"]
    missing_fields = []

    for field in required_fields:
        if field not in config or not config[field]:
            missing_fields.append(field)

    if missing_fields:
        logger.error(f"Client {client_id} config missing required fields: {missing_fields}")
        return False

    # Validate send2 credentials if provided
    if "send2_credentials" in config:
        creds = config["send2_credentials"]
        if not isinstance(creds, dict):
            logger.error(f"Client {client_id} has invalid send2_credentials format")
            return False

        required_creds = ["username", "password", "number"]
        for cred_field in required_creds:
            if cred_field not in creds or not creds[cred_field]:
                logger.error(f"Client {client_id} missing send2 credential: {cred_field}")
                return False

    return True


def _get_client_config_path(client_id: str) -> Path:
    """Get the config file path for a specific client."""
    client_dir = BASE_DIR / "clients" / client_id
    return client_dir / "config.json"


def load_client_config(client_id: str, force_reload: bool = False) -> Dict:
    """
    Load client-specific config with production-ready validation and hot-reload.

    Args:
        client_id: The client identifier (e.g., 'troo_good', 'balaji')
        force_reload: Force reload from disk even if cached

    Returns:
        Client config dict, or global default if client config missing/invalid
    """
    global _client_config_cache, _client_config_timestamps

    if not client_id:
        logger.warning("load_client_config called with empty client_id, using global config")
        return load_bot_config()

    # Check cache validity
    if not force_reload and client_id in _client_config_cache:
        cache_time = _client_config_timestamps.get(client_id, datetime.min)
        if datetime.now() - cache_time < _CLIENT_CONFIG_TTL:
            logger.debug(f"Using cached config for client {client_id}")
            return _client_config_cache[client_id]

    config_path = _get_client_config_path(client_id)

    try:
        if not config_path.exists():
            logger.warning(f"Client config not found: {config_path}, using global config")
            return load_bot_config()

        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # Validate config before using
        if not _validate_client_config(raw, client_id):
            logger.error(f"Client {client_id} config validation failed, using global config")
            return load_bot_config()

        # Cache the valid config
        _client_config_cache[client_id] = raw
        _client_config_timestamps[client_id] = datetime.now()

        logger.info(f"Client config loaded: {client_id} from {config_path}")
        return raw

    except json.JSONDecodeError as e:
        logger.error(f"Client {client_id} config JSON decode error: {e}, using global config")
        return load_bot_config()
    except Exception as e:
        logger.error(f"Failed to load client {client_id} config: {e}, using global config")
        return load_bot_config()


def get_client_config(client_id: str = None) -> Dict:
    """
    Get config for specific client, or global default if no client specified.

    This is the main entry point for production multi-client config access.
    """
    if client_id:
        return load_client_config(client_id)
    return load_bot_config()


def get_domain_guardrails(client_id: str = None) -> Dict:
    """
    Get domain-specific guardrails for a particular client.
    
    Domain guardrails are industry-specific restrictions (certifications, nutrition, allergens, etc.)
    that only apply to clients in specific industries or regions. For clients without specific
    domain guardrails, this returns a default empty dict allowing broader responses.
    
    Args:
        client_id: The client identifier (e.g., 'troo_good', 'balaji', 'food_supplier').
                  If None, uses the global default (empty domain guardrails).
    
    Returns:
        Dict containing domain-specific guardrails (empty by default). Contains keys like:
        - certifications: List of certification types that are blocked
        - nutrition_claims: List of nutrition-related phrases that are blocked  
        - allergen_notes: List of allergen claim patterns that are blocked
        - pricing_examples: List of pricing examples that are blocked
        - health_disclaimers: List of health disclaimer patterns that are blocked
        
    Note: Domain guardrails define what industry-specific content is restricted for this client.
    Only content explicitly listed here is blocked; all other content is allowed.
    """
    # Start with empty domain guardrails (permissive by default)
    domain_guardrails = {
        "certifications": [],
        "nutrition_claims": [],
        "allergen_notes": [],
        "pricing_examples": [],
        "health_disclaimers": []
    }
    
    # Load client config to check for domain-specific override
    client_config = get_client_config(client_id)
    
    # Extract domain_guardrails from client config if present
    config_domain_guardrails = client_config.get("domain_guardrails", {})
    if config_domain_guardrails:
        # Update defaults with client-specific values
        for key in domain_guardrails:
            if key in config_domain_guardrails:
                domain_guardrails[key] = config_domain_guardrails[key]
    
    return domain_guardrails


def reload_all_client_configs() -> Dict[str, bool]:
    """
    Hot-reload all client configs - useful for adding new brands without restart.

    Returns:
        Dict mapping client_id to load success (True) or failure (False)
    """
    global _client_config_cache, _client_config_timestamps

    results = {}
    clients_dir = BASE_DIR / "clients"

    if not clients_dir.exists():
        logger.warning("Clients directory not found")
        return results

    for client_dir in clients_dir.iterdir():
        if not client_dir.is_dir():
            continue

        client_id = client_dir.name
        try:
            config = load_client_config(client_id, force_reload=True)
            results[client_id] = config is not None
        except Exception as e:
            logger.error(f"Failed to reload client {client_id}: {e}")
            results[client_id] = False

    logger.info(f"Reloaded {len(results)} client configs, {sum(results.values())} successful")
    return results


def clear_client_config_cache(client_id: str = None):
    """
    Clear config cache - useful for config updates or testing.

    Args:
        client_id: Specific client to clear, or None to clear all client caches
    """
    global _client_config_cache, _client_config_timestamps

    if client_id:
        _client_config_cache.pop(client_id, None)
        _client_config_timestamps.pop(client_id, None)
        logger.info(f"Cleared config cache for client {client_id}")
    else:
        _client_config_cache.clear()
        _client_config_timestamps.clear()
        logger.info("Cleared all client config caches")


def list_active_clients() -> List[str]:
    """List all clients that have valid configs loaded."""
    clients_dir = BASE_DIR / "clients"
    active_clients = []

    if not clients_dir.exists():
        return active_clients

    for client_dir in clients_dir.iterdir():
        if not client_dir.is_dir():
            continue

        config_path = client_dir / "config.json"
        if config_path.exists():
            try:
                # Quick validation - try to load and validate
                config = load_client_config(client_dir.name)
                if config and config.get("client_id") == client_dir.name:
                    active_clients.append(client_dir.name)
            except Exception:
                pass

    return active_clients


def get_client_business_name(client_id: str = None) -> str:
    """Get business name for specific client, or global default."""
    config = get_client_config(client_id)
    return config.get("business_name", BUSINESS_NAME)


def get_client_bot_name(client_id: str = None) -> str:
    """Get bot name for specific client, or global default."""
    config = get_client_config(client_id)
    return config.get("bot_name", config.get("name", f"{BUSINESS_NAME} Assistant"))


def get_client_personality(client_id: str = None) -> str:
    """Get personality for specific client, with business name substitution."""
    config = get_client_config(client_id)
    personality = config.get("personality", "")
    business_name = get_client_business_name(client_id)

    # Replace both old and new style placeholders
    personality = personality.replace("{BUSINESS_NAME}", business_name)
    personality = personality.replace("{{BUSINESS_NAME}}", business_name)
    personality = personality.replace("[BUSINESS_NAME]", business_name)

    return personality


def get_client_whatsapp_credentials(client_id: str = None) -> Dict[str, str]:
    """
    Get WhatsApp send2 credentials for specific client.

    Returns:
        Dict with 'username', 'password', 'number' keys
        Empty dict if credentials not properly configured
    """
    config = get_client_config(client_id)
    creds = config.get("send2_credentials", {})

    if not isinstance(creds, dict):
        logger.warning(f"Invalid send2_credentials format for client {client_id or 'global'}")
        return {}

    # Validate required credential fields
    required_fields = ["username", "password", "number"]
    if not all(field in creds and creds[field] for field in required_fields):
        logger.warning(f"Missing required send2 credentials for client {client_id or 'global'}")
        return {}

    return {
        "username": creds["username"],
        "password": creds["password"],
        "number": creds["number"],
    }


def get_client_whatsapp_config(client_id: str = None) -> Dict:
    """Get WhatsApp-specific configuration for client."""
    config = get_client_config(client_id)
    return config.get("whatsapp", {})


def client_has_valid_config(client_id: str) -> bool:
    """Check if client has a valid, loadable configuration."""
    try:
        config = load_client_config(client_id)
        return config is not None and _validate_client_config(config, client_id)
    except Exception:
        return False


def validate_production_readiness() -> Dict[str, Any]:
    """
    Validate that system is production-ready with proper client configs.

    Returns:
        Dict with validation results and any issues found
    """
    issues = []
    warnings = []
    active_clients = []

    # Check clients directory exists
    clients_dir = BASE_DIR / "clients"
    if not clients_dir.exists():
        issues.append("Clients directory not found - multi-client system not properly set up")
        return {
            "ready": False,
            "issues": issues,
            "warnings": warnings,
            "active_clients": active_clients
        }

    # Check for at least one valid client config
    active_clients = list_active_clients()
    if not active_clients:
        issues.append("No valid client configurations found - system cannot handle traffic")

    # Validate each active client
    for client_id in active_clients:
        config = load_client_config(client_id)

        # Check send2 credentials
        if not config.get("send2_credentials"):
            warnings.append(f"Client {client_id} missing send2_credentials - will use global")
        else:
            creds = get_client_whatsapp_credentials(client_id)
            if not creds:
                issues.append(f"Client {client_id} has invalid send2_credentials - cannot send messages")

        # Check for required config sections
        required_sections = ["personality", "whatsapp"]
        for section in required_sections:
            if not config.get(section):
                warnings.append(f"Client {client_id} missing {section} section - will use defaults")

    return {
        "ready": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "active_clients": active_clients,
        "total_clients": len(active_clients)
    }


# BACKWARD COMPATIBILITY: Update existing functions to support client_id parameter

def get_personality(client_id: str = None) -> str:
    """Get personality with optional client_id parameter."""
    return get_client_personality(client_id)


def get_contact_details(client_id: str = None) -> Dict:
    """Get contact details with optional client_id parameter."""
    config = get_client_config(client_id)
    details = config.get("contact_details", {}) or {}
    if not isinstance(details, dict):
        return {}
    return {
        "phone": details.get("phone", "").strip(),
        "email": details.get("email", "").strip(),
        "website": details.get("website", "").strip(),
        "address": details.get("address", "").strip(),
    }


def get_category_keywords(client_id: str = None) -> Dict:
    """
    Get industry-specific category keywords for a particular client.
    
    Category keywords are used for intent classification (shipping, returns, privacy, payment, etc.).
    Different industries use different terminology for the same general categories.
    
    Args:
        client_id: The client identifier (e.g., 'troo_good', 'balaji', 'logistics_provider').
                  If None, uses the global default.
    
    Returns:
        Dict containing category keywords (default English-based). Keys are category names
        (shipping_policy, returns_policy, privacy_policy, payment) and values are lists of
        keywords that trigger that category intent.
    """
    # Default English-based category keywords
    category_keywords = {
        "shipping_policy": ["ship", "deliver", "delivery", "tracking", "order status", "dispatch", "logistics", "courier"],
        "returns_policy": ["refund", "cancel", "cancellation", "return", "exchange", "replacement", "money back"],
        "privacy_policy": ["privacy", "data", "personal", "confidential", "gdpr", "policy", "terms"],
        "payment": ["payment", "pay", "upi", "card", "cod", "cash on delivery", "invoice", "billing"]
    }
    
    # Load client config to check for industry-specific override
    client_config = get_client_config(client_id)
    
    # Extract category_keywords from client config if present
    config_category_keywords = client_config.get("category_keywords", {})
    if config_category_keywords:
        # Update defaults with client-specific values
        for key in category_keywords:
            if key in config_category_keywords:
                category_keywords[key] = config_category_keywords[key]
    
    return category_keywords
