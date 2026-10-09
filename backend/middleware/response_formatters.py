"""
🌟 Response Formatting Middleware

This middleware automatically applies enhanced formatting to all chatbot responses,
ensuring consistent, engaging, and professional messages across your entire system.
"""

import re
import logging
from functools import wraps
from typing import Callable, Any
from fastapi import Request

# Import response formatter
try:
    from services.response_formatters import WhatsAppFormatter, MessageType, smart_format
    RESPONSE_FORMATTER_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Response formatter not available: {e}")
    RESPONSE_FORMATTER_AVAILABLE = False

logger = logging.getLogger("response_formatters_middleware")


class ResponseFormatterMiddleware:
    """
    FastAPI Middleware for Response Formatting
    
    This middleware intercepts all responses and applies formatting to text content
    before it's sent to the user. It's smart about detecting which fields contain
    user-facing text that should be formatted.
    """
    
    TEXT_FIELDS = [
        "answer", "response", "message", "text", "content", 
        "description", "body", "caption", "payload"
    ]
    
    EXCLUDED_ROUTES = [
        "/api/admin", "/api/auth", "/api/status", 
        "/docs", "/openapi.json",  "/redoc"
    ]
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, request: Request, call_next):
        """Process request and format response."""
        response = await call_next(request)
        
        # Skip formatting for excluded routes
        if any(request.url.path.startswith(route) for route in self.EXCLUDED_ROUTES):
            return response
        
        # Only format JSON responses
        if response.media_type != "application/json":
            return response
        
        # Get the response body if it's already been generated
        try:
            response_body = response.body
            if response_body:
                # Parse and format the JSON
                import json
                data = json.loads(response_body)
                formatted_data = self._format_response_data(data)
                
                # Recreate response with formatted data
                response.body = json.dumps(formatted_data).encode()
                response.headers["Content-Length"] = str(len(response.body))
        except Exception as e:
            logger.debug(f"Response formatting middleware error: {e}")
        
        return response
    
    def _format_response_data(self, data: dict) -> dict:
        """Format all text fields in response data."""
        if isinstance(data, dict):
            formatted = {}
            for key, value in data.items():
                if self._should_format_field(key) and isinstance(value, str):
                    formatted[key] = self._format_text(value, key)
                else:
                    formatted[key] = self._format_response_data(value) if isinstance(value, (dict, list)) else value
            return formatted
        elif isinstance(data, list):
            return [self._format_response_data(item) for item in data]
        else:
            return data
    
    def _should_format_field(self, field_name: str) -> bool:
        """Check if a field should be formatted."""
        field_lower = field_name.lower()
        return any(text_field in field_lower for text_field in self.TEXT_FIELDS)
    
    def _format_text(self, text: str, field_name: str) -> str:
        """Format text based on field name."""
        if not text or not text.strip():
            return text
        
        # Determine message type based on field name
        message_type = self._get_message_type(field_name)
        
        if RESPONSE_FORMATTER_AVAILABLE:
            try:
                formatter = WhatsAppFormatter()
                return formatter.format(text, message_type=message_type)
            except Exception as e:
                logger.debug(f"Enhanced formatting failed: {e}")
        
        # Fallback to basic formatting
        return self._basic_format(text)
    
    def _get_message_type(self, field_name: str) -> MessageType:
        """Determine message type based on field name."""
        if not RESPONSE_FORMATTER_AVAILABLE:
            return None
        
        field_lower = field_name.lower()
        
        type_mapping = {
            "greeting": MessageType.GREETING,
            "welcome": MessageType.GREETING,
            "answer": MessageType.FAQ_ANSWER,
            "response": MessageType.FAQ_ANSWER,
            "message": MessageType.FAQ_ANSWER,
            "product": MessageType.PRODUCT_INFO,
            "item": MessageType.PRODUCT_INFO,
            "description": MessageType.PRODUCT_INFO,
            "price": MessageType.PRICE_QUERY,
            "cost": MessageType.PRICE_QUERY,
            "rate": MessageType.PRICE_QUERY,
            "order": MessageType.ORDER_CONFIRMATION,
            "purchase": MessageType.ORDER_CONFIRMATION,
            "thanks": MessageType.SUPPORT_RESPONSE,
            "thank": MessageType.SUPPORT_RESPONSE,
            "support": MessageType.SUPPORT_RESPONSE,
            "error": MessageType.ERROR_MESSAGE,
            "warning": MessageType.ERROR_MESSAGE,
        }
        
        for field_pattern, msg_type in type_mapping.items():
            if field_pattern in field_lower:
                return msg_type
        
        return MessageType.FAQ_ANSWER
    
    def _basic_format(self, text: str) -> str:
        """Basic text formatting."""
        # Fix bullet points
        bullet = "•"
        text = re.sub(r"(?<!^)(?<!\n)[ \t]*" + bullet + r"[ \t]*", "\n" + bullet + " ", text, flags=re.MULTILINE)
        
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Trim trailing whitespace on each line
        text = "\n".join(line.rstrip() for line in text.splitlines())
        
        return text.strip()


