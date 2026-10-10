"""
Multi-Tenant Admin API for WhatsApp Chatbot SaaS Platform

This module provides endpoints for:
- Tenant registration and management
- Document upload and processing
- Menu customization
- System configuration

These endpoints are typically used by:
1. Super admins (platform administrators)
2. Company admins (individual tenant administrators)
"""

import os
import json
import logging
import uuid
from typing import Optional, Dict, Any, List, UploadFile, Tuple
from datetime import datetime

from fastapi import (
    APIRouter, HTTPException, Depends, Request, 
    UploadFile, File, Form, Query
)
from pydantic import BaseModel

from backend.database_multi_tenant import (
    create_tenant, update_tenant, deactivate_tenant, delete_tenant,
    list_tenants, get_tenant_by_id, get_tenant_by_slug,
    get_tenant_by_whatsapp_number, tenant_query, get_current_tenant_id
)
from backend.database import get_db_context, record_admin_audit_event, get_db
from backend.services.tenant_menu_service import get_tenant_menu_service
from backend.kb.services.tenant_rag import add_document_to_tenant

logger = logging.getLogger("tenant_admin")

router = APIRouter(prefix="/api/admin/tenants", tags=["tenant_admin"])


# ── Pydantic Models ───────────────────────────────────────────────────

class TenantCreateRequest(BaseModel):
    company_name: str
    slug: str
    whatsapp_number: Optional[str] = None
    send2_username: Optional[str] = None
    send2_password: Optional[str] = None
    system_prompt: Optional[str] = None
    brand_color: Optional[str] = "#25D366"
    logo_url: Optional[str] = None
    domain: Optional[str] = None
    industry_type: Optional[str] = "general"
    welcome_message: Optional[str] = "Welcome! How can I help you today?"


class TenantUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    slug: Optional[str] = None
    whatsapp_number: Optional[str] = None
    send2_username: Optional[str] = None
    send2_password: Optional[str] = None
    system_prompt: Optional[str] = None
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    domain: Optional[str] = None
    industry_type: Optional[str] = None
    welcome_message: Optional[str] = None
    is_active: Optional[bool] = None


class MenuItemCreateRequest(BaseModel):
    menu_type: str = "main"
    title: str
    description: Optional[str] = None
    section: Optional[str] = "General"
    icon: Optional[str] = None
    action_type: Optional[str] = "message"
    action_payload: Optional[str] = None
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True


class MenuSectionRequest(BaseModel):
    title: str
    items: List[MenuItemCreateRequest]


class MenuConfigRequest(BaseModel):
    menu_name: str = "Main Menu"
    button_text: str = "Select an option"
    sections: List[MenuSectionRequest]


class DocumentUploadResponse(BaseModel):
    tenant_id: int
    document_id: int
    filename: str
    content_length: int
    chunks_created: int
    status: str


# ── Dependencies ────────────────────────────────────────────────────────

async def get_super_admin(request: Request):
    """Dependency to verify super admin access."""
    # In a real system, this would check authentication/authorization
    # For now, we'll just return a dummy admin
    return {"username": "super_admin", "role": "super_admin"}


async def get_tenant_admin(
    request: Request,
    tenant_id: Optional[int] = Query(None),
    tenant_slug: Optional[str] = Query(None)
):
    """Dependency to identify and verify tenant admin."""
    # In a real system, this would check if the authenticated user
    # is an admin for the specified tenant
    
    # Try to identify tenant
    tenant = None
    if tenant_id:
        tenant = get_tenant_by_id(tenant_id)
    elif tenant_slug:
        tenant = get_tenant_by_slug(tenant_slug)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Return tenant info along with admin info
    return {
        "admin": {"username": "tenant_admin", "role": "admin"},
        "tenant": tenant
    }


# ── Tenant Management Endpoints ─────────────────────────────────────────

