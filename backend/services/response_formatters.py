"""
🎨 Advanced Response Formatting System for WhatsApp Chatbot

This module provides sophisticated text formatting to make chatbot responses:
- ✨ Engaging and visually appealing
- 📱 WhatsApp-optimized
- 🎯 Professional and informative
- 🌐 Hyperlink-capable
- 🎭 Emoji-enhanced (without overuse)
"""

import re
import html
import urllib.parse
from typing import Dict, List, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum

import logging
logger = logging.getLogger("response_formatters")


class TextStyle(Enum):
    """Available text formatting styles for WhatsApp."""
    NORMAL = "normal"
    BOLD = "bold"
    ITALIC = "italic"
    STRIKETHROUGH = "strikethrough"
    MONOSPACE = "monospace"
    BOLD_ITALIC = "bold_italic"


class MessageType(Enum):
    """Types of messages for context-aware formatting."""
    GREETING = "greeting"
    FAQ_ANSWER = "faq_answer"
    PRODUCT_INFO = "product_info"
    ORDER_CONFIRMATION = "order_confirmation"
    PRICE_QUERY = "price_query"
    SUPPORT_RESPONSE = "support_response"
    ERROR_MESSAGE = "error_message"
    LISTING = "listing"
    INSTRUCTIONS = "instructions"


@dataclass
class FormattingOptions:
    """Configuration for response formatting."""
    use_emojis: bool = True
    use_markdown: bool = True
    use_hyperlinks: bool = True
    use_line_breaks: bool = True
    max_line_length: int = 400
    bullet_style: str = "•"  # Options: •, - , *, ◦, ▪
    separator_style: str = "─"
    signature: str = ""
    brand_name: str = "ChatBot"
    
    # Emoji frequency: "none", "minimal", "moderate", "liberal"
    emoji_frequency: str = "moderate"
    
    # WhatsApp formatting support
    whatsapp_format_support: bool = True


# 🌈 Emoji Mapping Database
EMOJI_CATEGORIES = {
    "greetings": ["👋", "👥", "🌟", "✨", "🌞", "🌙"],
    "thanks": ["🙏", "🤝", "💙", "❤️", "🌈", "🎉"],
    "products": ["📦", "🛍️", "👕", "📱", "🔋", "💎", "✨"],
    "pricing": ["💰", "💵", "💳", "💼", "🏷️", "🧾"],
    "orders": ["📋", "📝", "🛒", "📦", "🚚", "📅", "✅"],
    "support": ["❓", "❔", "🆘", "🚨", "💬", "📞", "👨‍💻"],
    "success": ["✅", "🎉", "👍", "🌟", "🚀", "💯"],
    "error": ["❌", "⚠️", "❗", "🚫", "💥"],
    "warning": ["⚠️", "⚡", "❗", "🚨", "🔥"],
    "info": ["ℹ️", "📊", "📈", "🔍", "📋", "🏷️"],
    " acquisitions": ["🎁", "🛒", "💎", "✨", "🏆"],
    "delivery": ["🚚", "📦", "🗺️", "🏠", "📍", "⏰"],
    "payment": ["💳", "💰", "💵", "🏦", "🪙", "💼"],
    "knowledge": ["🧠", "📚", "🔍", "💡", "🌐", "📝"],
    "question": ["❓", "❔", "❕", "❗", "🤔", "💭"],
    "time": ["⏰", "⏳", "⏱️", "⏸️", "⏩", "⏪"],
    "los": ["🔗", "🌐", "🔽", "🔼", "👆", "👇"],
    "numbers": ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"],
}

