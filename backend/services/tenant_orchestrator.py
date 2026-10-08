"""
Multi-Tenant Orchestrator for WhatsApp Chatbot SaaS Platform

This module handles the core logic for routing messages to the appropriate
tenant and ensuring strict data isolation between different companies.
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from contextlib import asynccontextmanager

logger = logging.getLogger("tenant_orchestrator")

# Import tenant database functions
from backend.database_multi_tenant import (
    get_tenant_by_whatsapp_number, get_tenant_by_id, identify_tenant,
    get_current_tenant, set_current_tenant, get_current_tenant_id,
    TenantContext, with_tenant
)


class TenantBotOrchestrator:
    """
    Orchestrates message processing across multiple tenants.
    
    This class manages:
    1. Tenant identification from incoming webhooks
    2. Dynamic loading of tenant-specific configurations
    3. Routing to appropriate handlers based on tenant and message type
    4. Maintaining strict data isolation between tenants
    """
    
    def __init__(self):
        # Cache for tenant configurations
        self._tenant_config_cache = {}
        self._handler_registry = {}
        
        # Register default handlers
        self.register_handler('b2c', self._handle_b2c_message)
        self.register_handler('b2b', self._handle_b2b_message)
        self.register_handler('kb', self._handle_kb_message)
        self.register_handler('faq', self._handle_faq_message)
    
    def register_handler(self, route_type: str, handler_func):
        """Register a handler for a specific route type."""
        self._handler_registry[route_type] = handler_func
    
    @asynccontextmanager
    async def tenant_context(self, incoming_number: str = None, wa_id: str = None, tenant_id: int = None):
        """
        Context manager to set up tenant context for message processing.
        
        Usage:
            async with orchestrator.tenant_context(incoming_number=number) as tenant:
                # tenant is now set as current tenant
                result = await orchestrator.process_message(wa_id, message)
        """
        # Identify tenant
        if not tenant_id and not incoming_number:
            raise ValueError("Either tenant_id or incoming_number must be provided")
        
        tenant = None
        if tenant_id:
            tenant = get_tenant_by_id(tenant_id)
        elif incoming_number:
            tenant = get_tenant_by_whatsapp_number(incoming_number)
        
        if not tenant:
            # Fallback: try to identify by wa_id
            tenant = identify_tenant(incoming_number, wa_id)
        
        if not tenant:
            logger.warning(f"No tenant found for incoming_number={incoming_number}, wa_id={wa_id}")
            # Use first tenant as fallback
            from backend.database_multi_tenant import list_tenants
            tenants = list_tenants(limit=1)
            tenant = tenants[0] if tenants else None
        
        if tenant:
            set_current_tenant(tenant)
            logger.info(f"Set tenant context: {tenant['company_name']} (ID: {tenant['id']})")
        
        try:
            yield tenant
        finally:
            # Clean up tenant context
            set_current_tenant(None)
    
    async def process_incoming_message(
        self, 
        wa_id: str, 
        message: str, 
        incoming_number: str = None,
        route: str = None
    ) -> Dict[str, Any]:
        """
        Main entry point for processing an incoming WhatsApp message.
        
        Args:
            wa_id: The WhatsApp ID of the user sending the message
            message: The text content of the message
            incoming_number: The WhatsApp business number that received the message
            route: Optional route hint (faq, b2c, b2b, kb)
        
        Returns:
            Dict with response information including:
            - 'response': The text or menu to send
            - 'tenant_id': The tenant that processed the message
            - 'route': The determined route
            - 'action': Any specific action to take
        """
        tenant = None
        tenant_id = None
        
        # Identify tenant
        if incoming_number:
            tenant = get_tenant_by_whatsapp_number(incoming_number)
        
        if not tenant and wa_id:
            tenant = identify_tenant(incoming_number, wa_id)
        
        if not tenant:
            # Fallback to first tenant
            from backend.database_multi_tenant import list_tenants
            tenants = list_tenants(limit=1)
            tenant = tenants[0] if tenants else None
        
        if not tenant:
            logger.error("Cannot process message - no tenant identified")
            return {
                'response': "Sorry, I cannot process your request at this time.",
                'tenant_id': None,
                'route': 'error',
                'action': 'no_tenant'
            }
        
        tenant_id = tenant['id']
        
        # Set tenant context
        set_current_tenant(tenant)
        
        try:
            # Load tenant configuration
            config = self._load_tenant_config(tenant)
            
            # Process message through appropriate handler
            if route:
                # Use the provided route
                handler = self._handler_registry.get(route)
                if handler:
                    result = await handler(wa_id, message, tenant, config)
                else:
                    result = await self._handle_general_message(wa_id, message, tenant, config)
            else:
                # Determine route dynamically
                result = await self._determine_and_handle_route(wa_id, message, tenant, config)
            
            # Ensure result has tenant_id
            result['tenant_id'] = tenant_id
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing message for tenant {tenant_id}: {e}")
            return {
                'response': "Sorry, there was an error processing your request.",
                'tenant_id': tenant_id,
                'route': 'error',
                'action': 'processing_error',
                'error': str(e)
            }
        finally:
            # Clean up tenant context
            set_current_tenant(None)
    
    def _load_tenant_config(self, tenant: Dict[str, Any]) -> Dict[str, Any]:
        """Load configuration for a specific tenant."""
        tenant_id = tenant['id']
        
        # Check cache first
        if tenant_id in self._tenant_config_cache:
            return self._tenant_config_cache[tenant_id]
        
        config = {
            'tenant_id': tenant_id,
            'company_name': tenant.get('company_name', ''),
            'whatsapp_number': tenant.get('whatsapp_number', ''),
            'system_prompt': tenant.get('system_prompt', ''),
            'send2_username': tenant.get('send2_username', ''),
            'send2_password': tenant.get('send2_password', ''),
            'brand_color': tenant.get('brand_color', '#25D366'),
            'welcome_message': tenant.get('welcome_message', 'Welcome!'),
            'industry_type': tenant.get('industry_type', 'general'),
            'menu_config': self._load_tenant_menu_config(tenant_id),
            'kb_config': self._load_tenant_kb_config(tenant_id)
        }
        
        # Cache the config
        self._tenant_config_cache[tenant_id] = config
        
        return config
    
    def _load_tenant_menu_config(self, tenant_id: int) -> Dict[str, Any]:
        """Load menu configuration for a tenant."""
        from backend.database_multi_tenant import get_tenant_main_menu
        
        try:
            menu_config = get_tenant_main_menu(tenant_id)
            return menu_config or {'sections': []}
        except Exception as e:
            logger.error(f"Failed to load menu config for tenant {tenant_id}: {e}")
            return {'sections': []}
    
    def _load_tenant_kb_config(self, tenant_id: int) -> Dict[str, Any]:
        """Load knowledge base configuration for a tenant."""
        try:
            from backend.database_multi_tenant import list_tenants
            # This would be replaced with actual KB config loading
            return {
                'kb_enabled': True,
                'faq_enabled': True,
                'rag_enabled': True,
                'tenant_id': tenant_id
            }
        except Exception as e:
            logger.error(f"Failed to load KB config for tenant {tenant_id}: {e}")
            return {}
    
    async def _determine_and_handle_route(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Determine the appropriate route for a message and handle it."""
        # Simple route detection based on message content
        message_lower = message.strip().lower()
        
        # Check for menu/start commands
        if message_lower in ['hi', 'hello', 'hey', 'start', 'menu', 'main menu', 'main']:
            return await self._handle_main_menu(wa_id, message, tenant, config)
        
        # Check for admin commands
        elif message_lower in ['admin', 'help']:
            return await self._handle_admin_request(wa_id, message, tenant, config)
        
        # Default to KB/FAQ for general questions
        else:
            return await self._handle_general_message(wa_id, message, tenant, config)
    
    async def _handle_main_menu(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle main menu request for a tenant."""
        from .tenant_menu_service import TenantMenuService
        
        menu_service = TenantMenuService(tenant['id'])
        menu_data = menu_service.get_main_menu()
        
        # This would be replaced with actual menu rendering
        return {
            'response': menu_data,
            'route': 'menu',
            'action': 'show_main_menu',
            'menu_type': 'interactive_list'
        }
    
    async def _handle_general_message(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle general messages using tenant-specific KB/RAG."""
        # Use tenant-specific RAG search
        tenant_id = tenant['id']
        
        try:
            from kb.services.rag import search_tenant_kb
            answer = await search_tenant_kb(tenant_id, message)
            
            if answer:
                return {
                    'response': answer,
                    'route': 'kb',
                    'action': 'rag_answer'
                }
            else:
                return {
                    'response': "I'm not sure I understand. Would you like to see the menu?",
                    'route': 'fallback',
                    'action': 'no_match'
                }
        except Exception as e:
            logger.error(f"RAG search failed for tenant {tenant_id}: {e}")
            return {
                'response': "Sorry, I'm having trouble finding information about that.",
                'route': 'error',
                'action': 'rag_error'
            }
    
    async def _handle_faq_message(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle FAQ-specific messaging."""
        tenant_id = tenant['id']
        
        try:
            from faq.service import search_tenant_faq
            answer = await search_tenant_faq(tenant_id, message)
            
            if answer:
                return {
                    'response': answer,
                    'route': 'faq',
                    'action': 'faq_answer'
                }
            else:
                # Fallback to general message handling
                return await self._handle_general_message(wa_id, message, tenant, config)
                
        except Exception as e:
            logger.error(f"FAQ search failed for tenant {tenant_id}: {e}")
            return {
                'response': "Sorry, I couldn't find FAQ information about that.",
                'route': 'error',
                'action': 'faq_error'
            }
    
    async def _handle_kb_message(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle knowledge base specific messaging."""
        return await self._handle_general_message(wa_id, message, tenant, config)
    
    async def _handle_b2c_message(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle B2C (customer) specific messaging with tenant awareness."""
        tenant_id = tenant['id']
        
        # Import and call the existing B2C handler with tenant context
        try:
            # This would be the updated version of bots.customer_b2c.workflows
            from bots.customer_b2c.tenant_workflows import handle_b2c_message as tenant_b2c_handler
            
            result = await tenant_b2c_handler(wa_id, message, tenant_id)
            return {
                'response': result.get('response', ''),
                'route': 'b2c',
                'action': result.get('action', 'general'),
                'new_state': result.get('new_state', 'MAIN_MENU')
            }
        except ImportError:
            # Fallback to general handling
            logger.warning("Tenant-aware B2C handler not available, falling back to general")
            return await self._handle_general_message(wa_id, message, tenant, config)
        except Exception as e:
            logger.error(f"B2C processing failed for tenant {tenant_id}: {e}")
            return {
                'response': "Sorry, there was an error processing your request.",
                'route': 'error',
                'action': 'b2c_error',
                'error': str(e)
            }
    
    async def _handle_b2b_message(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle B2B (distributor) specific messaging with tenant awareness."""
        tenant_id = tenant['id']
        
        try:
            # This would be the updated version of bots.distributor_b2b.workflows
            from bots.distributor_b2b.tenant_workflows import handle_b2b_message as tenant_b2b_handler
            
            result = await tenant_b2b_handler(wa_id, message, tenant_id)
            return {
                'response': result.get('response', ''),
                'route': 'b2b',
                'action': result.get('action', 'general'),
                'new_state': result.get('new_state', 'MAIN_MENU')
            }
        except ImportError:
            # Fallback to general handling
            logger.warning("Tenant-aware B2B handler not available, falling back to general")
            return await self._handle_general_message(wa_id, message, tenant, config)
        except Exception as e:
            logger.error(f"B2B processing failed for tenant {tenant_id}: {e}")
            return {
                'response': "Sorry, there was an error processing your business request.",
                'route': 'error',
                'action': 'b2b_error',
                'error': str(e)
            }
    
    async def _handle_admin_request(
        self, wa_id: str, message: str, tenant: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle admin-specific requests."""
        return {
            'response': "Admin functions are not available through this interface.",
            'route': 'admin',
            'action': 'not_available'
        }


# ── Global Orchestrator Instance ────────────────────────────────────────
# This is the main orchestrator instance that will be used throughout the application
orchestrator = TenantBotOrchestrator()


# ── Convenience Functions ─────────────────────────────────────────────────

async def process_tenant_message(
    wa_id: str, 
    message: str, 
    incoming_number: str = None,
    route: str = None
) -> Dict[str, Any]:
    """
    Convenience function to process a message with tenant awareness.
    
    This is the main entry point that should be called from your webhook handlers.
    
    Example:
        @whatsapp_webhook.post("/webhook")
        async def handle_webhook(payload: dict):
            wa_id = payload.get('wa_id')
            message = payload.get('message')
            incoming_number = payload.get('incoming_number')
            
            result = await process_tenant_message(wa_id, message, incoming_number)
            # Send response back to WhatsApp
    """
    return await orchestrator.process_incoming_message(wa_id, message, incoming_number, route)


async def get_tenant_config(tenant_id: int = None, incoming_number: str = None) -> Dict[str, Any]:
    """Get the configuration for a specific tenant."""
    if not tenant_id and incoming_number:
        tenant = get_tenant_by_whatsapp_number(incoming_number)
        tenant_id = tenant['id'] if tenant else None
    
    if not tenant_id:
        return {}
    
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return {}
    
    orch = TenantBotOrchestrator()
    return orch._load_tenant_config(tenant)


async def get_tenant_system_prompt(tenant_id: int = None, incoming_number: str = None) -> str:
    """Get the system prompt for a specific tenant."""
    config = await get_tenant_config(tenant_id, incoming_number)
    return config.get('system_prompt', '')