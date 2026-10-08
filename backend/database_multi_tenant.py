"""
Multi-Tenant Database Layer for WhatsApp Chatbot SaaS Platform

This module extends the existing database.py with multi-tenant support.
Every operation is now tenant-aware with strict data isolation.
"""

import os
import json
import sqlite3
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

logger = logging.getLogger("database_multi_tenant")

# Import the existing database functions to extend them
from .database import (
    get_db_context, get_db, _ensure_columns, _loads_json,
    PROJECT_ROOT, DB_PATH
)


# ── Tenant Context Management ────────────────────────────────────────────
# Global tenant context for the current request (set by middleware)
_current_tenant = None

def set_current_tenant(tenant: Dict[str, Any] = None):
    """Set the current tenant for this request."""
    global _current_tenant
    _current_tenant = tenant

def get_current_tenant() -> Optional[Dict[str, Any]]:
    """Get the current tenant for this request."""
    global _current_tenant
    return _current_tenant

def get_current_tenant_id() -> Optional[int]:
    """Get the current tenant ID for this request."""
    tenant = get_current_tenant()
    return tenant['id'] if tenant else None


# ── Tenant Core Functions ────────────────────────────────────────────────

def create_tenants_table():
    """Create the tenants table if it doesn't exist."""
    with get_db_context() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                whatsapp_number TEXT UNIQUE,
                send2_username TEXT,
                send2_password TEXT,
                system_prompt TEXT,
                brand_color TEXT DEFAULT '#25D366',
                logo_url TEXT,
                domain TEXT,
                industry_type TEXT DEFAULT 'general',
                welcome_message TEXT DEFAULT 'Welcome! How can I help you today?',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        
        # Add indexes for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tenants_slug ON tenants(slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tenants_whatsapp ON tenants(whatsapp_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active)")

def add_tenant_id_to_all_tables():
    """Add tenant_id column to all data tables for strict isolation."""
    with get_db_context() as conn:
        # List of all tables that need tenant_id
        tables_to_update = [
            ('chat_history', [('tenant_id', 'INTEGER')]),
            ('webhook_logs', [('tenant_id', 'INTEGER')]),
            ('faq_dataset', [('tenant_id', 'INTEGER')]),
            ('knowledge_base', [('tenant_id', 'INTEGER')]),
            ('incoming_messages', [('tenant_id', 'INTEGER')]),
            ('cached_embeddings', [('tenant_id', 'INTEGER')]),
            ('user_sessions', [('tenant_id', 'INTEGER NOT NULL DEFAULT 1')]),
            ('user_states', [('tenant_id', 'INTEGER NOT NULL DEFAULT 1')]),
            ('products', [('tenant_id', 'INTEGER')]),
            ('complaints', [('tenant_id', 'INTEGER')]),
            ('leads', [('tenant_id', 'INTEGER')]),
            ('orders', [('tenant_id', 'INTEGER')]),
            ('admins', [('tenant_id', 'INTEGER')]),
            ('menus', [('tenant_id', 'INTEGER')]),
            ('menu_settings', [('tenant_id', 'INTEGER')]),
            ('carts', [('tenant_id', 'INTEGER')]),
            ('cart_items', [('tenant_id', 'INTEGER')]),
            ('checkout_sessions', [('tenant_id', 'INTEGER')]),
            ('distributors', [('tenant_id', 'INTEGER')]),
            ('campaigns', [('tenant_id', 'INTEGER')]),
            ('campaign_replies', [('tenant_id', 'INTEGER')]),
            ('whatsapp_templates', [('tenant_id', 'INTEGER')]),
            ('session_buttons', [('tenant_id', 'INTEGER')]),
            ('button_clicks', [('tenant_id', 'INTEGER')]),
            ('published_config', [('tenant_id', 'INTEGER')]),
            ('draft_config', [('tenant_id', 'INTEGER')]),
            ('publish_history', [('tenant_id', 'INTEGER')])
        ]
        
        for table_name, columns in tables_to_update:
            _ensure_columns(conn, table_name, columns)
        
        # Add tenant_id to existing records (assign to first tenant)
        tenant_check = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        if tenant_check == 0:
            # Create default tenant
            conn.execute(
                """INSERT INTO tenants (
                    company_name, slug, system_prompt, industry_type
                ) VALUES (?, ?, ?, ?)""",
                ("Leeway Softech", "leeway-softech", 
                 "You are the AI assistant for Leeway Softech, a premier IT services company.",
                 "IT Services")
            )
            default_tenant_id = conn.execute("SELECT id FROM tenants ORDER BY id LIMIT 1").fetchone()[0]
        else:
            default_tenant_id = conn.execute("SELECT id FROM tenants ORDER BY id LIMIT 1").fetchone()[0]
        
        # Update existing records with default tenant_id
        tables_with_existing_data = [
            'chat_history', 'webhook_logs', 'faq_dataset', 'knowledge_base',
            'incoming_messages', 'cached_embeddings', 'user_sessions', 'user_states',
            'products', 'complaints', 'leads', 'orders', 'admins', 'menus',
            'menu_settings', 'carts', 'cart_items', 'checkout_sessions',
            'distributors', 'campaigns', 'campaign_replies', 'whatsapp_templates',
            'session_buttons', 'button_clicks', 'published_config', 'draft_config', 'publish_history'
        ]
        
        for table_name in tables_with_existing_data:
            try:
                # Check if there are any records without tenant_id
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE tenant_id IS NULL"
                ).fetchone()[0]
                
                if count > 0:
                    conn.execute(
                        f"UPDATE {table_name} SET tenant_id = ? WHERE tenant_id IS NULL",
                        (default_tenant_id,)
                    )
                    logger.info(f"Updated {count} records in {table_name} with tenant_id={default_tenant_id}")
            except Exception as e:
                logger.error(f"Failed to update tenant_id in {table_name}: {e}")

