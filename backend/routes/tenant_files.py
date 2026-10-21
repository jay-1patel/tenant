"""Tenant-scoped file management.

The global ``/api/admin/files`` routes serve a single-tenant deployment. This
router is the tenant-owned path the console uses: every file row carries the
tenant that uploaded it, so a tenant console lists only its own knowledge base,
FAQ and catalogue files.

    GET    /api/admin/tenants/{tenant_id}/files
    POST   /api/admin/tenants/{tenant_id}/files/upload
    GET    /api/admin/tenants/{tenant_id}/files/{filename}/preview
    GET    /api/admin/tenants/{tenant_id}/files/{filename}/download
    DELETE /api/admin/tenants/{tenant_id}/files/{filename}

Uploads share ``admin.run_upload`` with the global path, so extraction and index
rebuilding exist once; the tenant id is threaded into every stored row and chunk.
"""

import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials

from database import (
    delete_admin_file,
    delete_file_chunks,
    delete_knowledge_base_file,
    get_admin_file,
    list_admin_files,
)
from routes.admin import (
    SUPPORTED,
    UPLOAD_DIR,
    _find_uploaded_file,
    _guess_media_type,
    run_upload,
)
from routes.auth import (
    get_current_admin,
    get_tenant_principal,
    has_permission,
    require_tenant_access,
    security,
)

logger = logging.getLogger("tenant_files")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}", tags=["tenant-files"])


def _require(perm: str):
    """Admin (or the tenant's own token) with ``perm`` may proceed."""

    def dependency(
        request: Request,
        tenant_id: str,
        principal: dict = Depends(require_tenant_access()),
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        if principal.get("type") == "tenant":
            return principal
        if not has_permission(get_current_admin(request, credentials), perm):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action",
            )
        return principal

    return dependency


def _resolve_uploader(
    request: Request,
    principal: dict,
    credentials: HTTPAuthorizationCredentials,
) -> dict:
    """The admin dict ``run_upload`` checks upload permissions against.

    A tenant token is, by construction, authorized for its own tenant, so it is
    represented as a super admin of that tenant.
    """
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(principal)
    except Exception:
        pass
    if principal.get("type") == "tenant":
        return {
            "id": None,
            "type": "tenant_token",
            "token_id": principal.get("token_id"),
            "label": principal.get("label") or "tenant",
            "username": principal.get("label") or "tenant",
            "role": "super_admin",
            "tenant_id": principal.get("tenant_id"),
            "permissions": {},
        }
    return get_current_admin(request, credentials)


@router.get("/files")
def list_tenant_files(
    tenant_id: str,
    module: str = Query(None),
    search: str = Query(None),
    principal: dict = Depends(_require("view_files")),
):
    files = list_admin_files(tenant_id=tenant_id)
    if module:
        files = [f for f in files if f.get("module") == module]
    if search:
        needle = search.lower()
        files = [f for f in files if needle in (f.get("name") or "").lower()]
    return {"files": files}