@router.post("/register")
async def register_tenant(
    tenant_data: TenantCreateRequest,
    super_admin: Dict = Depends(get_super_admin)
):
    """
    Register a new tenant/company.
    
    Only super admins can create new tenants.
    """
    try:
        # Check if slug already exists
        existing = get_tenant_by_slug(tenant_data.slug)
        if existing:
            raise HTTPException(status_code=400, detail="Tenant slug already exists")
        
        # Create the tenant
        tenant_id = create_tenant(
            company_name=tenant_data.company_name,
            slug=tenant_data.slug,
            whatsapp_number=tenant_data.whatsapp_number,
            send2_username=tenant_data.send2_username,
            send2_password=tenant_data.send2_password,
            system_prompt=tenant_data.system_prompt or 
                f"You are the AI assistant for {tenant_data.company_name}, a premier company. "
                f"Your goal is to help users with their inquiries about {tenant_data.company_name}. "
                f"Be professional, helpful, and concise.",
            brand_color=tenant_data.brand_color,
            logo_url=tenant_data.logo_url,
            domain=tenant_data.domain,
            industry_type=tenant_data.industry_type,
            welcome_message=tenant_data.welcome_message
        )
        
        with get_db_context() as conn:
            try:
                record_admin_audit_event(
                    conn,
                    action="tenant_created",
                    actor=super_admin,
                    resource_type="tenant",
                    resource_id=tenant_id,
                    tenant_id=str(tenant_id),
                    details={"created_tenant": tenant_data.dict()}
                )
            except Exception as e:
                logger.error(f"Audit log failed: {e}")
                
        logger.info(f"Registered new tenant: {tenant_data.company_name} (ID: {tenant_id})")
        
        return {
            "status": "success",
            "tenant_id": tenant_id,
            "company_name": tenant_data.company_name,
            "slug": tenant_data.slug,
            "whatsapp_number": tenant_data.whatsapp_number,
            "message": f"Tenant '{tenant_data.company_name}' registered successfully!"
        }
        
    except Exception as e:
        logger.error(f"Failed to register tenant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_tenants_endpoint(
    is_active: Optional[bool] = Query(True),
    limit: Optional[int] = Query(100),
    offset: Optional[int] = Query(0),
    super_admin: Dict = Depends(get_super_admin)
):
    """
    List all tenants.
    
    Only super admins can list all tenants.
    """
    try:
        tenants = list_tenants(
            is_active=is_active,
            limit=limit,
            offset=offset
        )
        
        return {
            "tenants": [
                {
                    "id": t['id'],
                    "company_name": t['company_name'],
                    "slug": t['slug'],
                    "whatsapp_number": t['whatsapp_number'],
                    "industry_type": t['industry_type'],
                    "is_active": bool(t['is_active']),
                    "created_at": t['created_at']
                }
                for t in tenants
            ],
            "total": len(tenants),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"Failed to list tenants: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tenant_id}", response_model=Dict[str, Any])