def initialize_multi_tenant_db():
    """Initialize the multi-tenant database layer."""
    create_tenants_table()
    add_tenant_id_to_all_tables()
    create_tenant_specific_tables()


def create_tenant_specific_tables():
    """Create tables specific to multi-tenant functionality."""
    with get_db_context() as conn:
        # Menu configuration tables (replacing hardcoded menus)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tenant_menu_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                menu_type TEXT NOT NULL DEFAULT 'main',
                menu_name TEXT NOT NULL DEFAULT 'Main Menu',
                config_json TEXT NOT NULL DEFAULT '{}',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                UNIQUE(tenant_id, menu_type)
            )"""
        )
        
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tenant_menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                menu_config_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                section TEXT DEFAULT 'General',
                icon TEXT DEFAULT '',
                action_type TEXT DEFAULT 'message',
                action_payload TEXT,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                FOREIGN KEY (menu_config_id) REFERENCES tenant_menu_configs(id),
                UNIQUE(tenant_id, item_id)
            )"""
        )


# ── Tenant CRUD Operations ───────────────────────────────────────────────

def create_tenant(
    company_name: str,
    slug: str,
    whatsapp_number: str,
    send2_username: str = None,
    send2_password: str = None,
    system_prompt: str = None,
    brand_color: str = "#25D366",
    logo_url: str = None,
    domain: str = None,
    industry_type: str = "general",
    welcome_message: str = "Welcome! How can I help you today?"
) -> int:
    """Create a new tenant/company."""
    with get_db_context() as conn:
        cursor = conn.execute(
            """INSERT INTO tenants (
                company_name, slug, whatsapp_number, send2_username, send2_password,
                system_prompt, brand_color, logo_url, domain, industry_type, welcome_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_name, slug, whatsapp_number, send2_username, send2_password,
             system_prompt, brand_color, logo_url, domain, industry_type, welcome_message)
        )
        tenant_id = cursor.lastrowid
        
        # Create default menu configuration
        default_menu_config = {
            "sections": [
                {"title": "🌐 Our Services", "items": []},
                {"title": "📞 Contact", "items": []},
                {"title": "🛠️ Support", "items": []}
            ]
        }
        
        conn.execute(
            """INSERT INTO tenant_menu_configs 
               (tenant_id, menu_type, menu_name, config_json)
               VALUES (?, 'main', 'Main Menu', ?)""",
            (tenant_id, json.dumps(default_menu_config))
        )
        
        logger.info(f"Created new tenant: {company_name} (ID: {tenant_id})")
    
    return tenant_id


def get_tenant_by_whatsapp_number(whatsapp_number: str) -> Optional[Dict[str, Any]]:
    """Get tenant by their WhatsApp business number."""
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM tenants WHERE whatsapp_number = ?", (whatsapp_number,)
        ).fetchone()
    return dict(row) if row else None


def get_tenant_by_id(tenant_id: int) -> Optional[Dict[str, Any]]:
    """Get tenant by ID."""
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
    return dict(row) if row else None


def get_tenant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Get tenant by slug."""
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT * FROM tenants WHERE slug = ?", (slug,)
        ).fetchone()
    return dict(row) if row else None


