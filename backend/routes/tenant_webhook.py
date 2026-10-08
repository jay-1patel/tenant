"""
Multi-Tenant Webhook Endpoint for WhatsApp Chatbot SaaS Platform

This module provides tenant-aware webhook handling where:
- Each company (tenant) can have their own WhatsApp business number
- Incoming messages are automatically routed to the correct tenant
- Each tenant's data is strictly isolated

Send2.digital webhook format that we expect:
    {
        "username": "tenant_username",     # This identifies the tenant
        "password": "tenant_password",     # For authentication
        "number": 918690983030,          # The recipient's WhatsApp number (identifies tenant)
        "msg_type": "text",
        "msg": "hello",                   # The user's message
        "time": "2026-08-22 10:00:00"
    }
"""

import asyncio
import logging
import json
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from pydantic import BaseModel

from backend.database_multi_tenant import (
    get_tenant_by_whatsapp_number, get_tenant_by_id,
    save_chat, set_current_tenant
)
from backend.services.tenant_orchestrator import process_tenant_message

logger = logging.getLogger("tenant_webhook")

router = APIRouter(prefix="/api/tenant", tags=["tenant_webhook"])


class TenantWebhookRequest(BaseModel):
    """Request body from tenant webhook."""
    username: str
    password: str
    number: int  # This is the incoming WhatsApp number (tenant identifier)
    msg_type: str = "text"
    msg: str = ""
    sender: Optional[str] = None  # The actual user's WA ID
    message_id: Optional[str] = None
    time: Optional[str] = None


class TenantMessageRequest(BaseModel):
    """Simplified request for direct tenant messaging."""
    tenant_id: Optional[int] = None
    tenant_slug: Optional[str] = None
    whatsapp_number: Optional[str] = None
    wa_id: str  # User's WhatsApp ID
    message: str
    message_type: str = "text"


