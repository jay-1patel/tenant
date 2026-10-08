"""
Generic Button Registry for Multi-Domain Support Chatbot

This module provides a dynamic button registry that adapts to different
company types (IT, Food, E-commerce, Manufacturing, Healthcare, etc.)

Usage:
    from routing.button_registry import button_registry
    
    # Get all buttons for current company type
    buttons = button_registry.get_buttons_for_type()
    
    # Get buttons for specific company type
    it_buttons = button_registry.get_buttons_for_type('it')
    
    # Get button by ID
    button = button_registry.get_button('contact_support')
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set


class ButtonRegistry:
    """
    Dynamic button registry that supports multiple company types.
    
    The registry can be configured via:
    1. Environment variables (COMPANY_TYPE, DOMAIN, INDUSTRY)
    2. JSON configuration file (default: routing/button_registry.json)
    3. Programmatic registration via register_button()
    """
    
    def __init__(self):
        """Initialize the button registry."""
        self.registry: Dict[str, Dict] = {}
        self.company_type: str = "generic"
        self.domain: str = "support"
        self.industry: str = "technology"
        self._loaded: bool = False
        
        # Load configuration
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from environment and JSON file."""
        if self._loaded:
            return
        
        # Load from environment
        self.company_type = os.getenv("COMPANY_TYPE", "generic").lower()
        self.domain = os.getenv("DOMAIN", "support").lower()
        self.industry = os.getenv("INDUSTRY", "technology").lower()
        
        # Load from JSON file
        json_path = os.getenv("BUTTON_REGISTRY_FILE", 
                              str(Path(__file__).parent / "button_registry.json"))
        self._load_from_json(json_path)
        
        # Load defaults if registry is empty
        if not self.registry:
            self._load_defaults()
        
        self._loaded = True
    
    def _load_from_json(self, filepath: str) -> None:
        """Load button registry from JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.registry = data.get('buttons', {})
                
                # Override with file settings if present
                if 'company_type' in data:
                    self.company_type = data['company_type']
                if 'domain' in data:
                    self.domain = data['domain']
                if 'industry' in data:
                    self.industry = data['industry']
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            # File doesn't exist or is invalid - will use defaults
            pass
    
    def _load_defaults(self) -> None:
        """Load default generic buttons."""
        self.registry = {
            # Universal buttons for any company
            'main_menu': {
                'id': 'main_menu',
                'title': 'Main Menu',
                'action': 'show_main_menu',
                'category': 'navigation',
                'description': 'Return to main menu',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'contact_support': {
                'id': 'contact_support',
                'title': 'Contact Support',
                'action': 'contact_support',
                'category': 'support',
                'description': 'Get help from support team',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'faq': {
                'id': 'faq',
                'title': 'FAQ',
                'action': 'show_faq',
                'category': 'information',
                'description': 'View frequently asked questions',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'about_us': {
                'id': 'about_us',
                'title': 'About Us',
                'action': 'show_about',
                'category': 'information',
                'description': 'Learn about our company',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            
            # IT/Technology-specific buttons
            'it_services': {
                'id': 'it_services',
                'title': 'IT Services',
                'action': 'show_it_services',
                'category': 'services',
                'description': 'View our IT service offerings',
                'applicable': ['it', 'technology', 'software']
            },
            'technical_support': {
                'id': 'technical_support',
                'title': 'Technical Support',
                'action': 'technical_support',
                'category': 'support',
                'description': 'Get technical assistance',
                'applicable': ['it', 'technology', 'software', 'ecommerce']
            },
            'software_development': {
                'id': 'software_development',
                'title': 'Software Development',
                'action': 'show_software_services',
                'category': 'services',
                'description': 'View software development services',
                'applicable': ['it', 'technology', 'software']
            },
            'cloud_services': {
                'id': 'cloud_services',
                'title': 'Cloud Services',
                'action': 'show_cloud_services',
                'category': 'services',
                'description': 'View cloud computing services',
                'applicable': ['it', 'technology']
            },
            'cybersecurity': {
                'id': 'cybersecurity',
                'title': 'Cybersecurity',
                'action': 'show_cybersecurity',
                'category': 'services',
                'description': 'View cybersecurity solutions',
                'applicable': ['it', 'technology']
            },

            # Company information / careers buttons
            'projects': {
                'id': 'projects',
                'title': 'Projects',
                'action': 'show_projects',
                'category': 'information',
                'description': 'View our past work and projects',
                'applicable': ['it', 'technology', 'software', 'generic']
            },
            'technologies': {
                'id': 'technologies',
                'title': 'Technologies',
                'action': 'show_technologies',
                'category': 'information',
                'description': 'View the technologies we work with',
                'applicable': ['it', 'technology', 'software']
            },
            'careers': {
                'id': 'careers',
                'title': 'Careers',
                'action': 'show_careers',
                'category': 'information',
                'description': 'View job openings and apply',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'benefits': {
                'id': 'benefits',
                'title': 'Benefits',
                'action': 'show_benefits',
                'category': 'information',
                'description': 'View benefits and perks',
                'applicable': ['it', 'technology', 'software', 'healthcare', 'retail', 'generic']
            },
            
            # Food/Restaurant-specific buttons
            'view_menu': {
                'id': 'view_menu',
                'title': 'View Menu',
                'action': 'show_menu',
                'category': 'products',
                'description': 'Browse our menu',
                'applicable': ['food', 'restaurant', 'cafe']
            },
            'place_order': {
                'id': 'place_order',
                'title': 'Place Order',
                'action': 'place_order',
                'category': 'sales',
                'description': 'Place a new order',
                'applicable': ['food', 'restaurant', 'ecommerce']
            },
            'today_special': {
                'id': 'today_special',
                'title': 'Today Special',
                'action': 'show_today_special',
                'category': 'products',
                'description': 'View today special offers',
                'applicable': ['food', 'restaurant']
            },
            'delivery_info': {
                'id': 'delivery_info',
                'title': 'Delivery Info',
                'action': 'show_delivery_info',
                'category': 'information',
                'description': 'View delivery options and timings',
                'applicable': ['food', 'restaurant', 'ecommerce']
            },
            'catering': {
                'id': 'catering',
                'title': 'Catering Services',
                'action': 'show_catering',
                'category': 'services',
                'description': 'View catering options',
                'applicable': ['food', 'restaurant']
            },
            
            # E-commerce/Retail-specific buttons
            'products': {
                'id': 'products',
                'title': 'Our Products',
                'action': 'show_products',
                'category': 'products',
                'description': 'Browse our product catalog',
                'applicable': ['ecommerce', 'retail', 'manufacturing', 'food']
            },
            'product_categories': {
                'id': 'product_categories',
                'title': 'Product Categories',
                'action': 'show_categories',
                'category': 'products',
                'description': 'View product categories',
                'applicable': ['ecommerce', 'retail', 'manufacturing']
            },
            'product_catalog': {
                'id': 'product_catalog',
                'title': 'Product Brochure',
                'action': 'show_catalog',
                'category': 'products',
                'description': 'View the complete brochure',
                'applicable': ['ecommerce', 'retail', 'manufacturing']
            },
            'pricing': {
                'id': 'pricing',
                'title': 'Pricing',
                'action': 'show_pricing',
                'category': 'sales',
                'description': 'View pricing information',
                'applicable': ['ecommerce', 'it', 'manufacturing', 'retail']
            },
            'discounts': {
                'id': 'discounts',
                'title': 'Discounts',
                'action': 'show_discounts',
                'category': 'sales',
                'description': 'View current discounts and offers',
                'applicable': ['ecommerce', 'retail', 'food']
            },
            'orders': {
                'id': 'orders',
                'title': 'My Orders',
                'action': 'show_orders',
                'category': 'sales',
                'description': 'View your orders and their status',
                'applicable': ['food', 'restaurant', 'ecommerce', 'retail', 'manufacturing']
            },
            'customers': {
                'id': 'customers',
                'title': 'Customers',
                'action': 'show_customers',
                'category': 'crm',
                'description': 'View customer details',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'campaigns': {
                'id': 'campaigns',
                'title': 'Campaigns',
                'action': 'show_campaigns',
                'category': 'sales',
                'description': 'View current campaigns and offers',
                'applicable': ['ecommerce', 'retail', 'food', 'generic']
            },
            'track_order': {
                'id': 'track_order',
                'title': 'Track Order',
                'action': 'track_order',
                'category': 'support',
                'description': 'Track your order status',
                'applicable': ['ecommerce', 'retail', 'food']
            },
            'return_policy': {
                'id': 'return_policy',
                'title': 'Return Policy',
                'action': 'show_return_policy',
                'category': 'information',
                'description': 'View return and refund policy',
                'applicable': ['ecommerce', 'retail']
            },
            
            # Healthcare-specific buttons
            'appointments': {
                'id': 'appointments',
                'title': 'Book Appointment',
                'action': 'book_appointment',
                'category': 'services',
                'description': 'Schedule an appointment',
                'applicable': ['healthcare', 'medical', 'clinic', 'hospital']
            },
            'doctors': {
                'id': 'doctors',
                'title': 'Our Doctors',
                'action': 'show_doctors',
                'category': 'information',
                'description': 'View our medical team',
                'applicable': ['healthcare', 'medical', 'clinic']
            },
            'services': {
                'id': 'services',
                'title': 'Medical Services',
                'action': 'show_medical_services',
                'category': 'services',
                'description': 'View our medical services',
                'applicable': ['healthcare', 'medical', 'clinic', 'hospital']
            },
            'emergency': {
                'id': 'emergency',
                'title': 'Emergency Contact',
                'action': 'emergency_contact',
                'category': 'support',
                'description': 'Emergency contact information',
                'applicable': ['healthcare', 'medical', 'clinic', 'hospital']
            },
            'health_tips': {
                'id': 'health_tips',
                'title': 'Health Tips',
                'action': 'show_health_tips',
                'category': 'information',
                'description': 'View health tips and advice',
                'applicable': ['healthcare', 'medical', 'clinic']
            },
            
            # Manufacturing-specific buttons
            'product_lines': {
                'id': 'product_lines',
                'title': 'Product Lines',
                'action': 'show_product_lines',
                'category': 'products',
                'description': 'View our product lines',
                'applicable': ['manufacturing', 'industrial']
            },
            'technical_specs': {
                'id': 'technical_specs',
                'title': 'Technical Specifications',
                'action': 'show_technical_specs',
                'category': 'information',
                'description': 'View technical specifications',
                'applicable': ['manufacturing', 'it', 'technology']
            },
            'distributors': {
                'id': 'distributors',
                'title': 'Find Distributors',
                'action': 'show_distributors',
                'category': 'sales',
                'description': 'Find authorized distributors',
                'applicable': ['manufacturing', 'industrial', 'retail', 'ecommerce', 'food', 'generic']
            },
            'warranty': {
                'id': 'warranty',
                'title': 'Warranty Info',
                'action': 'show_warranty',
                'category': 'information',
                'description': 'View warranty information',
                'applicable': ['manufacturing', 'retail', 'ecommerce', 'it']
            },
            
            # Generic support buttons
            'raise_ticket': {
                'id': 'raise_ticket',
                'title': 'Raise Support Ticket',
                'action': 'raise_ticket',
                'category': 'support',
                'description': 'Create a support ticket',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'check_ticket_status': {
                'id': 'check_ticket_status',
                'title': 'Check Ticket Status',
                'action': 'check_ticket_status',
                'category': 'support',
                'description': 'Check status of your support ticket',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'live_chat': {
                'id': 'live_chat',
                'title': 'Live Chat',
                'action': 'start_live_chat',
                'category': 'support',
                'description': 'Start a live chat session',
                'applicable': ['it', 'ecommerce', 'retail', 'generic']
            },
            'call_support': {
                'id': 'call_support',
                'title': 'Call Support',
                'action': 'call_support',
                'category': 'support',
                'description': 'Call our support team',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
            'email_support': {
                'id': 'email_support',
                'title': 'Email Support',
                'action': 'email_support',
                'category': 'support',
                'description': 'Send email to support',
                'applicable': ['it', 'food', 'ecommerce', 'manufacturing', 'healthcare', 'retail', 'generic']
            },
        }
    
    def register_button(
        self,
        button_id: str,
        title: str,
        action: str,
        category: str = "general",
        description: str = "",
        applicable: Optional[List[str]] = None
    ) -> None:
        """
        Register a new button programmatically.
        
        Args:
            button_id: Unique identifier for the button
            title: Display title (max 20 chars)
            action: Action to trigger
            category: Button category
            description: Button description
            applicable: List of company types this button applies to
        """
        self.registry[button_id] = {
            'id': button_id,
            'title': title[:20],
            'action': action,
            'category': category,
            'description': description,
            'applicable': applicable or ['generic']
        }
    
    def get_buttons_for_type(
        self,
        company_type: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        Get buttons applicable for a specific company type.
        
        Args:
            company_type: Company type to filter by (default: current company_type)
            
        Returns:
            Dictionary of button_id -> button_info
        """
        ct = company_type or self.company_type
        return {
            k: v for k, v in self.registry.items()
            if ct in v.get('applicable', []) or 'all' in v.get('applicable', [])
        }
    
    def get_button(self, button_id: str) -> Optional[Dict]:
        """
        Get a specific button by ID.
        
        Args:
            button_id: The button ID to retrieve
            
        Returns:
            Button info dictionary or None if not found
        """
        return self.registry.get(button_id)
    
    def get_buttons_by_category(
        self,
        category: str,
        company_type: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        Get buttons by category for a specific company type.
        
        Args:
            category: Category to filter by
            company_type: Company type to filter by
            
        Returns:
            Dictionary of button_id -> button_info
        """
        buttons = self.get_buttons_for_type(company_type)
        return {
            k: v for k, v in buttons.items()
            if v.get('category') == category
        }
    
    def registry_prompt_text(self) -> str:
        """
        Generate text describing available buttons for LLM prompt.
        
        Returns:
            String with button registry in format for LLM prompt
        """
        buttons = self.get_buttons_for_type()
        items = []
        for btn_id, btn_info in buttons.items():
            items.append(f'"{btn_id}": "{btn_info["title"]}"')
        return ", \n".join(items)
    
    def suggest_actions(
        self,
        query: str,
        company_type: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict]:
        """
        Suggest relevant actions based on query keywords.
        
        Args:
            query: User query text
            company_type: Company type to consider
            limit: Maximum number of suggestions
            
        Returns:
            List of suggested action dictionaries
        """
        query_lower = query.lower()
        company_type = company_type or self.company_type
        buttons = self.get_buttons_for_type(company_type)
        suggestions = []
        
        # Keyword matching
        keyword_actions = {
            'menu': ['view_menu', 'menu'],
            'order': ['orders', 'place_order', 'track_order'],
            'customer': ['customers'],
            'campaign': ['campaigns'],
            'portfolio': ['projects'],
            'project': ['projects'],
            'technolog': ['technologies'],
            'career': ['careers'],
            'job': ['careers'],
            'benefit': ['benefits'],
            'product': ['products', 'product_catalog', 'product_categories'],
            'price': ['pricing', 'price'],
            'service': ['it_services', 'services', 'software_development'],
            'technical': ['technical_support', 'it_services'],
            'support': ['contact_support', 'technical_support', 'raise_ticket'],
            'faq': ['faq'],
            'about': ['about_us'],
            'appointment': ['appointments', 'book_appointment'],
            'doctor': ['doctors', 'services'],
            'catalog': ['product_catalog', 'products'],
            'delivery': ['delivery_info'],
            'catering': ['catering'],
            'cloud': ['cloud_services'],
            'security': ['cybersecurity'],
            'distributor': ['distributors'],
            'warranty': ['warranty'],
            'ticket': ['raise_ticket', 'check_ticket_status'],
            'live': ['live_chat'],
            'call': ['call_support'],
            'email': ['email_support'],
        }
        
        for keyword, action_ids in keyword_actions.items():
            if keyword in query_lower:
                for action_id in action_ids:
                    if action_id in buttons:
                        suggestions.append({
                            'id': action_id,
                            'title': buttons[action_id]['title']
                        })
        
        # Remove duplicates while preserving order
        seen: Set[str] = set()
        unique_suggestions = []
        for s in suggestions:
            if s['id'] not in seen:
                seen.add(s['id'])
                unique_suggestions.append(s)
        
        return unique_suggestions[:limit]
    
    def get_main_menu_buttons(
        self,
        company_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Get buttons to show in main menu for a company type.
        
        Args:
            company_type: Company type to get menu for
            
        Returns:
            List of button dictionaries for main menu
        """
        buttons = self.get_buttons_for_type(company_type)
        
        # Main menu typically includes 3-5 most important buttons
        main_menu_ids = ['main_menu']  # Always include main menu
        
        # Add company-specific primary buttons
        ct = company_type or self.company_type
        if ct in ['it', 'technology', 'software']:
            main_menu_ids.extend(['it_services', 'technical_support', 'contact_support'])
        elif ct in ['food', 'restaurant', 'cafe']:
            main_menu_ids.extend(['view_menu', 'place_order', 'contact_support'])
        elif ct in ['ecommerce', 'retail']:
            main_menu_ids.extend(['products', 'orders', 'contact_support'])
        elif ct in ['healthcare', 'medical', 'clinic', 'hospital']:
            main_menu_ids.extend(['appointments', 'services', 'emergency'])
        elif ct in ['manufacturing', 'industrial']:
            main_menu_ids.extend(['product_lines', 'distributors', 'contact_support'])
        else:
            main_menu_ids.extend(['products', 'contact_support', 'faq'])
        
        # Get button info for selected IDs
        result = []
        for btn_id in main_menu_ids:
            if btn_id in buttons:
                result.append(buttons[btn_id])
        
        return result[:3]  # WhatsApp limit: max 3 buttons


# Global instance
button_registry = ButtonRegistry()


# Convenience functions for backward compatibility
BUTTON_REGISTRY = button_registry.registry

def registry_prompt_text() -> str:
    """Get registry prompt text (backward compatibility)."""
    return button_registry.registry_prompt_text()


def suggest_actions(query: str, source_file: str = "") -> List[Dict]:
    """Suggest actions (backward compatibility)."""
    return button_registry.suggest_actions(query)


def enforce_topic_actions(actions: List[Dict], query: str, limit: int = 3) -> List[Dict]:
    """Enforce topic relevance for actions (backward compatibility)."""
    if not actions:
        return []
    
    # Filter to only valid button IDs
    valid_ids = set(button_registry.registry.keys())
    filtered = [a for a in actions if a.get('id') in valid_ids]
    
    return filtered[:limit]