def list_tenants(
    is_active: bool = True,
    limit: int = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """List all tenants with optional filtering."""
    with get_db_context() as conn:
        query = "SELECT * FROM tenants WHERE 1=1"
        params = []
        
        if is_active is not None:
            query += " AND is_active = ?"
            params.append(1 if is_active else 0)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
    
    return [dict(row) for row in rows]


def update_tenant(tenant_id: int, **kwargs) -> bool:
    """Update tenant information."""
    if not tenant_id:
        return False
    
    valid_fields = [
        'company_name', 'slug', 'whatsapp_number', 'send2_username', 'send2_password',
        'system_prompt', 'brand_color', 'logo_url', 'domain', 'industry_type',
        'welcome_message', 'is_active'
    ]
    
    data = {k: v for k, v in kwargs.items() if k in valid_fields}
    if not data:
        return False
    
    sets = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values())
    values.append(tenant_id)
    
    with get_db_context() as conn:
        conn.execute(
            f"UPDATE tenants SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values
        )
    
    logger.info(f"Updated tenant {tenant_id}")
    return True


def deactivate_tenant(tenant_id: int) -> bool:
    """Deactivate a tenant (soft delete)."""
    return update_tenant(tenant_id, is_active=False)


def delete_tenant(tenant_id: int) -> bool:
    """Permanently delete a tenant and all their data."""
    with get_db_context() as conn:
        # Delete all tenant-specific data
        tables_with_tenant_id = [
            'tenant_menu_configs', 'tenant_menu_items',
            'chat_history', 'webhook_logs', 'faq_dataset', 'knowledge_base',
            'incoming_messages', 'cached_embeddings', 'user_sessions', 'user_states',
            'products', 'complaints', 'leads', 'orders', 'admins',
            'menus', 'menu_settings', 'carts', 'cart_items', 'checkout_sessions',
            'distributors', 'campaigns', 'campaign_replies', 'whatsapp_templates',
            'session_buttons', 'button_clicks', 'published_config', 'draft_config', 'publish_history'
        ]
        
        for table in tables_with_tenant_id:
            try:
                conn.execute(f"DELETE FROM {table} WHERE tenant_id = ?", (tenant_id,))
            except Exception as e:
                logger.error(f"Failed to delete from {table}: {e}")
        
        # Finally delete the tenant
        conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
    
    logger.info(f"Deleted tenant {tenant_id} and all associated data")
    return True


# ── Tenant Identification ────────────────────────────────────────────────

def identify_tenant(incoming_number: str = None, wa_id: str = None) -> Optional[Dict[str, Any]]:
    """Identify which tenant a message belongs to."""
    # First try by incoming WhatsApp number (company's business number)
    if incoming_number:
        tenant = get_tenant_by_whatsapp_number(incoming_number)
        if tenant:
            return tenant
    
    # If we have wa_id (user's number), check existing sessions
    if wa_id:
        with get_db_context() as conn:
            row = conn.execute(
                """SELECT t.* FROM tenants t
                   JOIN user_sessions us ON t.id = us.tenant_id
                   WHERE us.wa_id = ?""", (wa_id,)
            ).fetchone()
            if row:
                return dict(row)
    
    # Fallback: return first active tenant if available
    tenants = list_tenants(is_active=True, limit=1)
    return tenants[0] if tenants else None


def get_tenant_id_for_request(incoming_number: str = None, wa_id: str = None) -> Optional[int]:
    """Get tenant_id for a request based on incoming number or user wa_id."""
    tenant = identify_tenant(incoming_number, wa_id)
    return tenant['id'] if tenant else None


# ── Tenant Context Utilities ────────────────────────────────────────────

class TenantContext:
    """Context manager for multi-tenant operations."""
    
    def __init__(self, tenant_id: int = None, whatsapp_number: str = None, wa_id: str = None):
        self.tenant_id = tenant_id
        self.whatsapp_number = whatsapp_number
        self.wa_id = wa_id
        self.previous_tenant = None
    
    def __enter__(self):
        # If we have a whatsapp_number but not tenant_id, look it up
        if self.whatsapp_number and not self.tenant_id:
            tenant = get_tenant_by_whatsapp_number(self.whatsapp_number)
            if tenant:
                self.tenant_id = tenant['id']
        
        # If we have wa_id but not tenant_id, try to find it
        elif self.wa_id and not self.tenant_id:
            tenant = identify_tenant(None, self.wa_id)
            if tenant:
                self.tenant_id = tenant['id']
        
        if self.tenant_id:
            tenant = get_tenant_by_id(self.tenant_id)
            if tenant:
                self.previous_tenant = get_current_tenant()
                set_current_tenant(tenant)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.previous_tenant:
            set_current_tenant(self.previous_tenant)
        else:
            set_current_tenant(None)