def format_response_answer(func: Callable) -> Callable:
    """
    Decorator to automatically format the 'answer' field in responses.
    
    Usage:
        @format_response_answer
        async def my_endpoint():
            return {"answer": "Hello, this will be formatted beautifully!"}
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        
        # Check if result is a dict with 'answer' field
        if isinstance(result, dict) and "answer" in result:
            answer = result.get("answer", "")
            if answer and isinstance(answer, str):
                if RESPONSE_FORMATTER_AVAILABLE:
                    try:
                        formatter = WhatsAppFormatter()
                        result["answer"] = formatter.format(answer, MessageType.FAQ_ANSWER)
                    except Exception as e:
                        logger.debug(f"Response formatting failed: {e}")
                else:
                    # Basic formatting
                    result["answer"] = _basic_format(answer)
        
        return result
    
    return wrapper


def format_all_text_fields(func: Callable) -> Callable:
    """
    Decorator to format all text fields in the response.
    
    Usage:
        @format_all_text_fields
        async def my_endpoint():
            return {"answer": "Hello", "description": "This will be formatted"}
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        
        if isinstance(result, dict):
            result = _format_dict_text_fields(result)
        
        return result
    
    return wrapper


def _basic_format(text: str) -> str:
    """Basic text formatting."""
    if not text:
        return text or ""
    
    # Fix bullet points
    bullet = "•"
    text = re.sub(r"(?<!^)(?<!\n)[ \t]*" + bullet + r"[ \t]*", "\n" + bullet + " ", text, flags=re.MULTILINE)
    
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Trim trailing whitespace on each line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    
    return text.strip()


def _format_dict_text_fields(data: Any) -> Any:
    """Format all text fields in a dictionary or list."""
    TEXT_FIELDS = ["answer", "response", "message", "text", "content", "description", "body"]
    
    if isinstance(data, dict):
        formatted = {}
        for key, value in data.items():
            if any(field in key.lower() for field in TEXT_FIELDS) and isinstance(value, str):
                if RESPONSE_FORMATTER_AVAILABLE:
                    try:
                        formatter = WhatsAppFormatter()
                        formatted[key] = formatter.format(value, MessageType.FAQ_ANSWER)
                    except Exception:
                        formatted[key] = _basic_format(value)
                else:
                    formatted[key] = _basic_format(value)
            else:
                formatted[key] = _format_dict_text_fields(value) if isinstance(value, (dict, list)) else value
        return formatted
    elif isinstance(data, list):
        return [_format_dict_text_fields(item) for item in data]
    else:
        return data


# 🎯 Create the middleware for FastAPI app

def add_response_formatting_middleware(app):
    """
    Add response formatting middleware to a FastAPI app.
    
    Usage:
        from middleware.response_formatters import add_response_formatting_middleware
        app = FastAPI()
        add_response_formatting_middleware(app)
    """
    app.add_middleware(ResponseFormatterMiddleware)


