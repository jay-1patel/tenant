"""
🎯 Response Formatting Configuration

This module provides centralized configuration for response formatting,
allowing customization of emoji usage, markdown styling, and brand identity.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import os


class FormattingLevel(Enum):
    """Levels of formatting intensity."""
    MINIMAL = "minimal"      # Basic formatting, no emojis
    STANDARD = "standard"    # Balanced formatting with emojis
    RICH = "rich"           # Full formatting with emojis, links, styling


@dataclass
class BrandConfig:
    """Brand-specific configuration for responses."""
    name: str = "ChatBot"
    tagline: str = "Your Smart Assistant"
    signature: str = "🤖 {name} | Your Smart Assistant"
    support_email: str = ""
    support_phone: str = ""
    website: str = ""
    logo_emoji: str = "🤖"
    
    # Social media links
    whatsapp_link: Optional[str] = None
    telegram_link: Optional[str] = None
    instagram_link: Optional[str] = None
    facebook_link: Optional[str] = None


@dataclass 
class EmojiConfig:
    """Emoji usage configuration."""
    enabled: bool = True
    frequency: str = "moderate"  # none, minimal, moderate, liberal
    
    # Custom emoji mappings (override defaults)
    custom_mappings: Dict[str, str] = field(default_factory=dict)
    
    # Categories to enable/disable
    enabled_categories: List[str] = field(default_factory=lambda: [
        "greetings", "thanks", "products", "pricing", 
        "orders", "support", "success", "error", "warning", "info"
    ])
    
    # Whitelist of allowed emojis
    whitelist: List[str] = field(default_factory=list)
    
    # Blacklist of disallowed emojis  
    blacklist: List[str] = field(default_factory=list)


@dataclass
class MarkdownConfig:
    """Markdown formatting configuration."""
    enabled: bool = True
    bold_style: str = "*"  # * or _
    italic_style: str = "_"  # * or _
    code_style: str = "```"  # ``` or '
    bullet_style: str = "•"  # •, -, *, etc.
    separator_style: str = "─"  # ─, -, =, etc.
    
    # WhatsApp formatting support
    whatsapp_compatible: bool = True


@dataclass
class HyperlinkConfig:
    """Hyperlink configuration."""
    enabled: bool = True
    auto_detect_urls: bool = True
    shorten_long_urls: bool = True
    url_max_length: int = 50
    
    # URL shortening service (if available)
    use_shortener: bool = False
    shorten_service_url: Optional[str] = None


@dataclass
class ResponseConfig:
    """Complete response formatting configuration."""
    formatting_level: FormattingLevel = FormattingLevel.STANDARD
    brand: BrandConfig = field(default_factory=BrandConfig)
    emoji: EmojiConfig = field(default_factory=EmojiConfig)
    markdown: MarkdownConfig = field(default_factory=MarkdownConfig)
    hyperlinks: HyperlinkConfig = field(default_factory=HyperlinkConfig)
    
    # Message-specific settings
    max_line_length: int = 400
    max_message_length: int = 4000  # WhatsApp message limit
    auto_split_long_messages: bool = True
    
    # Content settings
    use_signature: bool = True
    signature_position: str = "end"  # start, end, none
    
    # Performance
    cache_formatted_responses: bool = False
    
    def get_formatted_signature(self) -> str:
        """Get the formatted signature with brand info."""
        if not self.use_signature:
            return ""
        
        signature = self.brand.signature
        if signature and "{name}" in signature:
            signature = signature.replace("{name}", self.brand.name)
        if signature and "{tagline}" in signature:
            signature = signature.replace("{tagline}", self.brand.tagline)
            
        return signature
    
    def get_welcome_message(self) -> str:
        """Get the welcome message."""
        return f"{self.brand.logo_emoji} Hello! I'm {self.brand.name}\n\n{self.brand.tagline}\n\nHow can I help you today?"
    
    def get_help_message(self) -> str:
        """Get the help message."""
        help_text = f"💬 How can I help you?\n\n"
        
        if self.brand.support_phone:
            help_text += f"📞 Contact: {self.brand.support_phone}\n"
        if self.brand.support_email:
            help_text += f"✉️ Email: {self.brand.support_email}\n"
        if self.brand.website:
            help_text += f"🌐 Visit: {self.brand.website}"
            
        return help_text


# 🔧 Default Configuration Generator
def get_default_config(brand_name: str = "ChatBot", brand_tagline: str = "Your Smart Assistant") -> ResponseConfig:
    """
    Generate default response configuration.
    
    Args:
        brand_name: Your brand/company name
        brand_tagline: Your brand tagline
        
    Returns:
        Configured ResponseConfig instance
    """
    config = ResponseConfig(
        brand=BrandConfig(
            name=brand_name,
            tagline=brand_tagline,
            signature=f"🤖 {brand_name} | {brand_tagline}"
        )
    )
    return config


# 📁 Configuration Loading from Environment
def load_config_from_env() -> ResponseConfig:
    """Load configuration from environment variables."""
    config = ResponseConfig()
    
    # Brand configuration
    config.brand.name = os.getenv("BRAND_NAME", config.brand.name)
    config.brand.tagline = os.getenv("BRAND_TAGLINE", config.brand.tagline)
    config.brand.support_email = os.getenv("SUPPORT_EMAIL", config.brand.support_email)
    config.brand.support_phone = os.getenv("SUPPORT_PHONE", config.brand.support_phone)
    config.brand.website = os.getenv("BRAND_WEBSITE", config.brand.website)
    config.brand.logo_emoji = os.getenv("BRAND_LOGO_EMOJI", config.brand.logo_emoji)
    
    # Emoji configuration
    config.emoji.enabled = os.getenv("EMOJI_ENABLED", "true").lower() == "true"
    config.emoji.frequency = os.getenv("EMOJI_FREQUENCY", config.emoji.frequency)
    
    # Markdown configuration
    config.markdown.enabled = os.getenv("MARKDOWN_ENABLED", "true").lower() == "true"
    config.markdown.whatsapp_compatible = os.getenv("WHATSAPP_FORMATTING", "true").lower() == "true"
    
    # Hyperlink configuration
    config.hyperlinks.enabled = os.getenv("HYPERLINKS_ENABLED", "true").lower() == "true"
    config.hyperlinks.auto_detect_urls = os.getenv("AUTO_DETECT_URLS", "true").lower() == "true"
    
    # Formatting level
    level_mapping = {
        "minimal": FormattingLevel.MINIMAL,
        "standard": FormattingLevel.STANDARD,
        "rich": FormattingLevel.RICH
    }
    level = os.getenv("FORMATTING_LEVEL", "standard").lower()
    config.formatting_level = level_mapping.get(level, FormattingLevel.STANDARD)
    
    return config


# 🎨 Template-based Response Generator
class TemplateManager:
    """
    Manage and render response templates with variable substitution.
    """
    
    def __init__(self, config: Optional[ResponseConfig] = None):
        self.config = config or load_config_from_env()
        self.templates: Dict[str, str] = {}
        self._load_default_templates()
    
    def _load_default_templates(self):
        """Load default response templates."""
        self.templates = {
            "welcome": self._get_welcome_template(),
            "help": self._get_help_template(),
            "goodbye": "👋 Thank you for chatting with us! Have a great day!",
            "error": "❌ We encountered an issue. Please try again or contact support.",
            "not_understood": "❓ I didn't understand that. Could you please rephrase or ask something else?",
            "thanks": "🙏 You're welcome! Is there anything else I can help you with?",
            "loading": "⏳ Please wait while I look that up for you...",
            "timeout": "⏰ I'm taking longer than usual. Please hold on...",
            "rate_limit": "⏸️ Too many requests. Please wait a moment and try again.",
            "session_end": "🌙 Our conversation has ended. Feel free to start a new chat anytime!",
        }
    
    def _get_welcome_template(self) -> str:
        """Get customized welcome template."""
        brand = self.config.brand
        if brand.website:
            return f"{brand.logo_emoji} Welcome to {brand.name}!\n\n{brand.tagline}\n\nVisit us: {brand.website}\n\nHow can I assist you today?"
        else:
            return f"{brand.logo_emoji} Welcome to {brand.name}!\n\n{brand.tagline}\n\nHow can I assist you today?"
    
    def _get_help_template(self) -> str:
        """Get customized help template."""
        brand = self.config.brand
        help_text = f"💬 How can I help you?\n\n"
        
        if brand.support_phone:
            help_text += f"📞 Contact: {brand.support_phone}\n"
        if brand.support_email:
            help_text += f"✉️ Email: {brand.support_email}\n"
        if brand.website:
            help_text += f"🌐 Website: {brand.website}\n"
            
        help_text += "\n🤔 Try asking about our products, pricing, or services!"
        return help_text
    
    def add_template(self, name: str, template: str):
        """Add a custom template."""
        self.templates[name] = template
    
    def render(self, template_name: str, **context) -> str:
        """
        Render a template with context variables.
        
        Args:
            template_name: Name of the template
            **context: Variables to substitute in the template
            
        Returns:
            Rendered template string
        """
        template = self.templates.get(template_name, "")
        return template.format(**context)
    
    def render_welcome(self, visitor_name: str = "") -> str:
        """Render a welcome message."""
        template = self.templates.get("welcome", "")
        if visitor_name:
            template = template.replace("Welcome", f"Welcome, {visitor_name}")
        return template


# 📋 Example Usage
if __name__ == "__main__":
    # Load configuration
    config = load_config_from_env()
    
    print("=== DEFAULT CONFIGURATION ===")
    print(f"Brand: {config.brand.name}")
    print(f"Tagline: {config.brand.tagline}")
    print(f"Emojis enabled: {config.emoji.enabled}")
    print(f"Formatting level: {config.formatting_level.value}")
    
    print("\n=== WELCOME MESSAGE ===")
    print(config.get_welcome_message())
    
    print("\n=== HELP MESSAGE ===") 
    print(config.get_help_message())
    
    print("\n=== TEMPLATE MANAGER ===")
    template_manager = TemplateManager(config)
    print(template_manager.render_welcome("John"))
    print(template_manager.render("goodbye"))
    print(template_manager.render("error"))