def with_tenant(tenant_id: int = None, whatsapp_number: str = None, wa_id: str = None):
    """Decorator to set tenant context for a function."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with TenantContext(tenant_id=tenant_id, whatsapp_number=whatsapp_number, wa_id=wa_id):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# ── Tenant-Specific Data Access ────────────────────────────────────────

def tenant_query(table: str, tenant_id: int = None, **kwargs) -> List[Dict[str, Any]]:
    """Execute a query with automatic tenant_id filtering."""
    tenant_id = tenant_id or get_current_tenant_id()
    if not tenant_id:
        logger.warning("No tenant_id provided, returning empty result")
        return []
    
    with get_db_context() as conn:
        query = f"SELECT * FROM {table} WHERE tenant_id = ?"
        params = [tenant_id]
        
        # Add additional filters from kwargs
        where_clauses = []
        additional_params = []
        for key, value in kwargs.items():
            if key != 'tenant_id':
                where_clauses.append(f"{key} = ?")
                additional_params.append(value)
        
        if where_clauses:
            query += " AND " + " AND ".join(where_clauses)
            params.extend(additional_params)
        
        rows = conn.execute(query, params).fetchall()
    
    return [dict(row) for row in rows]


def tenant_get_one(table: str, tenant_id: int = None, **kwargs) -> Optional[Dict[str, Any]]:
    """Get one record from a table with tenant filtering."""
    results = tenant_query(table, tenant_id, **kwargs)
    return results[0] if results else None


def tenant_create(table: str, data: Dict[str, Any], tenant_id: int = None) -> int:
    """Create a record in a tenant-specific table."""
    tenant_id = tenant_id or get_current_tenant_id()
    if not tenant_id:
        logger.error("No tenant_id provided for create operation")
        return None
    
    # Add tenant_id to the data
    data['tenant_id'] = tenant_id
    
    with get_db_context() as conn:
        columns = [f"{k}" for k in data.keys()]
        placeholders = ["?"] * len(data)
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        
        cursor = conn.execute(query, list(data.values()))
        return cursor.lastrowid


# ── Menu Management for Multi-Tenancy ──────────────────────────────────

def get_tenant_main_menu(tenant_id: int = None) -> Optional[Dict[str, Any]]:
    """Get the main menu configuration for a tenant."""
    tenant_id = tenant_id or get_current_tenant_id()
    if not tenant_id:
        return None
    
    menus = tenant_query('tenant_menu_configs', tenant_id, menu_type='main')
    return menus[0] if menus else None


def get_all_tenant_menu_configs(tenant_id: int = None) -> List[Dict[str, Any]]:
    """Get all menu configurations for a tenant."""
    tenant_id = tenant_id or get_current_tenant_id()
    return tenant_query('tenant_menu_configs', tenant_id)


def get_tenant_menu_items(menu_config_id: int, tenant_id: int = None) -> List[Dict[str, Any]]:
    """Get all menu items for a specific menu configuration."""
    tenant_id = tenant_id or get_current_tenant_id()
    if not tenant_id:
        return []
    
    with get_db_context() as conn:
        rows = conn.execute(
            """SELECT * FROM tenant_menu_items 
               WHERE menu_config_id = ? AND tenant_id = ?
               ORDER BY sort_order, id""",
            (menu_config_id, tenant_id)
        ).fetchall()
    
    return [dict(row) for row in rows]


def create_tenant_menu_config(
    tenant_id: int = None,
    menu_type: str = 'main',
    menu_name: str = 'Main Menu',
    config_json: Dict[str, Any] = None
) -> int:
    """Create a menu configuration for a tenant."""
    tenant_id = tenant_id or get_current_tenant_id()
    if not tenant_id:
        return None
    
    data = {
        'tenant_id': tenant_id,
        'menu_type': menu_type,
        'menu_name': menu_name,
        'config_json': json.dumps(config_json or {}),
        'is_active': 1
    }
    
    return tenant_create('tenant_menu_configs', data, tenant_id)


def create_tenant_menu_item(
    tenant_id: int = None,
    menu_config_id: int = None,
    item_data: Dict[str, Any] = None
) -> int:
    """Create a menu item for a tenant."""
    tenant_id = tenant_id or get_current_tenant_id()
    if not tenant_id or not menu_config_id or not item_data:
        return None
    
    data = {
        'tenant_id': tenant_id,
        'menu_config_id': menu_config_id,
        **item_data
    }
    
    return tenant_create('tenant_menu_items', data, tenant_id)


# ── Data Migration Functions ────────────────────────────────────────────

def migrate_existing_data_to_tenant(tenant_id: int):
    """Migrate all existing data to a specific tenant."""
    with get_db_context() as conn:
        tables = [
            'chat_history', 'faq_dataset', 'knowledge_base', 'products',
            'complaints', 'leads', 'orders', 'user_sessions', 'user_states'
        ]
        
        for table in tables:
            try:
                conn.execute(
                    f"UPDATE {table} SET tenant_id = ? WHERE tenant_id IS NULL",
                    (tenant_id,)
                )
            except Exception as e:
                logger.error(f"Migration failed for {table}: {e}")


# ── Initialize Multi-Tenant System ──────────────────────────────────────

# Auto-initialize when imported
initialize_multi_tenant_db()