# 🌈 Predefined Formatting Presets

PRESET_FRIENDLY = {
    "use_emojis": True,
    "emoji_frequency": "liberal", 
    "use_markdown": True,
    "signature": "Best regards, {brand_name} 🤖"
}

PRESET_PROFESSIONAL = {
    "use_emojis": True,
    "emoji_frequency": "minimal",
    "use_markdown": True,
    "signature": "Regards, {brand_name}"
}

PRESET_MINIMAL = {
    "use_emojis": False,
    "use_markdown": True,
    "signature": ""
}

PRESET_ENGAGING = {
    "use_emojis": True,
    "emoji_frequency": "liberal",
    "use_markdown": True,
    "use_hyperlinks": True,
    "signature": "Cheers! 🎉 | {brand_name}"
}


# 🎨 Quick Formatting Functions

def quick_format(text: str, preset: str = "engaging") -> str:
    """
    Quick format text with a preset style.
    
    Args:
        text: Text to format
        preset: Formatting preset (friendly, professional, minimal, engaging)
        
    Returns:
        Formatted text
    """
    presets = {
        "friendly": PRESET_FRIENDLY,
        "professional": PRESET_PROFESSIONAL, 
        "minimal": PRESET_MINIMAL,
        "engaging": PRESET_ENGAGING
    }
    
    preset_config = presets.get(preset, PRESET_ENGAGING)
    
    if RESPONSE_FORMATTER_AVAILABLE:
        try:
            from services.response_formatters import FormattingOptions
            options = FormattingOptions(**preset_config)
            formatter = WhatsAppFormatter(options)
            return formatter.format(text, MessageType.FAQ_ANSWER)
        except Exception:
            return _basic_format(text)
    else:
        return _basic_format(text)


def format_with_emoji(text: str, emoji: str = "🎯") -> str:
    """Add emoji to text (if not already present)."""
    if not text:
        return text
    
    if text.startswith(emoji):
        return text
    
    # Check if text already starts with any emoji
    existing_emoji = re.match(r"^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002702\U00002705\U0000270A-\U0000270D\U00002640\U00002642\U0001F004\U0001F0CF\U0001F18E\U0001F191-\U0001F251]+", text)
    if existing_emoji:
        return text
    
    return f"{emoji} {text}"


def format_list(items: list, bullet: str = "•") -> str:
    """Format a list with nice bullets."""
    if not items:
        return ""
    
    formatted_items = []
    for item in items:
        if isinstance(item, dict):
            # Try to extract a displayable value
            item_text = item.get("text") or item.get("title") or item.get("name") or str(item)
        else:
            item_text = str(item)
        
        formatted_items.append(f"{bullet} {item_text}")
    
    return "\n".join(formatted_items)


def format_numbered_list(items: list) -> str:
    """Format a list with numbered emojis."""
    if not items:
        return ""
    
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    
    formatted_items = []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            item_text = item.get("text") or item.get("title") or item.get("name") or str(item)
        else:
            item_text = str(item)
        
        number_emoji = numbers[i] if i < len(numbers) else f"{i+1}."
        formatted_items.append(f"{number_emoji} {item_text}")
    
    return "\n".join(formatted_items)


if __name__ == "__main__":
    # Demo the functionality
    print("=== QUIK FORMATTING DEMO ===")
    
    # Test quick formatting
    text = "Here are our products: Headphones (₹1999), Speakers (₹2999), and Earbuds (₹999)"
    print("Original:", text)
    print("Formatted:", quick_format(text))
    
    print("\n=== LIST FORMATTING ===")
    items = [
        {"name": "Premium Headphones", "price": "₹1999"},
        {"name": "Bluetooth Speaker", "price": "₹2999"},
        {"name": "Wireless Earbuds", "price": "₹999"}
    ]
    print(format_list(items))
    
    print("\n=== NUMBERED LIST ===")
    steps = ["Select a product", "Add to cart", "Checkout", "Confirm order"]
    print(format_numbered_list(steps))