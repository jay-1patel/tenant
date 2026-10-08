"""
Tenant Menu Service for Multi-Tenant WhatsApp Chatbot SaaS Platform

This service provides dynamic menu building and management for each tenant,
replacing all hardcoded menu structures with database-driven configurations.
"""

import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("tenant_menu_service")

from backend.database_multi_tenant import (
    tenant_query, get_tenant_main_menu, get_tenant_by_id,
    get_current_tenant_id, create_tenant_menu_config, create_tenant_menu_item
)


class TenantMenuService:
    """
    Service for managing and building dynamic menus for tenants.
    
    Each tenant can have their own menu structure, menu items, and configurations.
    This allows each company using the platform to have completely customized menus
    that reflect their own services, products, and branding.
    """
    
    def __init__(self, tenant_id: int = None):
        """Initialize the menu service for a specific tenant."""
        self.tenant_id = tenant_id or get_current_tenant_id()
        if not self.tenant_id:
            raise ValueError("tenant_id is required for TenantMenuService")
        
        self._menu_cache = {}
    
    def get_main_menu(self) -> Dict[str, Any]:
        """Get the main menu configuration for the tenant."""
        return self._get_menu_config('main')
    
    def get_menu_config(self, menu_type: str = 'main') -> Dict[str, Any]:
        """Get a specific menu configuration for the tenant."""
        return self._get_menu_config(menu_type)
    
    def _get_menu_config(self, menu_type: str) -> Dict[str, Any]:
        """Internal method to get menu config with caching."""
        cache_key = f"tenant_{self.tenant_id}_{menu_type}"
        
        if cache_key in self._menu_cache:
            return self._menu_cache[cache_key]
        
        try:
            menu_config = get_tenant_main_menu(self.tenant_id)
            if menu_config:
                # Parse the config JSON
                config = json.loads(menu_config.get('config_json', '{}'))
                self._menu_cache[cache_key] = config
                return config
            else:
                # Return default menu structure
                default_menu = self._get_default_menu_structure()
                self._menu_cache[cache_key] = default_menu
                return default_menu
        except Exception as e:
            logger.error(f"Failed to load menu config for tenant {self.tenant_id}: {e}")
            return self._get_default_menu_structure()
    
    def _get_default_menu_structure(self) -> Dict[str, Any]:
        """Get a default menu structure for new tenants."""
        return {
            "menu_name": "Main Menu",
            "menu_type": "main",
            "button_text": "Select an option",
            "sections": [
                {
                    "title": "🌐 Our Services",
                    "items": [
                        {
                            "id": "our_services",
                            "title": "View All Services",
                            "description": "See what we offer",
                            "action": "message",
                            "payload": "services"
                        }
                    ]
                },
                {
                    "title": "📞 Contact Us",
                    "items": [
                        {
                            "id": "contact_support",
                            "title": "Contact Support",
                            "description": "Get help from our team",
                            "action": "message",
                            "payload": "contact"
                        }
                    ]
                }
            ]
        }
    
    def get_menu_items(self, menu_type: str = 'main') -> List[Dict[str, Any]]:
        """Get all menu items for a specific menu type."""
        try:
            items = tenant_query('tenant_menu_items', self.tenant_id, menu_config_id=None)
            return items
        except Exception as e:
            logger.error(f"Failed to load menu items for tenant {self.tenant_id}: {e}")
            return []
    
    def build_whatsapp_list_menu(self, menu_type: str = 'main') -> Dict[str, Any]:
        """
        Build a WhatsApp Interactive List menu from the tenant's menu configuration.
        
        Returns a properly formatted menu that can be sent via WhatsApp API.
        """
        menu_config = self.get_menu_config(menu_type)
        
        # Build the menu sections for WhatsApp
        sections = []
        
        for section_data in menu_config.get('sections', []):
            section = {
                "title": section_data.get('title', 'Untitled Section')
            }
            
            # Build menu rows from section items
            rows = []
            for item in section_data.get('items', []):
                if item.get('is_active', True):  # Only include active items
                    row = {
                        "id": item.get('id', f"item_{len(rows)}"),
                        "title": item.get('title', 'Untitled'),
                        "description": item.get('description', '')
                    }
                    rows.append(row)
            
            if rows:  # Only include sections with rows
                section["rows"] = rows
                sections.append(section)
        
        # Build the final menu structure
        whatsapp_menu = {
            "type": "interactive",
            "body": {
                "text": menu_config.get('button_text', "Please select an option:")
            },
            "action": {
                "button": menu_config.get('menu_name', "Main Menu"),
                "sections": sections
            }
        }
        
        return whatsapp_menu
    
    def build_simple_menu(self, menu_type: str = 'main') -> Dict[str, Any]:
        """
        Build a simple button-style menu for non-interactive clients.
        
        Returns a simpler menu structure that works with basic WhatsApp clients.
        """
        menu_config = self.get_menu_config(menu_type)
        
        buttons = []
        for section_data in menu_config.get('sections', []):
            for item in section_data.get('items', []):
                if item.get('is_active', True):
                    buttons.append({
                        "type": "reply",
                        "reply": {
                            "id": item.get('id', f"btn_{len(buttons)}"),
                            "title": item.get('title', 'Untitled')
                        }
                    })
        
        return {
            "text": menu_config.get('button_text', "Please select an option:"),
            "buttons": buttons
        }
    
    def create_menu(self, menu_type: str, menu_name: str, sections: List[Dict[str, Any]]) -> int:
        """
        Create a new menu configuration for the tenant.
        
        Args:
            menu_type: Type of menu (e.g., 'main', 'services', 'support')
            menu_name: Display name for the menu
            sections: List of section configurations
            
        Returns:
            ID of the created menu configuration
        """
        config_data = {
            "menu_name": menu_name,
            "menu_type": menu_type,
            "button_text": "Please select an option",
            "sections": sections
        }
        
        menu_config_id = create_tenant_menu_config(
            tenant_id=self.tenant_id,
            menu_type=menu_type,
            menu_name=menu_name,
            config_json=config_data
        )
        
        self._menu_cache = {}  # Clear cache after creating new menu
        
        return menu_config_id
    
    def update_menu(self, menu_type: str,menu_name: str, sections: List[Dict[str, Any]]) -> int:
        """
        Update an existing menu configuration for the tenant.
        """
        config_data = {
            "menu_name": menu_name,
            "menu_type": menu_type,
            "button_text": "Please select an option",
            "sections": sections
        }
        
        # For now, we'll delete and recreate (in production, use UPDATE)
        return self.create_menu(menu_type, menu_name, sections)
    
    def add_menu_item(self, menu_type: str, item_data: Dict[str, Any]) -> int:
        """
        Add a menu item to an existing menu configuration.
        
        Args:
            menu_type: The menu type to add the item to
            item_data: Menu item data including title, description, etc.
            
        Returns:
            ID of the created menu item
        """
        # Get the menu config ID
        menu_config = self._get_menu_config(menu_type)
        if not menu_config:
            # Create default menu if it doesn't exist
            self.create_menu(menu_type, f"{menu_type.title()} Menu", [])
            menu_config = self._get_menu_config(menu_type)
        
        # Find the menu config ID in the database
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM tenant_menu_configs WHERE tenant_id = ? AND menu_type = ?",
                (self.tenant_id, menu_type)
            ).fetchone()
            
            if not row:
                # Create the menu config first
                menu_config_id = self.create_menu(menu_type, f"{menu_type.title()} Menu", [])
            else:
                menu_config_id = row['id']
        
        # Create the menu item
        item_data['menu_config_id'] = menu_config_id
        item_id = create_tenant_menu_item(
            tenant_id=self.tenant_id,
            menu_config_id=menu_config_id,
            item_data=item_data
        )
        
        self._menu_cache = {}  # Clear cache after updating menu
        
        return item_id
    
    def get_menu_by_action(self, action: str) -> Optional[Dict[str, Any]]:
        """
        Find a menu item by its action ID.
        
        This is useful for routing based on menu selections.
        """
        menu_items = self.get_menu_items()
        
        for item in menu_items:
            if item.get('action_payload') == action or item.get('id') == action:
                return item
        
        return None