# 🎯 Context Emoji Mapping for Smart Emoji Selection
CONTEXT_EMOJIS = {
    # Greetings
    "hello": EMOJI_CATEGORIES["greetings"],
    "hi": EMOJI_CATEGORIES["greetings"],
    "hey": EMOJI_CATEGORIES["greetings"],
    "welcome": EMOJI_CATEGORIES["greetings"],
    
    # Thanks
    "thank": EMOJI_CATEGORIES["thanks"],
    "thanks": EMOJI_CATEGORIES["thanks"],
    "appreciate": EMOJI_CATEGORIES["thanks"],
    
    # Products
    "product": EMOJI_CATEGORIES["products"],
    "item": EMOJI_CATEGORIES["products"],
    "catalog": EMOJI_CATEGORIES["products"],
    "shop": EMOJI_CATEGORIES["products"],
    
    # Orders
    "order": EMOJI_CATEGORIES["orders"],
    "purchase": EMOJI_CATEGORIES["orders"],
    "buy": EMOJI_CATEGORIES["orders"],
    "cart": EMOJI_CATEGORIES["orders"],
    
    # Pricing
    "price": EMOJI_CATEGORIES["pricing"],
    "cost": EMOJI_CATEGORIES["pricing"],
    "rate": EMOJI_CATEGORIES["pricing"],
    "payment": EMOJI_CATEGORIES["payment"],
    
    # Support
    "help": EMOJI_CATEGORIES["support"],
    "support": EMOJI_CATEGORIES["support"],
    "question": EMOJI_CATEGORIES["question"],
    "issue": EMOJI_CATEGORIES["support"],
}


