"""Send2 Digital Configuration for WhatsApp Business API Integration.

This module provides centralized configuration for your Send2 Digital WhatsApp 
integration used throughout the callback booking pipeline.

Setup Instructions:
1. Sign up for Send2 Digital WhatsApp Business API
2. Create a WhatsApp Business Account
3. Get your API credentials
4. Configure the following environment variables:

Required Environment Variables:
- SEND2_API_KEY: Your Send2 Digital API key
- SEND2_API_SECRET: Your Send2 Digital API secret
- SEND2_WHA_BUSINESS_ID: Your WhatsApp Business Account ID
- SEND2_PHONE_NUMBER_ID: Your WhatsApp Business phone number ID

Optional Environment Variables:
- SEND2_BASE_URL: Custom Send2 API URL (default: https://api.send2.digital)
- SEND2WEBHOOK_SECRET: Webhook verification secret for incoming messages
- SEND2_RATE_LIMIT: Rate limit in requests per second (default: 10)

Template Requirements:
For callback booking, you'll need the following WhatsApp message templates:
1. callback_confirmation - For confirming callback requests
2. callback_scheduled - For notifying when callback is scheduled
3. callback_reminder - For meeting reminders
4. callback_cancelled - For cancellation notifications

Example template structure:
{
  "name": "callback_confirmation",
  "language": "en_US",
  "category": "UTILITY",
  "components": [
    {
      "type": "BODY",
      "text": "Thank you for your callback request! Our team will contact you shortly. Request ID: {{1}}"
    }
  ]
}
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Send2Environment(Enum):
    """Send2 Digital API environments."""
    PRODUCTION = "production"
    SANDBOX = "sandbox"
    DEVELOPMENT = "development"


@dataclass
class Send2Credentials:
    """Send2 Digital API credentials."""
    api_key: str
    api_secret: str
    wha_business_id: str
    phone_number_id: str
    base_url: str = "https://api.send2.digital"
    
    def __post_init__(self):
        # Clean URLs
        if self.base_url.endswith('/'):
            self.base_url = self.base_url[:-1]


@dataclass
class WhatsAppTemplate:
    """WhatsApp message template configuration."""
    name: str
    language: str = "en_US"
    category: str = "UTILITY"
    body: Optional[str] = None
    header: Optional[Dict[str, Any]] = None
    footer: Optional[str] = None
    buttons: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_api_format(self) -> Dict[str, Any]:
        """Convert to Send2 API template format."""
        template: Dict[str, Any] = {
            "name": self.name,
            "language": self.language,
            "category": self.category,
            "components": []
        }
        
        if self.header:
            template["components"].append({"type": "HEADER", **self.header})
        
        if self.body:
            template["components"].append({"type": "BODY", "text": self.body})
        
        if self.footer:
            template["components"].append({"type": "FOOTER", "text": self.footer})
        
        for button in self.buttons:
            template["components"].append({"type": "BUTTONS", **button})
        
        return template


class Send2Config:
    """Main Send2 Digital configuration manager."""
    
    def __init__(self):
        self.credentials: Optional[Send2Credentials] = None
        self.environment = Send2Environment.PRODUCTION
        self.rate_limit = 10  # requests per second
        self.timeout = 30.0  # connection timeout in seconds
        self.retries = 3  # number of retries for failed requests
        self.templates: Dict[str, WhatsAppTemplate] = {}
        self.webhook_secret: Optional[str] = None
        self._load_from_environment()
    
    def _load_from_environment(self):
        """Load configuration from environment variables."""
        try:
            # Load credentials
            api_key = os.getenv("SEND2_API_KEY")
            api_secret = os.getenv("SEND2_API_SECRET")
            wha_business_id = os.getenv("SEND2_WHA_BUSINESS_ID")
            phone_number_id = os.getenv("SEND2_PHONE_NUMBER_ID")
            
            if api_key and api_secret and wha_business_id and phone_number_id:
                base_url = os.getenv("SEND2_BASE_URL", "https://api.send2.digital")
                self.credentials = Send2Credentials(
                    api_key=api_key,
                    api_secret=api_secret,
                    wha_business_id=wha_business_id,
                    phone_number_id=phone_number_id,
                    base_url=base_url
                )
                logger.info("Send2 credentials loaded successfully")
            else:
                logger.warning("Send2 credentials not fully configured")
                logger.info(f"Missing: API Key: {not api_key}, API Secret: {not api_secret}, "
                           f"WHA Business ID: {not wha_business_id}, Phone ID: {not phone_number_id}")
            
            # Load environment
            env = os.getenv("SEND2_ENVIRONMENT", "production").lower()
            if env == "sandbox":
                self.environment = Send2Environment.SANDBOX
            elif env == "development":
                self.environment = Send2Environment.DEVELOPMENT
            
            # Load rate limit
            rate_limit = os.getenv("SEND2_RATE_LIMIT")
            if rate_limit:
                try:
                    self.rate_limit = int(rate_limit)
                except ValueError:
                    logger.warning(f"Invalid rate limit: {rate_limit}, using default 10")
            
            # Load webhook secret
            self.webhook_secret = os.getenv("SEND2_WEBHOOK_SECRET")
            
            # Load timeout
            timeout = os.getenv("SEND2_TIMEOUT")
            if timeout:
                try:
                    self.timeout = float(timeout)
                except ValueError:
                    logger.warning(f"Invalid timeout: {timeout}, using default 30.0")
            
            # Load retries
            retries = os.getenv("SEND2_RETRIES")
            if retries:
                try:
                    self.retries = int(retries)
                except ValueError:
                    logger.warning(f"Invalid retries: {retries}, using default 3")
            
            self._initialize_templates()
            
        except Exception as e:
            logger.error(f"Failed to load Send2 configuration: {e}")
    
    def _initialize_templates(self):
        """Initialize default WhatsApp templates for callback booking."""
        # Callback Confirmation Template
        self.templates["callback_confirmation"] = WhatsAppTemplate(
            name="callback_confirmation",
            category="UTILITY",
            body="✅ Thank you for your callback request!\n\n📝 Request ID: {{1}}\n🎯 Purpose: {{2}}\n\nOur team will contact you shortly to confirm a suitable time."
        )
        
        # Callback Scheduled Template
        self.templates["callback_scheduled"] = WhatsAppTemplate(
            name="callback_scheduled",
            category="UTILITY",
            body="📅 Callback Confirmed!\n\n📆 Date: {{1}}\n⏰ Time: {{2}}\n👤 Agent: {{3}}\n🎯 Purpose: {{4}}\n\n🔗 Join Meeting: {{5}}"
        )
        
        # Callback Reminder Template
        self.templates["callback_reminder"] = WhatsAppTemplate(
            name="callback_reminder",
            category="UTILITY",
            body="⏰ REMINDER: Your callback starts in {{1}} minutes!\n\n📅 Date: {{2}}\n⏰ Time: {{3}}\n👤 Agent: {{4}}\n🔗 Join Now: {{5}}"
        )
        
        # Callback Cancelled Template
        self.templates["callback_cancelled"] = WhatsAppTemplate(
            name="callback_cancelled",
            category="UTILITY",
            body="❌ Callback Cancelled\n\n🎫 Request ID: {{1}}\n📅 Date: {{2}}\n⏰ Time: {{3}}\n💬 Reason: {{4}}"
        )
        
        # Agent Assignment Template (for internal use)
        self.templates["agent_assignment"] = WhatsAppTemplate(
            name="agent_assignment",
            category="UTILITY",
            body="🔔 New Callback Assigned\n\n📞 Customer: {{1}}\n📱 WhatsApp: {{2}}\n🎯 Type: {{3}}\n📅 Date: {{4}}\n⏰ Time: {{5}}\n📝 Purpose: {{6}}"
        )
    
    def is_configured(self) -> bool:
        """Check if Send2 Digital is properly configured."""
        return self.credentials is not None
    
    def get_credentials(self) -> Optional[Send2Credentials]:
        """Get Send2 credentials."""
        return self.credentials
    
    def get_credentials_dict(self) -> Dict[str, str]:
        """Get credentials as dictionary for API requests."""
        if not self.credentials:
            return {}
        
        return {
            "api_key": self.credentials.api_key,
            "api_secret": self.credentials.api_secret,
            "wha_business_id": self.credentials.wha_business_id,
            "phone_number_id": self.credentials.phone_number_id
        }
    
    def get_base_url(self) -> str:
        """Get Send2 API base URL."""
        if self.credentials:
            return self.credentials.base_url
        return "https://api.send2.digital"
    
    def get_template(self, template_name: str) -> Optional[WhatsAppTemplate]:
        """Get a specific WhatsApp template."""
        return self.templates.get(template_name)
    
    def get_all_templates(self) -> Dict[str, WhatsAppTemplate]:
        """Get all configured templates."""
        return self.templates
    
    def add_template(self, template: WhatsAppTemplate):
        """Add a custom WhatsApp template."""
        self.templates[template.name] = template
    
    def validate_webhook(self, signature: str, payload: str) -> bool:
        """Validate incoming webhook signature."""
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured")
            return False
        
        # Implement signature validation based on Send2's webhook format
        # This is typically HMAC-SHA256 with the webhook secret
        import hmac
        import hashlib
        
        expected_signature = hmac.new(
            self.webhook_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    def get_config_summary(self) -> Dict[str, Any]:
        """Get a summary of the current configuration."""
        return {
            "configured": self.is_configured(),
            "environment": self.environment.value,
            "rate_limit": self.rate_limit,
            "timeout": self.timeout,
            "retries": self.retries,
            "templates_count": len(self.templates),
            "base_url": self.get_base_url(),
            "webhook_configured": bool(self.webhook_secret)
        }


# Singleton instance
send2_config = Send2Config()


# Auto-update the Send2 callback service
def update_send2_callback_service():
    """Update the Send2 callback service with current configuration."""
    from backend.services.send2_callback_notification import send2_callback_service
    
    # Update the service with proper configuration
    config = send2_config.get_credentials()
    if config:
        send2_callback_service.api_key = config.api_key
        send2_callback_service.api_secret = config.api_secret
        send2_callback_service.whatsapp_business_id = config.wha_business_id
        send2_callback_service.phone_number_id = config.phone_number_id
        send2_callback_service.base_url = config.base_url


# Update on import
update_send2_callback_service()


# Utility for environment validation
def validate_send2_environment() -> Dict[str, Any]:
    """Validate Send2 Digital environment configuration."""
    config = send2_config
    issues = []
    warnings = []
    
    # Check credentials
    if not config.is_configured():
        issues.append("Send2 credentials not configured")
    
    # Check environment variables
    missing_vars = []
    if not os.getenv("SEND2_API_KEY"):
        missing_vars.append("SEND2_API_KEY")
    if not os.getenv("SEND2_API_SECRET"):
        missing_vars.append("SEND2_API_SECRET")
    if not os.getenv("SEND2_WHA_BUSINESS_ID"):
        missing_vars.append("SEND2_WHA_BUSINESS_ID")
    if not os.getenv("SEND2_PHONE_NUMBER_ID"):
        missing_vars.append("SEND2_PHONE_NUMBER_ID")
    
    if missing_vars:
        issues.append(f"Missing environment variables: {', '.join(missing_vars)}")
    
    # Check if it's production but no webhook secret
    if config.environment == Send2Environment.PRODUCTION and not config.webhook_secret:
        warnings.append("Webhook secret not configured for production")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "config_summary": config.get_config_summary()
    }