async def get_tenant_details(
    tenant_id: int,
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Get detailed information about a specific tenant.
    
    Accessible by super admins and tenant admins.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        # The dependency already found the tenant, but let's verify
        tenant = get_tenant_by_id(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
    
    # Remove sensitive data
    tenant_safe = {k: v for k, v in tenant.items() if k != 'send2_password'}
    
    return tenant_safe


@router.put("/{tenant_id}")
async def update_tenant_details(
    tenant_id: int,
    tenant_data: TenantUpdateRequest,
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Update tenant details.
    
    Only accessible by tenant admins or super admins.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        tenant = get_tenant_by_id(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
    
    try:
        # Remove None values
        update_data = {k: v for k, v in tenant_data.dict().items() if v is not None}
        
        success = update_tenant(tenant_id, **update_data)
        
        if success:
            # Return updated tenant info
            updated_tenant = get_tenant_by_id(tenant_id)
            with get_db_context() as conn:
                try:
                    record_admin_audit_event(
                        conn,
                        action="tenant_updated",
                        actor=tenant_admin.get('admin'),
                        resource_type="tenant",
                        resource_id=tenant_id,
                        tenant_id=str(tenant_id),
                        details={"before_state": tenant, "after_state": updated_tenant}
                    )
                except Exception as e:
                    logger.error(f"Audit log failed: {e}")
            updated_tenant_safe = {k: v for k, v in updated_tenant.items() if k != 'send2_password'}
            
            logger.info(f"Updated tenant {tenant_id}")
            return updated_tenant_safe
        else:
            raise HTTPException(status_code=500, detail="Failed to update tenant")
            
    except Exception as e:
        logger.error(f"Failed to update tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant_id}")
async def delete_tenant_endpoint(
    tenant_id: int,
    super_admin: Dict = Depends(get_super_admin)
):
    """
    Delete a tenant and all their data.
    
    Only accessible by super admins!
    This permanently removes all tenant data.
    """
    try:
        tenant_to_delete = get_tenant_by_id(tenant_id)
        success = delete_tenant(tenant_id)
        
        if success:
            with get_db_context() as conn:
                try:
                    record_admin_audit_event(
                        conn,
                        action="tenant_deleted",
                        actor=super_admin,
                        resource_type="tenant",
                        resource_id=tenant_id,
                        tenant_id=str(tenant_id),
                        details={"deleted_tenant": tenant_to_delete}
                    )
                except Exception as e:
                    logger.error(f"Audit log failed: {e}")
            logger.info(f"Deleted tenant {tenant_id} and all associated data")
            return {
                "status": "success",
                "message": f"Tenant {tenant_id} deleted successfully",
                "tenant_id": tenant_id
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to delete tenant")
            
    except Exception as e:
        logger.error(f"Failed to delete tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_id}/deactivate")
async def deactivate_tenant_endpoint(
    tenant_id: int,
    tenant_admin: Dict = Depends(get_super_admin)
):
    """
    Deactivate a tenant (soft delete).
    
    Deactivated tenants cannot receive or send messages but their data is preserved.
    """
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    try:
        success = deactivate_tenant(tenant_id)
        
        if success:
            with get_db_context() as conn:
                try:
                    record_admin_audit_event(
                        conn,
                        action="tenant_deactivated",
                        actor=tenant_admin,
                        resource_type="tenant",
                        resource_id=tenant_id,
                        tenant_id=str(tenant_id),
                        details={"before_state": tenant}
                    )
                except Exception as e:
                    logger.error(f"Audit log failed: {e}")
            logger.info(f"Deactivated tenant {tenant_id}")
            return {
                "status": "success",
                "message": f"Tenant {tenant_id} deactivated",
                "tenant_id": tenant_id
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to deactivate tenant")
            
    except Exception as e:
        logger.error(f"Failed to deactivate tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Document Management Endpoints ─────────────────────────────────────────

@router.post("/{tenant_id}/kb/upload")
async def tenant_upload_kb_document(
    tenant_id: int,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: Optional[str] = Form("general"),
    source: Optional[str] = Form(None),
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Upload a document to a tenant's knowledge base.
    
    Supports PDF, TXT, and DOCX files.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        tenant = get_tenant_by_id(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if tenant_admin['admin']['role'] != 'super_admin':
            raise HTTPException(status_code=403, detail="Permission denied")
    
    # Check file type
    valid_extensions = ['.pdf', '.txt', '.doc', '.docx']
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    if file_extension not in valid_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type {file_extension}. Supported: {', '.join(valid_extensions)}"
        )
    
    try:
        # Read file content
        content = await file.read()
        
        if not content or len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        
        # Extract text from the file
        text_content = extract_text_from_file(content, file.filename)
        
        if not text_content or not text_content.strip():
            raise HTTPException(status_code=400, detail="No text content found in file")
        
        # Use filename as title if not provided
        if not title:
            title = os.path.splitext(file.filename)[0]
        
        # Add to tenant's knowledge base
        document_id = add_document_to_tenant(
            tenant_id=tenant_id,
            title=title,
            content=text_content,
            source=source or file.filename,
            category=category
        )
        
        # Create chunks
        from kb.services.tenant_rag import TenantRAGService
        rag_service = TenantRAGService(tenant_id)
        chunks = rag_service._chunk_content(text_content)
        
        # Rebuild the tenant's search index
        rag_service.build_tenant_index(force_rebuild=True)
        
        logger.info(f"Uploaded KB document '{title}' to tenant {tenant_id}")
        
        return {
            "status": "success",
            "tenant_id": tenant_id,
            "document_id": document_id,
            "filename": file.filename,
            "title": title,
            "content_length": len(text_content),
            "chunks_created": len(chunks),
            "category": category,
            "source": source or file.filename
        }
        
    except Exception as e:
        logger.error(f"KB upload failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_id}/kb/upload-batch")
async def tenant_upload_kb_batch(
    tenant_id: int,
    files: List[UploadFile] = File(...),
    category: Optional[str] = Form("general"),
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Upload multiple documents to a tenant's knowledge base at once.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    results = []
    errors = []
    
    for file in files:
        try:
            content = await file.read()
            text_content = extract_text_from_file(content, file.filename)
            
            if text_content and text_content.strip():
                title = os.path.splitext(file.filename)[0]
                
                document_id = add_document_to_tenant(
                    tenant_id=tenant_id,
                    title=title,
                    content=text_content,
                    source=file.filename,
                    category=category
                )
                
                results.append({
                    "filename": file.filename,
                    "document_id": document_id,
                    "status": "success"
                })
            else:
                errors.append({
                    "filename": file.filename,
                    "error": "No text content found"
                })
                
        except Exception as e:
            errors.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    if results:
        # Rebuild the tenant's search index
        from kb.services.tenant_rag import TenantRAGService
        rag_service = TenantRAGService(tenant_id)
        rag_service.build_tenant_index(force_rebuild=True)
    
    return {
        "status": "completed",
        "tenant_id": tenant_id,
        "uploaded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors
    }


@router.get("/{tenant_id}/kb")
async def get_tenant_kb(
    tenant_id: int,
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Get information about a tenant's knowledge base.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    from backend.database_multi_tenant import get_tenant_knowledge_base
    
    kb_entries = get_tenant_knowledge_base(tenant_id)
    
    return {
        "tenant_id": tenant_id,
        "total_documents": len(kb_entries),
        "documents": [
            {
                "id": entry['id'],
                "title": entry['title'],
                "source": entry['source'],
                "category": entry['category'],
                "tagcount": len(entry.get('tags', '')),
                "created_at": entry['created_at']
            }
            for entry in kb_entries
        ]
    }


# ── Menu Management Endpoints ────────────────────────────────────────────

@router.get("/{tenant_id}/menus")
async def get_tenant_menus(
    tenant_id: int,
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Get all menu configurations for a tenant.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    menu_service = get_tenant_menu_service(tenant_id)
    
    try:
        menus = menu_service.get_all_tenant_menu_configs()
        
        return {
            "tenant_id": tenant_id,
            "menus": menus,
            "count": len(menus)
        }
        
    except Exception as e:
        logger.error(f"Failed to get menus for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tenant_id}/menus/{menu_type}")
async def get_tenant_menu(
    tenant_id: int,
    menu_type: str = "main",
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Get a specific menu configuration for a tenant.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    menu_service = get_tenant_menu_service(tenant_id)
    
    try:
        menu_config = menu_service.get_menu_config(menu_type)
        
        if not menu_config:
            raise HTTPException(status_code=404, detail=f"Menu type '{menu_type}' not found")
        
        return {
            "tenant_id": tenant_id,
            "menu_type": menu_type,
            "config": menu_config
        }
        
    except Exception as e:
        logger.error(f"Failed to get menu {menu_type} for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_id}/menus")
async def create_tenant_menu(
    tenant_id: int,
    menu_data: MenuConfigRequest,
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Create or update a menu configuration for a tenant.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    menu_service = get_tenant_menu_service(tenant_id)
    
    try:
        # Convert menu data to sections format
        sections_data = []
        for section in menu_data.sections:
            section_data = {
                "title": section.title,
                "items": []
            }
            for item in section.items:
                section_data["items"].append({
                    "id": item.id,
                    "title": item.title,
                    "description": item.description or "",
                    "action": item.action_type or "message",
                    "payload": item.action_payload or item.id,
                    "icon": item.icon or "",
                    "sort_order": item.sort_order or 0,
                    "is_active": item.is_active if item.is_active is not None else True
                })
            sections_data.append(section_data)
        
        # Create or update the menu
        menu_config_id = menu_service.create_menu(
            menu_type=menu_data.menu_type or "main",
            menu_name=menu_data.menu_name,
            sections=sections_data
        )
        
        logger.info(f"Created/updated menu for tenant {tenant_id}")
        
        return {
            "status": "success",
            "tenant_id": tenant_id,
            "menu_config_id": menu_config_id,
            "menu_type": menu_data.menu_type or "main",
            "menu_name": menu_data.menu_name
        }
        
    except Exception as e:
        logger.error(f"Failed to create menu for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_id}/menus/preview")
async def preview_tenant_menu(
    tenant_id: int,
    menu_data: MenuConfigRequest,
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Preview how a menu configuration will look as a WhatsApp menu.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    menu_service = get_tenant_menu_service(tenant_id)
    
    try:
        # Convert menu data to sections format
        sections_data = []
        for section in menu_data.sections:
            section_data = {
                "title": section.title,
                "items": []
            }
            for item in section.items:
                section_data["items"].append({
                    "id": item.id,
                    "title": item.title,
                    "description": item.description or "",
                    "action": item.action_type or "message",
                    "payload": item.action_payload or item.id,
                    "icon": item.icon or "",
                    "sort_order": item.sort_order or 0,
                    "is_active": item.is_active if item.is_active is not None else True
                })
            sections_data.append(section_data)
        
        # Create a temporary menu config for preview
        menu_config = {
            "menu_name": menu_data.menu_name,
            "button_text": menu_data.button_text or "Select an option",
            "sections": sections_data
        }
        
        # Build the WhatsApp menu format
        whatsapp_menu = {
            "button_text": menu_config['button_text'],
            "sections": []
        }
        
        for section in menu_config['sections']:
            whatsapp_section = {
                "title": section['title'],
                "rows": []
            }
            for item in section['items']:
                if item.get('is_active', True):
                    whatsapp_section['rows'].append({
                        "id": item['id'],
                        "title": item['title'],
                        "description": item.get('description', '')
                    })
            
            if whatsapp_section['rows']:  # Only include sections with rows
                whatsapp_menu['sections'].append(whatsapp_section)
        
        return {
            "preview": whatsapp_menu,
            "menu_name": menu_config['menu_name'],
            "total_sections": len(whatsapp_menu['sections']),
            "total_items": sum(len(s['rows']) for s in whatsapp_menu['sections'])
        }
        
    except Exception as e:
        logger.error(f"Menu preview failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Tenant Onboarding Endpoints ────────────────────────────────────────

@router.post("/{tenant_id}/onboard")
async def onboard_tenant(
    tenant_id: int,
    onboarding_data: Dict[str, Any],
    tenant_admin: Dict = Depends(get_tenant_admin)
):
    """
    Complete tenant onboarding with initial configuration.
    """
    tenant = tenant_admin['tenant']
    
    if tenant['id'] != tenant_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    try:
        # Update tenant with onboarding data
        update_data = {}
        
        if 'company_name' in onboarding_data:
            update_data['company_name'] = onboarding_data['company_name']
        if 'system_prompt' in onboarding_data:
            update_data['system_prompt'] = onboarding_data['system_prompt']
        if 'welcome_message' in onboarding_data:
            update_data['welcome_message'] = onboarding_data['welcome_message']
        if 'industry_type' in onboarding_data:
            update_data['industry_type'] = onboarding_data['industry_type']
        if 'brand_color' in onboarding_data:
            update_data['brand_color'] = onboarding_data['brand_color']
        
        update_tenant(tenant_id, **update_data)
        
        # Create initial menu if provided
        if 'menu' in onboarding_data:
            menu_data = onboarding_data['menu']
            if isinstance(menu_data, dict):
                sections_data = []
                for section_title, items in menu_data.items():
                    section_data = {
                        "title": section_title,
                        "items": []
                    }
                    for item in items:
                        if isinstance(item, str):
                            section_data['items'].append({
                                "id": item.lower().replace(' ', '_'),
                                "title": item,
                                "description": "",
                                "action": "message",
                                "payload": item.lower().replace(' ', '_')
                            })
                        elif isinstance(item, dict):
                            section_data['items'].append({
                                "id": item.get('id', item.get('title', '').lower().replace(' ', '_')),
                                "title": item.get('title', ''),
                                "description": item.get('description', ''),
                                "action": item.get('action', 'message'),
                                "payload": item.get('payload', item.get('title', '').lower().replace(' ', '_'))
                            })
                    sections_data.append(section_data)
                
                menu_service = get_tenant_menu_service(tenant_id)
                menu_service.create_menu(
                    menu_type='main',
                    menu_name='Main Menu',
                    sections=sections_data
                )
        
        logger.info(f"Completed onboarding for tenant {tenant_id}")
        
        return {
            "status": "success",
            "tenant_id": tenant_id,
            "message": "Onboarding completed successfully"
        }
        
    except Exception as e:
        logger.error(f"Onboarding failed for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Helper Functions ────────────────────────────────────────────────────────

def extract_text_from_file(content: bytes, filename: str) -> str:
    """Extract text from various file types."""
    try:
        # Try to detect encoding
        text = content.decode('utf-8')
        if is_text_file(text):
            return text
        
        # If it'sbinary, it might be a PDF or DOCX
        filename_lower = filename.lower()
        
        if filename_lower.endswith('.txt'):
            return content.decode('utf-8', errors='replace')
        
        elif filename_lower.endswith('.pdf'):
            return extract_text_from_pdf(content)
        
        elif filename_lower.endswith(('.doc', '.docx')):
            return extract_text_from_docx(content)
        
        else:
            # Try to decode as UTF-8 text
            return content.decode('utf-8', errors='replace')
            
    except Exception as e:
        logger.error(f"Failed to extract text from file {filename}: {e}")
        return ""


def is_text_file(content: str) -> bool:
    """Check if content appears to be plain text."""
    # Simple check - if it doesn't contain many binary-looking bytes
    binary_chars = 0
    for char in content[:1000]:  # Check first 1000 characters
        if ord(char) < 32 and char not in ['\n', '\r', '\t']:
            binary_chars += 1
        if binary_chars > 10:  # More than 1% binary chars
            return False
    return True


def extract_text_from_pdf(content: bytes) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    try:
        import fitz
        import io
        
        pdf_document = fitz.open(stream=io.BytesIO(content))
        text_parts = []
        
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            text = page.get_text()
            text_parts.append(text)
        
        pdf_document.close()
        
        return '\n\n'.join(text_parts)
        
    except ImportError:
        logger.error("PyMuPDF (fitz) not installed. PDF extraction requires: pip install pymupdf")
        return ""
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def extract_text_from_docx(content: bytes) -> str:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        import io
        
        doc = Document(io.BytesIO(content))
        text_parts = []
        
        for paragraph in doc.paragraphs:
            text_parts.append(paragraph.text)
        
        return '\n'.join(text_parts)
        
    except ImportError:
        logger.error("python-docx not installed. DOCX extraction requires: pip install python-docx")
        return ""
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""