@router.post("/webhook")
async def receive_tenant_webhook(request: TenantWebhookRequest):
    """
    Process an incoming WhatsApp message from any tenant.
    
    This is the main webhook endpoint that should be configured for all tenants.
    It identifies the tenant based on:
    1. The incoming WhatsApp number (from the 'number' field)
    2. Falls back to the username for tenant identification
    """
    from routing.config import SEND2_USERNAME, SEND2_PASSWORD
    
    # Identify the tenant based on the incoming number
    incoming_number = str(request.number).strip()
    tenant = get_tenant_by_whatsapp_number(incoming_number)
    
    if not tenant:
        logger.warning(f"Unknown tenant with WhatsApp number: {incoming_number}")
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Set tenant context for this request
    set_current_tenant(tenant)
    tenant_id = tenant['id']
    
    # Get the actual user's WA ID
    wa_id = request.sender or incoming_number
    
    # Get user's message
    text = (request.msg or "").strip()
    
    if not text:
        logger.warning(f"Empty message from {wa_id} to tenant {tenant_id}")
        return {"status": "ignored", "reason": "empty message"}
    
    logger.info(f"Tenant webhook: tenant={tenant['company_name']} from={wa_id} msg={text[:50]}...")
    
    try:
        # Process through the multi-tenant orchestrator
        result = await process_tenant_message(
            wa_id=wa_id,
            message=text,
            incoming_number=incoming_number,
            route=None  # Let orchestrator determine route
        )
        
        # Save the chat interaction
        save_chat(
            wa_id=wa_id,
            sender_name=request.sender or wa_id,
            message=text,
            response=result.get('response', ''),
            route=result.get('route', 'unknown'),
            tenant_id=tenant_id
        )
        
        # Prepare response
        response_data = {
            "status": "processed",
            "wa_id": wa_id,
            "tenant_id": tenant_id,
            "company": tenant['company_name'],
            "response": result.get('response', ''),
            "route": result.get('route', 'unknown'),
            "action": result.get('action', 'general')
        }
        
        # If there's a new state, include it
        if 'new_state' in result:
            response_data['new_state'] = result['new_state']
        
        logger.info(f"Processed message for tenant {tenant_id}: {response_data}")
        return response_data
        
    except Exception as e:
        logger.error(f"Tenant webhook failed for {wa_id} (tenant {tenant_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up tenant context
        set_current_tenant(None)


@router.post("/message")
async def send_tenant_message(request: TenantMessageRequest):
    """
    Process a message for a specific tenant using tenant_id or slug.
    
    This endpoint allows direct messaging to a specific tenant without
    coming through the standard webhook format.
    """
    tenant = None
    incoming_number = None
    
    # Identify tenant using the provided information
    if request.tenant_id:
        tenant = get_tenant_by_id(request.tenant_id)
    elif request.tenant_slug:
        from backend.database_multi_tenant import get_tenant_by_slug
        tenant = get_tenant_by_slug(request.tenant_slug)
    elif request.whatsapp_number:
        tenant = get_tenant_by_whatsapp_number(request.whatsapp_number)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Set tenant context
    set_current_tenant(tenant)
    tenant_id = tenant['id']
    
    # Process message
    try:
        result = await process_tenant_message(
            wa_id=request.wa_id,
            message=request.message,
            incoming_number=request.whatsapp_number or incoming_number,
            route=None
        )
        
        # Save chat
        save_chat(
            wa_id=request.wa_id,
            sender_name=request.wa_id,  # User ID as sender for now
            message=request.message,
            response=result.get('response', ''),
            route=result.get('route', 'unknown'),
            tenant_id=tenant_id
        )
        
        return {
            "status": "processed",
            "tenant_id": tenant_id,
            "company": tenant['company_name'],
            "response": result.get('response', ''),
            "route": result.get('route', 'unknown'),
            "action": result.get('action', 'general')
        }
        
    except Exception as e:
        logger.error(f"Message processing failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_current_tenant(None)


@router.post("/{tenant_slug}/webhook")
async def receive_slug_tenant_webhook(
    tenant_slug: str,
    request: TenantWebhookRequest
):
    """
    Process an incoming WhatsApp message for a tenant identified by slug.
    
    This endpoint allows for webhook URLs like: /api/tenant/company-name/webhook
    """
    from backend.database_multi_tenant import get_tenant_by_slug
    
    # Find tenant by slug
    tenant = get_tenant_by_slug(tenant_slug)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Verify that the incoming number matches the tenant's configured number
    if tenant['whatsapp_number'] and str(request.number) != tenant['whatsapp_number']:
        logger.warning(f"Number mismatch for tenant {tenant_slug}: expected {tenant['whatsapp_number']}, got {request.number}")
        # Proceed anyway, but log the warning
    
    # Set tenant context
    set_current_tenant(tenant)
    tenant_id = tenant['id']
    
    # Process message
    try:
        wa_id = request.sender or str(request.number)
        text = (request.msg or "").strip()
        
        result = await process_tenant_message(
            wa_id=wa_id,
            message=text,
            incoming_number=tenant['whatsapp_number'],
            route=None
        )
        
        # Save chat
        save_chat(
            wa_id=wa_id,
            sender_name=request.sender or wa_id,
            message=text,
            response=result.get('response', ''),
            route=result.get('route', 'unknown'),
            tenant_id=tenant_id
        )
        
        return {
            "status": "processed",
            "tenant_slug": tenant_slug,
            "tenant_id": tenant_id,
            "company": tenant['company_name'],
            "response": result.get('response', ''),
            "route": result.get('route', 'unknown')
        }
        
    except Exception as e:
        logger.error(f"Webhook failed for tenant {tenant_slug}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_current_tenant(None)


@router.get("/tenants")
async def list_available_tenants():
    """List all available tenants for debugging and management."""
    from backend.database_multi_tenant import list_tenants
    
    tenants = list_tenants(is_active=True)
    
    # Return simplified information
    return {
        "tenants": [
            {
                "id": t['id'],
                "company_name": t['company_name'],
                "slug": t['slug'],
                "industry": t['industry_type'],
                "active": bool(t['is_active'])
            }
            for t in tenants
        ],
        "total": len(tenants)
    }


@router.get("/tenants/{tenant_id}/config")
async def get_tenant_config(tenant_id: int):
    """Get configuration for a specific tenant."""
    from backend.services.tenant_orchestrator import get_tenant_config
    
    config = await get_tenant_config(tenant_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Remove sensitive information
    safe_config = {k: v for k, v in config.items() if k not in ['send2_password']}
    
    return safe_config


@router.post("/tenants/{tenant_id}/message")
async def send_message_to_tenant(
    tenant_id: int,
    wa_id: str,
    message: str,
    route: Optional[str] = None
):
    """
    Send a message to a specific tenant as if it came from a user.
    
    This is useful for testing and for system-generated messages.
    """
    from backend.database_multi_tenant import get_tenant_by_id
    
    tenant = get_tenant_by_id(tenant_id)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Set tenant context
    set_current_tenant(tenant)
    
    try:
        result = await process_tenant_message(
            wa_id=wa_id,
            message=message,
            incoming_number=tenant.get('whatsapp_number'),
            route=route
        )
        
        return {
            "status": "processed",
            "tenant_id": tenant_id,
            "response": result.get('response', ''),
            "route": result.get('route', 'unknown')
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_current_tenant(None)


# ── Middleware for Tenant Identification ──────────────────────────────

async def get_tenant_from_request(
    request: Request,
    x_tenant_id: Optional[str] = None,
    x_tenant_slug: Optional[str] = None,
    x_whatsapp_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Middleware to identify tenant from request headers or other sources.
    
    Can identify tenant from:
    - X-Tenant-ID header
    - X-Tenant-Slug header  
    - X-WhatsApp-Number header
    - Request body data
    """
    # Try headers first
    if x_tenant_id:
        tenant = get_tenant_by_id(int(x_tenant_id))
        if tenant:
            return tenant
    
    if x_tenant_slug:
        from backend.database_multi_tenant import get_tenant_by_slug
        tenant = get_tenant_by_slug(x_tenant_slug)
        if tenant:
            return tenant
    
    if x_whatsapp_number:
        tenant = get_tenant_by_whatsapp_number(x_whatsapp_number)
        if tenant:
            return tenant
    
    # Try to parse JSON body if available
    try:
        body = await request.json()
        if isinstance(body, dict):
            if 'tenant_id' in body:
                tenant = get_tenant_by_id(body['tenant_id'])
                if tenant:
                    return tenant
            if 'tenant_slug' in body:
                from backend.database_multi_tenant import get_tenant_by_slug
                tenant = get_tenant_by_slug(body['tenant_slug'])
                if tenant:
                    return tenant
            if 'whatsapp_number' in body:
                tenant = get_tenant_by_whatsapp_number(body['whatsapp_number'])
                if tenant:
                    return tenant
            if 'username' in body and 'password' in body:
                # Check if username/password match a tenant
                tenants = list_tenants()
                for t in tenants:
                    if (t.get('send2_username') == body['username'] and 
                        t.get('send2_password') == body['password']):
                        return t
    except Exception:
        pass
    
    # No tenant identified
    raise HTTPException(status_code=400, detail="Cannot identify tenant from request")


@router.post("/middleware/webhook")
async def handle_middleware_webhook(
    request: Request,
    tenant: Dict[str, Any] = Depends(get_tenant_from_request)
):
    """
    Generic webhook handler that uses middleware for tenant identification.
    
    This provides maximum flexibility for different webhook formats.
    """
    set_current_tenant(tenant)
    
    try:
        body = await request.json()
        
        # Extract message data from various format
        wa_id = body.get('wa_id') or body.get('from') or body.get('sender')
        message = body.get('msg') or body.get('message') or body.get('text')
        incoming_number = body.get('number') or body.get('whatsapp_number')
        
        if not wa_id or not message:
            raise HTTPException(status_code=400, detail="Missing wa_id or message")
        
        result = await process_tenant_message(
            wa_id=wa_id,
            message=message,
            incoming_number=incoming_number,
            route=None
        )
        
        return {
            "status": "processed",
            "tenant": tenant['company_name'],
            "response": result.get('response', ''),
            "route": result.get('route', 'unknown')
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        set_current_tenant(None)