class WhatsAppFormatter:
    """
    Advanced WhatsApp Message Formatter
    
    Supports:
    - Bold (*text*), Italic (_text_), Strikethrough (~text~)
    - Monospace (```text```)
    - Lists and bullet points
    - Hyperlinks (WhatsApp supports clickable links)
    - Emojis with context-aware selection
    - Code blocks and structured data
    - Signatures and branding
    """
    
    def __init__(self, options: Optional[FormattingOptions] = None):
        self.options = options or FormattingOptions()
        
    def format(self, text: str, message_type: MessageType = MessageType.FAQ_ANSWER, 
               context: Optional[Dict] = None) -> str:
        """
        Master formatting method that applies all formattings.
        
        Args:
            text: Raw text to format
            message_type: Type of message for context-aware formatting
            context: Additional context for smart formatting
            
        Returns:
            Formatted, WhatsApp-optimized text
        """
        if not text:
            return ""
            
        # Step 1: Clean and normalize text
        formatted = self._clean_text(text)
        
        # Step 2: Context-aware preprocessing
        formatted = self._preprocess_by_type(formatted, message_type, context)
        
        # Step 3: Apply markdown formatting
        formatted = self._apply_markdown(formatted)
        
        # Step 4: Add emojis based on context
        if self.options.use_emojis:
            formatted = self._add_context_emojis(formatted, message_type, context)
        
        # Step 5: Fix line breaks and paragraph structure
        formatted = self._fix_line_breaks(formatted)
        
        # Step 6: Ensure proper length and structure
        formatted = self._ensure_proper_structure(formatted)
        
        # Step 7: Add signature if configured
        if self.options.signature:
            formatted = self._add_signature(formatted)
            
        return formatted
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize the raw text."""
        # Remove excessive whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Trim each line
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines).strip()
        
        return text
    
    def _preprocess_by_type(self, text: str, message_type: MessageType, 
                           context: Optional[Dict]) -> str:
        """Apply type-specific preprocessing."""
        
        preprocessing_map = {
            MessageType.GREETING: self._format_greeting,
            MessageType.FAQ_ANSWER: self._format_faq_answer,
            MessageType.PRODUCT_INFO: self._format_product_info,
            MessageType.ORDER_CONFIRMATION: self._format_order_confirmation,
            MessageType.PRICE_QUERY: self._format_price_query,
            MessageType.SUPPORT_RESPONSE: self._format_support_response,
            MessageType.ERROR_MESSAGE: self._format_error_message,
            MessageType.LISTING: self._format_listing,
            MessageType.INSTRUCTIONS: self._format_instructions,
        }
        
        preprocessor = preprocessing_map.get(message_type, self._format_generic)
        return preprocessor(text, context or {})
    
    def _format_greeting(self, text: str, context: Dict) -> str:
        """Format greeting messages."""
        # Add greeting emoji
        greeting_emojis = EMOJI_CATEGORIES.get("greetings", ["👋"])
        if not text.startswith(tuple(greeting_emojis)):
            text = f"{greeting_emojis[0]} {text}"
        return text
    
    def _format_faq_answer(self, text: str, context: Dict) -> str:
        """Format FAQ answers."""
        # Add knowledge emoji at the beginning
        if self.options.use_emojis:
            knowledge_emoji = EMOJI_CATEGORIES.get("knowledge", ["💡"])[0]
            if not text.startswith(knowledge_emoji) and len(text) > 20:
                text = f"{knowledge_emoji} {text}"
        return text
    
    def _format_product_info(self, text: str, context: Dict) -> str:
        """Format product information."""
        # Add product emoji
        if self.options.use_emojis:
            product_emoji = EMOJI_CATEGORIES.get("products", ["📦"])[0]
            if not text.startswith(product_emoji):
                text = f"{product_emoji} {text}"
        return text
    
    def _format_order_confirmation(self, text: str, context: Dict) -> str:
        """Format order confirmations."""
        if self.options.use_emojis:
            success_emoji = EMOJI_CATEGORIES.get("success", ["✅"])[0]
            if not text.startswith(success_emoji):
                text = f"{success_emoji} {text}"
        return text
    
    def _format_price_query(self, text: str, context: Dict) -> str:
        """Format price responses."""
        if self.options.use_emojis:
            pricing_emoji = EMOJI_CATEGORIES.get("pricing", ["💰"])[0]
            if not text.startswith(pricing_emoji):
                text = f"{pricing_emoji} {text}"
        return text
    
    def _format_support_response(self, text: str, context: Dict) -> str:
        """Format support responses."""
        if self.options.use_emojis:
            support_emoji = EMOJI_CATEGORIES.get("support", ["💬"])[0]
            if not text.startswith(support_emoji):
                text = f"{support_emoji} {text}"
        return text
    
    def _format_error_message(self, text: str, context: Dict) -> str:
        """Format error messages."""
        if self.options.use_emojis:
            error_emoji = EMOJI_CATEGORIES.get("error", ["⚠️"])[0]
            if not text.startswith(error_emoji):
                text = f"{error_emoji} {text}"
        return text
    
    def _format_listing(self, text: str, context: Dict) -> str:
        """Format listings and catalogs."""
        # Ensure proper bullet formatting
        text = self._format_bullets(text)
        return text
    
    def _format_instructions(self, text: str, context: Dict) -> str:
        """Format step-by-step instructions."""
        # Add numbered emojis to steps
        text = self._number_steps(text)
        return text
    
    def _format_generic(self, text: str, context: Dict) -> str:
        """Default formatting."""
        return text
    
    def _apply_markdown(self, text: str) -> str:
        """Apply WhatsApp-compatible markdown formatting."""
        if not self.options.use_markdown or not self.options.whatsapp_format_support:
            return text
            
        # Apply markdown replacements
        replacements = [
            # Bold
            (r'\*\*(.+?)\*\*', r'*\1*'),
            (r'__([^_]+)__', r'*\1*'),
            
            # NOTE: no *x* / _x_ transforms. WhatsApp already renders *x* as
            # bold and _x_ as italic, and the bold rule above emits *x* —
            # re-matching it here used to rewrite it to \_x\_, a literal
            # backslash-underscore pair that clients display verbatim.
            
            # Strikethrough
            (r'~~(.+?)~~', r'~\1~'),
            
            # Bold + Italic
            (r'\*\*\*(.+?)\*\*\*', r'*_\1_*'),
        ]
        
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text)
            
        return text
    
    def _add_context_emojis(self, text: str, message_type: MessageType, 
                           context: Dict) -> str:
        """Add emojis based on message context."""
        # Don't add if already has emojis
        if self._has_emojis(text) and self.options.emoji_frequency != "liberal":
            return text
            
        # Get context-specific emoji
        emoji_map = {
            MessageType.GREETING: "greetings",
            MessageType.FAQ_ANSWER: "info", 
            MessageType.PRODUCT_INFO: "products",
            MessageType.ORDER_CONFIRMATION: "success",
            MessageType.PRICE_QUERY: "pricing",
            MessageType.SUPPORT_RESPONSE: "support",
            MessageType.ERROR_MESSAGE: "error",
            MessageType.LISTING: "products",
            MessageType.INSTRUCTIONS: "info",
        }
        
        category = emoji_map.get(message_type, "info")
        emojis = EMOJI_CATEGORIES.get(category, EMOJI_CATEGORIES["info"])
        
        if emojis and not self._has_emojis(text):
            emoji = emojis[0]
            # Add emoji at the beginning if it's an appropriate context
            appropriate_starts = [MessageType.GREETING, MessageType.SUPPORT_RESPONSE, 
                               MessageType.ORDER_CONFIRMATION, MessageType.ERROR_MESSAGE]
            if message_type in appropriate_starts:
                text = f"{emoji} {text}"
        
        return text
    
    def _has_emojis(self, text: str) -> bool:
        """Check if text already contains emojis."""
        # Simple check for common emoji patterns
        emoji_pattern = re.compile("[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002702\U00002705\U0000270A-\U0000270D\U00002640\U00002642\U00002600-\U000026FF\U00002B50\U000023F0-\U000023F3\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002640\U00002642\U0001F004\U0001F0CF\U0001F18E\U0001F191-\U0001F251]+")
        return bool(emoji_pattern.search(text))
    
    def _fix_line_breaks(self, text: str) -> str:
        """Fix line breaks and paragraph structure."""
        lines = text.split('\n')
        formatted_lines = []
        
        for line in lines:
            stripped = line.strip()
            if stripped:  # Non-empty line
                formatted_lines.append(stripped)
            else:  # Empty line - add single newline
                if formatted_lines and formatted_lines[-1] != '':
                    formatted_lines.append('')
        
        # Ensure we don't have more than 2 consecutive newlines
        result = '\n'.join(formatted_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result
    
    def _ensure_proper_structure(self, text: str) -> str:
        """Ensure proper message structure."""
        # Remove trailing whitespace and newlines
        text = text.strip()
        
        # Add final newline if missing
        if not text.endswith('\n'):
            text += '\n'
            
        return text
    
    def _add_signature(self, text: str) -> str:
        """Add signature to the message."""
        if not self.options.signature:
            return text
            
        # Add separator and signature
        separator = "─" * min(len(self.options.signature) + 4, 20)
        signature_text = f"\n\n{separator}\n{self.options.signature}"
        
        return text.rstrip() + signature_text
    
    def _format_bullets(self, text: str) -> str:
        """Format bullet points properly."""
        lines = text.split('\n')
        formatted_lines = []
        
        for line in lines:
            stripped = line.strip()
            if stripped:
                # Check if line starts with bullet markers
                bullet_markers = ['•', '-', '*', '◦', '▪', '·', '']
                starts_with_bullet = any(stripped.startswith(marker) for marker in bullet_markers)
                
                if starts_with_bullet:
                    # Standardize bullet style
                    bullet = self.options.bullet_style
                    content = stripped[1:].strip()  # Remove existing bullet
                    formatted_lines.append(f"{bullet} {content}")
                else:
                    formatted_lines.append(stripped)
            else:
                formatted_lines.append('')
                
        return '\n'.join(formatted_lines)
    
    def _number_steps(self, text: str) -> str:
        """Add numbers to step-by-step instructions."""
        lines = text.split('\n')
        numbered_lines = []
        step_count = 0
        
        for line in lines:
            stripped = line.strip()
            if stripped:
                # Check for step patterns
                step_patterns = [
                    r'^step [0-9]+:', r'^step ([0-9]+):',
                    r'^[0-9]+\.', r'^\- ', r'^• ', r'^\* '
                ]
                
                is_step = any(re.match(pattern, stripped, re.IGNORECASE) for pattern in step_patterns)
                
                if is_step:
                    step_count += 1
                    if step_count <= 9:
                        emoji_number = EMOJI_CATEGORIES["numbers"][step_count - 1]
                        content = re.sub(r'^(step [0-9]+:|[0-9]+\.|\- |• |\* )', '', stripped, flags=re.IGNORECASE).strip()
                        numbered_lines.append(f"{emoji_number} {content}")
                    else:
                        clean_content = re.sub(r'^(step [0-9]+:|[0-9]+\.|\- |• |\* )', '', stripped, flags=re.IGNORECASE).strip()
                        numbered_lines.append(f"{step_count}. {clean_content}")
                else:
                    numbered_lines.append(stripped)
            else:
                numbered_lines.append('')
                
        return '\n'.join(numbered_lines)


class HyperlinkFormatter:
    """
    Hyperlink Support for WhatsApp Messages
    
    WhatsApp supports clickable hyperlinks. This formatter:
    - Detects and enhances URLs
    - Shortens long URLs
    - Adds descriptive text
    - Ensures clickable format
    """
    
    def __init__(self):
        self.url_pattern = re.compile(
            r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[\w\-._~:/?#[\]@!$&\(\)\*\+,;=]*'
        )
    
    def format_urls(self, text: str) -> str:
        """
        Format URLs in text to be more readable and clickable.
        
        WhatsApp automatically makes URLs clickable, but we can:
        - Shorten very long URLs
        - Add context around links
        - Ensure proper spacing
        """
        def replace_url(match):
            url = match.group(0)
            
            # Shorten very long URLs
            if len(url) > 50:
                try:
                    # Try to extract domain
                    parsed = urllib.parse.urlparse(url)
                    domain = parsed.netloc.replace('www.', '')
                    
                    # Create shortened version with context
                    if parsed.path and len(parsed.path) > 1:
                        path_parts = parsed.path.split('/')[1:3]  # Take first 2 path parts
                        path_hint = '/'.join(path_parts) if path_parts else ''
                        short_url = f"{domain}{path_hint}" if path_hint else domain
                    else:
                        short_url = domain
                    
                    # Add hyperlink formatting
                    return f"[{short_url}]({url})"
                except:
                    return url
            else:
                # Ensure proper spacing around URLs
                return url
                
        return self.url_pattern.sub(replace_url, text)
    
    def create_link(self, text: str, url: str) -> str:
        """Create a clickable link with descriptive text."""
        return f"[{text}]({url})"
    
    def format_contact_links(self, text: str, phone: str, name: str = "Us") -> str:
        """Format phone number as clickable WhatsApp link."""
        # Create WhatsApp direct chat link
        whatsapp_url = f"https://wa.me/{phone.replace('+', '').replace(' ', '')}"
        link_text = f"[{name} on WhatsApp]({whatsapp_url})"
        
        # Replace phone numbers in text with clickable links
        phone_pattern = re.compile(r'(\+?[0-9\-\s]{10,15})')
        def replace_phone(match):
            phone_number = match.group(1).replace(' ', '').replace('-', '')
            wa_url = f"https://wa.me/{phone_number.replace('+', '')}"
            return f"[Chat]({wa_url})"
        
        text = phone_pattern.sub(replace_phone, text)
        text = text.replace(phone, link_text)
        
        return text


class ResponseComposer:
    """
    High-level Response Composer
    
    Combines all formatting capabilities into a simple interface
    for generating well-formatted responses.
    """
    
    def __init__(self, options: Optional[FormattingOptions] = None):
        self.formatter = WhatsAppFormatter(options)
        self.hyperlink_formatter = HyperlinkFormatter()
    
    def compose(self, text: str, message_type: MessageType = MessageType.FAQ_ANSWER,
               context: Optional[Dict] = None, links: Optional[Dict[str, str]] = None) -> str:
        """
        Compose a complete, well-formatted response.
        
        Args:
            text: Raw response text
            message_type: Type of message
            context: Additional context data
            links: Dictionary of {display_text: url} for hyperlink replacements
            
        Returns:
            Fully formatted response ready for WhatsApp
        """
        # Apply basic formatting
        formatted = self.formatter.format(text, message_type, context)
        
        # Apply hyperlink formatting
        formatted = self.hyperlink_formatter.format_urls(formatted)
        
        # Replace any specified links
        if links:
            for display, url in links.items():
                formatted = formatted.replace(display, f"[{display}]({url})")
        
        return formatted
    
    def create_greeting(self, name: str = None, time_of_day: str = None) -> str:
        """Create a personalized greeting."""
        greetings = {
            "morning": "Good morning",
            "afternoon": "Good afternoon", 
            "evening": "Good evening",
            "night": "Good night"
        }
        
        if time_of_day and time_of_day in greetings:
            greeting = f"{greetings[time_of_day]}, {name or 'there'}!"
        else:
            greeting = f"Hello, {name or 'there'}!"
        
        return self.compose(greeting, MessageType.GREETING)
    
    def create_product_response(self, product_data: Dict) -> str:
        """Create a product information response."""
        name = product_data.get('name', 'This product')
        price = product_data.get('price', 'Price on request')
        description = product_data.get('description', 'No description available')
        
        response = f"{name}\n\nPrice: ₹{price}\n\n{description}"
        return self.compose(response, MessageType.PRODUCT_INFO)
    
    def create_order_confirmation(self, order_data: Dict) -> str:
        """Create an order confirmation response."""
        order_number = order_data.get('order_number', '#ORDER123')
        items = order_data.get('items', []) 
        total = order_data.get('total_amount', '0')
        
        items_text = "\n".join([f"• {item.get('name', 'Item')}: ₹{item.get('price', '0')}" 
                             for item in items]) if items else "No items"
        
        response = f"Order Confirmed! 🎉\n\nOrder #{order_number}\n\n{items_text}\n\nTotal: ₹{total}"
        return self.compose(response, MessageType.ORDER_CONFIRMATION)
    
    def create_error_response(self, error: str, suggestion: str = None) -> str:
        """Create an error response."""
        response = f"Apologies, {error}."
        if suggestion:
            response += f"\n\n{suggestion}"
        return self.compose(response, MessageType.ERROR_MESSAGE, {"error": error})


# 🎨 Predefined Templates for Common Scenarios
RESPONSE_TEMPLATES = {
    "welcome": {
        "text": "Hello and welcome! 👋 I'm {brand_name}, your AI assistant. \n\nHow can I help you today?",
        "type": MessageType.GREETING
    },
    
    "thanks": {
        "text": "You're welcome! 🙏 Is there anything else I can help you with?",
        "type": MessageType.SUPPORT_RESPONSE
    },
    
    "product_not_found": {
        "text": "I couldn't find that product. ⚠️ Would you like to see our catalog?",
        "type": MessageType.ERROR_MESSAGE
    },
    
    "order_success": {
        "text": "Order received! ✅ Your order #{order_id} has been confirmed.\n\nYou'll receive updates on WhatsApp.",
        "type": MessageType.ORDER_CONFIRMATION
    },
    
    "price_query": {
        "text": "💰 Current price: ₹{price}\n\n{details}",
        "type": MessageType.PRICE_QUERY
    },
    
    "contact_support": {
        "text": "Need help? 💬 Contact our support team at {support_phone} or email {support_email}",
        "type": MessageType.SUPPORT_RESPONSE
    }
}


# 🎯 Smart Formatting Utilities

def smart_format(text: str, message_type: MessageType = MessageType.FAQ_ANSWER) -> str:
    """Quick smart formatting for any text."""
    composer = ResponseComposer()
    return composer.compose(text, message_type)


def add_emoji_for_context(text: str, context: str) -> str:
    """Add appropriate emoji based on context."""
    context = context.lower()
    emoji_map = {
        "greeting": "👋",
        "thanks": "🙏", 
        "success": "✅",
        "error": "⚠️",
        "product": "📦",
        "order": "📋",
        "price": "💰",
        "support": "💬",
        "question": "❓",
        "info": "ℹ️"
    }
    
    if context in emoji_map:
        emoji = emoji_map[context]
        if not text.startswith(emoji):
            text = f"{emoji} {text}"
    
    return text


def create_clickable_link(text: str, url: str) -> str:
    """Create a clickable hyperlink."""
    formatter = HyperlinkFormatter()
    return formatter.create_link(text, url)


def format_contact_info(phone: str, name: str = "Us") -> str:
    """Format a phone number as clickable WhatsApp link."""
    formatter = HyperlinkFormatter()
    return formatter.format_contact_links(name, phone)


if __name__ == "__main__":
    # Demo usage
    composer = ResponseComposer()
    
    # Example 1: Simple greeting
    print("=== GREETING ===")
    print(composer.create_greeting("John", "morning"))
    
    # Example 2: Product response
    print("\n=== PRODUCT ===")
    product = {
        'name': 'Premium Headphones',
        'price': '1999',
        'description': 'Noise-cancelling Bluetooth headphones with 30-hour battery life'
    }
    print(composer.create_product_response(product))
    
    # Example 3: Order confirmation
    print("\n=== ORDER ===")
    order = {
        'order_number': 'ORD789',
        'items': [
            {'name': 'Headphones', 'price': '1999'},
            {'name': 'Charging Cable', 'price': '299'}
        ],
        'total_amount': '2298'
    }
    print(composer.create_order_confirmation(order))
    
    # Example 4: URL formatting
    print("\n=== LINKS ===")
    formatter = HyperlinkFormatter()
    text_with_url = "Visit our website at https://www.example.com/products/headphones?ref=chatbot123 for more details"
    print(formatter.format_urls(text_with_url))