@router.post("/files/upload")
async def upload_tenant_file(
    request: Request,
    tenant_id: str,
    module: str = Query("faq"),
    url: str = Query(None),
    media_type: str = Query(None),
    principal: dict = Depends(require_tenant_access()),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    uploader = _resolve_uploader(request, principal, credentials)
    return await run_upload(request, module, url, media_type, uploader, tenant_id=tenant_id)


@router.post("/files/auto-bifurcate")
async def auto_bifurcate_tenant_files(
    request: Request,
    tenant_id: str,
    auto_publish: bool = Query(True),
    principal: dict = Depends(require_tenant_access()),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Auto-bifurcate and configure uploaded client documents into their proper places.

    Accepts multi-file payloads (JSON base64 or multipart) of PDFs, Word files,
    spreadsheets, and text. Extracted data is automatically parsed, classified,
    and configured into:
      1. Brand Profile & Hours -> clients/{tenant_id}/config.json & TenantProfile
      2. WhatsApp Interactive Menu -> MenuButtons (<=24 title, <=72 desc)
      3. Conversational Intents & Flows -> IntentSpec
      4. Products & Catalog -> SQLite products table
      5. Knowledge Base & FAQs -> Markdown files, Chunks, Vector RAG Index
    """
    import base64
    uploader = _resolve_uploader(request, principal, credentials)
    content_type = request.headers.get("content-type", "")
    files_payload = []

    if "application/json" in content_type:
        body = await request.json()
        if "files" in body and isinstance(body["files"], list):
            files_payload = body["files"]
        elif "filename" in body and "content" in body:
            files_payload = [body]
        auto_publish = body.get("auto_publish", auto_publish)
    elif "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_files = form.getlist("files") or ([form.get("file")] if form.get("file") else [])
        for uf in uploaded_files:
            if uf and hasattr(uf, "read"):
                fname = uf.filename or "uploaded_doc"
                raw = await uf.read()
                files_payload.append({
                    "filename": fname,
                    "content": base64.b64encode(raw).decode("ascii"),
                    "media_type": getattr(uf, "content_type", None),
                })
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    if not files_payload:
        raise HTTPException(status_code=400, detail="No files provided for auto-bifurcation")

    try:
        from services.auto_bifurcator import AutoBifurcator
    except ImportError:
        from backend.services.auto_bifurcator import AutoBifurcator

    bifurcator = AutoBifurcator(tenant_id=tenant_id, actor=uploader)
    try:
        result = bifurcator.process_files(files_payload, auto_publish=auto_publish)
        return result
    except Exception as exc:
        logger.error("Auto-bifurcation failed for tenant %s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Auto-bifurcation failed: {exc}")


@router.post("/files/bifurcate-existing")
async def auto_bifurcate_existing_files(
    request: Request,
    tenant_id: str,
    principal: dict = Depends(require_tenant_access()),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Run auto-bifurcation on files already uploaded to this tenant's library."""
    import base64
    uploader = _resolve_uploader(request, principal, credentials)
    body = await request.json() if "application/json" in request.headers.get("content-type", "") else {}
    target_filenames = body.get("filenames")  # None means all files for tenant
    auto_publish = body.get("auto_publish", True)

    tenant_files = list_admin_files(tenant_id=tenant_id)
    if target_filenames:
        target_set = set(target_filenames)
        tenant_files = [f for f in tenant_files if f.get("name") in target_set]

    if not tenant_files:
        raise HTTPException(status_code=404, detail="No matching uploaded files found to bifurcate")

    files_payload = []
    for tf in tenant_files:
        fname = tf.get("name")
        fpath = _find_uploaded_file(fname)
        if fpath and os.path.exists(fpath):
            with open(fpath, "rb") as disk_f:
                raw_bytes = disk_f.read()
                files_payload.append({
                    "filename": fname,
                    "content": base64.b64encode(raw_bytes).decode("ascii"),
                    "media_type": _guess_media_type(fname),
                })

    if not files_payload:
        raise HTTPException(status_code=400, detail="Could not read content from existing files on disk")

    try:
        from services.auto_bifurcator import AutoBifurcator
    except ImportError:
        from backend.services.auto_bifurcator import AutoBifurcator

    bifurcator = AutoBifurcator(tenant_id=tenant_id, actor=uploader)
    try:
        result = bifurcator.process_files(files_payload, auto_publish=auto_publish)
        return result
    except Exception as exc:
        logger.error("Auto-bifurcation on existing files failed for tenant %s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Auto-bifurcation failed: {exc}")



@router.get("/files/{filename}/preview")
def preview_tenant_file(
    tenant_id: str,
    filename: str,
    principal: dict = Depends(_require("view_files")),
):
    # The metadata row is the tenancy check: a filename that exists on disk but
    # belongs to another tenant must not be readable through this path.
    if not get_admin_file(filename, tenant_id=tenant_id):
        raise HTTPException(status_code=404, detail="File not found for this tenant")
    filepath = _find_uploaded_file(filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="File not found on disk")
    media_type = _guess_media_type(filename)
    return FileResponse(
        filepath,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/files/{filename}/download")
def download_tenant_file(
    tenant_id: str,
    filename: str,
    principal: dict = Depends(_require("view_files")),
):
    if not get_admin_file(filename, tenant_id=tenant_id):
        raise HTTPException(status_code=404, detail="File not found for this tenant")
    filepath = _find_uploaded_file(filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="File not found on disk")
    media_type = _guess_media_type(filename)
    return FileResponse(
        filepath,
        filename=filename,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/files/{filename}")
def delete_tenant_file(
    tenant_id: str,
    filename: str,
    principal: dict = Depends(_require("delete_files")),
):
    if not get_admin_file(filename, tenant_id=tenant_id):
        raise HTTPException(status_code=404, detail="File not found for this tenant")
    actor = {
        **principal,
        "username": principal.get("username") or principal.get("label") or "tenant",
        "tenant_id": tenant_id,
    }
    deleted_faq = delete_file_chunks(filename, tenant_id=tenant_id)
    deleted_kb = delete_knowledge_base_file(filename, tenant_id=tenant_id)
    delete_admin_file(filename, tenant_id=tenant_id, actor=actor)
    filepath = _find_uploaded_file(filename)
    if filepath:
        try:
            os.remove(filepath)
        except OSError:
            pass
    logger.info(
        "TENANT_FILE_DELETED | tenant=%s | %s (faq=%s, kb=%s)",
        tenant_id, filename, deleted_faq, deleted_kb,
    )
    return {
        "status": "ok",
        "filename": filename,
        "deleted_faq": deleted_faq,
        "deleted_kb": deleted_kb,
    }


@router.post("/files/image")
async def upload_tenant_image(
    tenant_id: str,
    file: UploadFile = File(...),
    principal: dict = Depends(require_tenant_access()),
):
    """Upload an image and return its public URL (tenant-scoped wrapper).

    Used by the record form's Image column: the image is hosted externally
    (imghippo) and the returned URL is what the record stores, so the bot can
    send it to customers without the console having to serve files.
    """
    from routes.chat import _upload_to_imghippo

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The upload is empty.")
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Images must be under 15 MB.")
    url = _upload_to_imghippo(content, file.filename or "image")
    if not url:
        raise HTTPException(
            status_code=502,
            detail="Image hosting failed — check the imghippo API key.",
        )
    try:
        from database import get_db_context, record_admin_audit_event
        actor = {
            **principal,
            "username": principal.get("username") or principal.get("label") or "tenant",
            "tenant_id": tenant_id,
        }
        with get_db_context() as conn:
            record_admin_audit_event(
                conn,
                action="file_uploaded",
                actor=actor,
                resource_type="file",
                resource_id=file.filename or "image",
                tenant_id=tenant_id,
                details={
                    "file_name": os.path.basename(file.filename or "image"),
                    "file_ext": os.path.splitext(file.filename or "")[1].lower().lstrip("."),
                    "module": "record_image",
                    "file_size": len(content),
                    "hosted": True,
                },
            )
    except Exception as exc:
        logger.error("Could not audit tenant image upload: %s", exc)
    logger.info("TENANT_IMAGE_UPLOADED | tenant=%s | name=%s | bytes=%s", tenant_id, file.filename, len(content))
    return {"url": url, "name": file.filename, "size": len(content)}