# ── Factory and Convenience Functions ────────────────────────────────────

def get_tenant_menu_service(tenant_id: int = None) -> TenantMenuService:
    """Get a menu service instance for a specific tenant."""
    return TenantMenuService(tenant_id)


def get_main_menu_for_tenant(tenant_id: int = None) -> Dict[str, Any]:
    """Get the main menu for a specific tenant."""
    service = get_tenant_menu_service(tenant_id)
    return service.get_main_menu()


def build_whatsapp_menu_for_tenant(tenant_id: int = None) -> Dict[str, Any]:
    """Build a WhatsApp-compatible menu for a specific tenant."""
    service = get_tenant_menu_service(tenant_id)
    return service.build_whatsapp_list_menu()


# ── Legacy Menu Compatibility ────────────────────────────────────────────
# These functions provide compatibility with the existing menu system

def get_legacy_menus_by_tenant(tenant_id: int) -> List[Dict[str, Any]]:
    """
    Get all legacy menu items for a tenant from the old menus table.
    This provides backward compatibility during migration.
    """
    from backend.database import get_db_context
    
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT * FROM menus WHERE tenant_id = ? ORDER BY sort_order",
            (tenant_id,)
        ).fetchall()
    
    return [dict(row) for row in rows]


def migrate_legacy_menus_to_tenant(tenant_id: int):
    """
    Migrate a tenant's legacy menu items to the new tenant menu system.
    
    This is a one-time migration function to move from the old hardcoded
    menu system to the new dynamic menu system.
    """
    # Get all legacy menu items for this tenant
    legacy_items = get_legacy_menus_by_tenant(tenant_id)
    
    if not legacy_items:
        logger.info(f"No legacy menu items found for tenant {tenant_id}")
        return 0
    
    # Create a main menu for this tenant
    service = TenantMenuService(tenant_id)
    
    # Group by menu_key
    menus_by_type = {}
    for item in legacy_items:
        menu_key = item.get('menu_key')
        if menu_key not in menus_by_type:
            menus_by_type[menu_key] = []
        menus_by_type[menu_key].append(item)
    
    # Convert each menu_key to new format
    migrated_count = 0
    for menu_key, items in menus_by_type.items():
        sections = {}
        for item in items:
            section = item.get('section', 'General')
            if section not in sections:
                sections[section] = []
            
            sections[section].append({
                'id': item.get('item_id'),
                'title': item.get('title'),
                'description': item.get('description'),
                'action': 'message',
                'payload': item.get('item_id')
            })
        
        # Convert sections dict to list
        section_list = [
            {'title': section, 'items': items}
            for section, items in sections.items()
        ]
        
        # Create the menu
        if menu_key == 'kb_main':  # This was our main menu
            service.create_menu('main', 'Main Menu', section_list)
            migrated_count += 1
        else:
            service.create_menu(menu_key, f"{menu_key.replace('_', ' ').title()} Menu", section_list)
            migrated_count += 1
    
    logger.info(f"Migrated {migrated_count} legacy menus to tenant {tenant_id}")
    return migrated_count