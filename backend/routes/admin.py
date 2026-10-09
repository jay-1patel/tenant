import os
import json
import base64
import logging
import aiohttp
from typing import List
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, Request, Form
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel
from database import (
    get_files_summary, delete_file_chunks, delete_knowledge_base_file, save_chunks, get_db, get_db_context,
    list_admin_files, list_products, get_products_by_category, save_admin_file, delete_admin_file,
    get_menu_items, upsert_menu_item, reset_menu, get_menu_settings, set_menu_settings,
    record_admin_audit_event,
)
from services.menu_catalog import (
    invalidate_menu_cache, get_menu_editor_items, get_effective_item,
)
from extract import process_file, results_to_chunks
from routes.auth import get_current_admin, has_permission, require_permission
from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger("chiki_webhook")
router = APIRouter(prefix="/api/admin")

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploaded_files"))
SUPPORTED = (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls")


def _find_uploaded_file(filename: str) -> str | None:
    for root, _, files in os.walk(UPLOAD_DIR):
        if filename in files:
            return os.path.join(root, filename)
    return None


def _guess_media_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
    }.get(ext, "application/octet-stream")


# ── Dashboard stats (available to every authenticated admin) ─────────────

@router.get("/dashboard/stats")
def dashboard_stats(current_admin: dict = Depends(get_current_admin)):
    """Overview stats for the dashboard. Requires only a valid admin token."""
    files = list_admin_files()
    kb_count = len([f for f in files if f.get("module") == "kb"])
    faq_count = len([f for f in files if f.get("module") == "faq"])

    try:
        product_count = len(list_products(limit=10000))
    except Exception:
        logger.exception("Failed to count products for dashboard")
        product_count = 0

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT message, COUNT(*) as count
               FROM chat_history
               WHERE created_at >= DATE('now', '-7 days')
               GROUP BY LOWER(message)
               ORDER BY count DESC
               LIMIT 7""",
        ).fetchall()
        questions = [{"query": r["message"], "count": r["count"]} for r in rows]

        total_customers = (
            conn.execute(
                """SELECT COUNT(*) AS c FROM (
                       SELECT wa_id FROM orders WHERE wa_id IS NOT NULL
                       UNION
                       SELECT wa_id FROM complaints WHERE wa_id IS NOT NULL
                       UNION
                       SELECT wa_id FROM user_states WHERE wa_id IS NOT NULL
                   )"""
            ).fetchone()["c"]
            or 0
        )

        total_orders = (
            conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"] or 0
        )
        orders_solved = (
            conn.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE status IN ('delivered','completed')"
            ).fetchone()["c"] or 0
        )

        total_complaints = (
            conn.execute("SELECT COUNT(*) AS c FROM complaints").fetchone()["c"] or 0
        )
        complaints_solved = (
            conn.execute(
                "SELECT COUNT(*) AS c FROM complaints WHERE status = 'resolved'"
            ).fetchone()["c"] or 0
        )
    finally:
        conn.close()

    return {
        "kb_files": kb_count,
        "faq_files": faq_count,
        "products": product_count,
        "top_questions": questions,
        "total_customers": total_customers,
        "total_orders": total_orders,
        "orders_solved": orders_solved,
        "total_complaints": total_complaints,
        "complaints_solved": complaints_solved,
    }


# ── Customers (aggregated from orders / complaints / chat_history) ────────

@router.get("/customers")
def list_customers(
    q: str = Query("", max_length=100),
    limit: int = Query(200, le=1000),
    current_admin: dict = Depends(require_permission("view_customers")),
):
    """List customers aggregated across orders, complaints and chat history.

    Each customer is identified by their WhatsApp ID (wa_id). The endpoint
    returns their best-known name/mobile, order and complaint totals, total
    spend, and last activity timestamp.
    """
    conn = get_db()
    try:
        customer_rows = conn.execute(
            """SELECT wa_id FROM (
                   SELECT wa_id FROM orders WHERE wa_id IS NOT NULL AND wa_id != ''
                   UNION
                   SELECT wa_id FROM complaints WHERE wa_id IS NOT NULL AND wa_id != ''
                   UNION
                   SELECT wa_id FROM chat_history WHERE wa_id IS NOT NULL AND wa_id != ''
                   UNION
                   SELECT wa_id FROM user_states WHERE wa_id IS NOT NULL AND wa_id != ''
               )""",
        ).fetchall()
        wa_ids = [r["wa_id"] for r in customer_rows]

        if q.strip():
            needle = q.strip()
            wa_ids = [
                wid for wid in wa_ids
                if needle.lower() in wid.lower()
            ]

        customers = []
        for wid in wa_ids[:limit]:
            name_row = conn.execute(
                """SELECT customer_name FROM orders
                   WHERE wa_id=? AND customer_name IS NOT NULL AND customer_name != ''
                   ORDER BY id DESC LIMIT 1""",
                (wid,),
            ).fetchone()
            sender_row = conn.execute(
                """SELECT sender_name FROM chat_history
                   WHERE wa_id=? AND sender_name IS NOT NULL AND sender_name != ''
                   ORDER BY id DESC LIMIT 1""",
                (wid,),
            ).fetchone()
            mobile_row = conn.execute(
                """SELECT customer_mobile FROM orders
                   WHERE wa_id=? AND customer_mobile IS NOT NULL AND customer_mobile != ''
                   ORDER BY id DESC LIMIT 1""",
                (wid,),
            ).fetchone()

            order_count = conn.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE wa_id=?", (wid,)
            ).fetchone()["c"] or 0
            complaint_count = conn.execute(
                "SELECT COUNT(*) AS c FROM complaints WHERE wa_id=?", (wid,)
            ).fetchone()["c"] or 0
            open_complaints = conn.execute(
                "SELECT COUNT(*) AS c FROM complaints WHERE wa_id=? AND status NOT IN ('resolved','closed')",
                (wid,),
            ).fetchone()["c"] or 0
            spent = conn.execute(
                """SELECT COALESCE(SUM(total_amount), 0) AS v FROM orders
                   WHERE wa_id=? AND status NOT IN ('cancelled','returned')""",
                (wid,),
            ).fetchone()["v"] or 0
            last_active = conn.execute(
                """SELECT MAX(last_seen) AS l FROM (
                       SELECT MAX(created_at) AS last_seen FROM chat_history WHERE wa_id=?
                       UNION ALL
                       SELECT MAX(created_at) AS last_seen FROM orders WHERE wa_id=?
                       UNION ALL
                       SELECT MAX(created_at) AS last_seen FROM complaints WHERE wa_id=?
                       UNION ALL
                       SELECT MAX(updated_at) AS last_seen FROM user_states WHERE wa_id=?
                   )""",
                (wid, wid, wid, wid),
            ).fetchone()["l"]

            customers.append({
                "wa_id": wid,
                "name": (name_row["customer_name"] if name_row else None)
                        or (sender_row["sender_name"] if sender_row else None)
                        or wid,
                "mobile": mobile_row["customer_mobile"] if mobile_row else None,
                "total_orders": order_count,
                "total_complaints": complaint_count,
                "open_complaints": open_complaints,
                "total_spent": round(float(spent), 2),
                "last_active": last_active,
            })

        customers.sort(key=lambda c: c["last_active"] or "", reverse=True)
        return {"customers": customers, "count": len(customers)}
    finally:
        conn.close()


@router.get("/logs")
def get_logs(
    direction: str = Query(None),
    limit: int = Query(100, ge=1, le=500),

):
    conn = get_db()
    try:
        if direction:
            rows = conn.execute(
                "SELECT * FROM webhook_logs WHERE direction = ? ORDER BY created_at DESC LIMIT ?",
                (direction, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM webhook_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.delete("/logs")
def clear_logs(current_admin: dict = Depends(require_permission("view_logs"))):
    with get_db_context() as conn:
        conn.execute("DELETE FROM webhook_logs")
    return {"status": "ok", "message": "Logs cleared"}


# ── Rebuild FAISS index + generate missing embeddings (no restart needed) ─

@router.post("/rebuild-index")
async def rebuild_index(background_tasks: bool = Query(False), current_admin: dict = Depends(get_current_admin)):
    """
    Rebuild all FAISS indexes and generate any missing embeddings.
    Runs in background by default so the endpoint returns immediately.
    Pass ?background_tasks=false to run synchronously (slower response).
    """
    def _do_rebuild():
        results = {}

        # 1. Rebuild KB chunks + missing embeddings + FAISS
        try:
            from kb.services.rag import build_chunks_for_kb, rebuild_faiss_index, generate_missing_embeddings
            build_chunks_for_kb()
            results["kb_chunks"] = "ok"
        except Exception as e:
            logger.error(f"KB build_chunks_for_kb failed: {e}")
            results["kb_chunks"] = f"error: {e}"

        try:
            from kb.services.rag import generate_missing_embeddings
            generate_missing_embeddings()
            results["kb_embeddings"] = "ok"
        except Exception as e:
            logger.error(f"KB generate_missing_embeddings failed: {e}")
            results["kb_embeddings"] = f"error: {e}"

        try:
            from kb.services.rag import rebuild_faiss_index
            rebuild_faiss_index()
            results["kb_faiss"] = "ok"
        except Exception as e:
            logger.error(f"KB rebuild_faiss_index failed: {e}")
            results["kb_faiss"] = f"error: {e}"

        # 2. Rebuild FAQ index (hybrid dense+sparse+reranker)
        try:
            from faq.service import faq_index
            faq_index.build(force=True)
            results["faq_index"] = "ok"
            results["faq_vectors"] = faq_index.index.ntotal if faq_index.is_built else 0
        except Exception as e:
            logger.error(f"FAQ index build failed: {e}")
            results["faq_index"] = f"error: {e}"

        # 3. Rebuild product FAISS index
        try:
            from kb.services.rag import rebuild_product_faiss_index
            rebuild_product_faiss_index()
            results["product_index"] = "ok"
        except Exception as e:
            logger.error(f"Product index build failed: {e}")
            results["product_index"] = f"error: {e}"

        return results

    if background_tasks:
        import threading
        threading.Thread(target=_do_rebuild, daemon=True).start()
        return {"status": "rebuild_started", "detail": "Index rebuild running in background. Check logs for completion."}
    else:
        results = await run_in_threadpool(_do_rebuild)
        return {"status": "ok", "results": results}


# ── Analytics endpoints ───────────────────────────────────────────────────

@router.get("/analytics/response-time")
def get_response_time_analytics(
    days: int = Query(7, ge=1, le=90),

):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT DATE(created_at) as date, AVG(response_time_ms) as avg_ms, COUNT(*) as count
               FROM webhook_logs
               WHERE direction = 'outgoing' AND response_time_ms IS NOT NULL
                 AND created_at >= DATE('now', ?)
               GROUP BY DATE(created_at)
               ORDER BY date ASC""",
            (f"-{days} days",),
        ).fetchall()
        return {
            "days": days,
            "data": [
                {
                    "date": r["date"],
                    "avg_ms": round(r["avg_ms"], 1) if r["avg_ms"] else 0,
                    "count": r["count"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.get("/analytics/frequent-questions")
def get_frequent_questions(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=100),

):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT message, COUNT(*) as count, MAX(created_at) as last_asked
               FROM chat_history
               WHERE created_at >= DATE('now', ?)
               GROUP BY LOWER(message)
               ORDER BY count DESC, last_asked DESC
               LIMIT ?""",
            (f"-{days} days", limit),
        ).fetchall()
        return {
            "days": days,
            "total_unique": len(rows),
            "questions": [
                {
                    "query": r["message"],
                    "count": r["count"],
                    "last_asked": r["last_asked"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.get("/analytics/overview")
def get_analytics_overview(
    days: int = Query(7, ge=1, le=90),

):
    conn = get_db()
    try:
        total_messages = conn.execute(
            """SELECT COUNT(*) as cnt FROM chat_history
               WHERE created_at >= DATE('now', ?)""",
            (f"-{days} days",),
        ).fetchone()["cnt"]

        unique_users = conn.execute(
            """SELECT COUNT(DISTINCT wa_id) as cnt FROM chat_history
               WHERE created_at >= DATE('now', ?)""",
            (f"-{days} days",),
        ).fetchone()["cnt"]

        avg_response = conn.execute(
            """SELECT AVG(response_time_ms) as avg_ms FROM webhook_logs
               WHERE direction = 'outgoing' AND response_time_ms IS NOT NULL
                 AND created_at >= DATE('now', ?)""",
            (f"-{days} days",),
        ).fetchone()["avg_ms"]

        route_breakdown = conn.execute(
            """SELECT route, COUNT(*) as count FROM chat_history
               WHERE created_at >= DATE('now', ?)
               GROUP BY route""",
            (f"-{days} days",),
        ).fetchall()

        return {
            "days": days,
            "total_messages": total_messages,
            "unique_users": unique_users,
            "avg_response_ms": round(avg_response, 1) if avg_response else 0,
            "route_breakdown": [dict(r) for r in route_breakdown],
        }
    finally:
        conn.close()


# ── Top questions ─────────────────────────────────────────────────────────

@router.get("/analytics/top-questions")
def get_top_questions(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),

):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT message, COUNT(*) as count
               FROM chat_history
               WHERE created_at >= DATE('now', ?)
               GROUP BY LOWER(message)
               ORDER BY count DESC
               LIMIT ?""",
            (f"-{days} days", limit),
        ).fetchall()
        total = sum(r["count"] for r in rows)
        return {
            "days": days,
            "total": total,
            "questions": [
                {"query": r["message"], "count": r["count"]}
                for r in rows
            ],
        }
    finally:
        conn.close()


class UnansweredToFAQ(BaseModel):
    query: str
    answer: str
    tenant_id: str = "default"
    module: str = "faq"


@router.post("/analytics/unanswered/convert")
def convert_unanswered_to_faq(
    body: UnansweredToFAQ,
    current_admin: dict = Depends(require_permission("upload_faq")),
):
    """Turn a repeatedly-unanswered question into an FAQ the bot can answer.

    Writes a tenant-tagged faq_dataset row; the embedding is generated on the
    next FAQ index build (missing embeddings are computed there), so this
    insert needs no model in the request path.
    """
    query = body.query.strip()
    answer = body.answer.strip()
    if not query or not answer:
        raise HTTPException(status_code=400, detail="Both query and answer are required")

    content = f"Q: {query}\nA: {answer}"
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO faq_dataset (source_file, content_type, content, page_number, module, tenant_id) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (f"admin_unanswered_{current_admin.get('username', 'admin')}", "text",
             content, body.module.strip() or "faq", body.tenant_id.strip() or "default"),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()
    logger.info(
        "UNANSWERED_CONVERTED_TO_FAQ | admin=%s | tenant=%s | faq_id=%s",
        current_admin.get("username"), body.tenant_id, row_id)
    return {
        "ok": True,
        "faq_id": row_id,
        "tenant_id": body.tenant_id,
        "note": "Rebuild the FAQ index (Knowledge Base -> Rebuild) to make this answer live.",
    }


# ── Unanswered queries ────────────────────────────────────────────────────

@router.get("/analytics/unanswered")
def get_unanswered_queries(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=100),

):
    conn = get_db()
    try:
        keywords = ("i don't know", "i do not know", "sorry", "unable to find", "couldn't find", "no answer", "not available", "don't have that information")
        rows = conn.execute(
            """SELECT message, response, COUNT(*) as count, MAX(created_at) as last_asked
               FROM chat_history
               WHERE created_at >= DATE('now', ?)
                 AND LOWER(response) LIKE ?
               GROUP BY LOWER(message)
               ORDER BY count DESC, last_asked DESC
               LIMIT ?""",
            (f"-{days} days", f"%{keywords[0]}%", limit),
        ).fetchall()
        return {
            "days": days,
            "total": len(rows),
            "queries": [
                {
                    "query": r["message"],
                    "response": r["response"],
                    "count": r["count"],
                    "last_asked": r["last_asked"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


# ── File management ───────────────────────────────────────────────────────

@router.get("/files")
def list_admin_files_api(
    module: str = Query(None),
    search: str = Query(None),
    current_admin: dict = Depends(require_permission("view_files")),
):
    files = list_admin_files()
    if module:
        files = [f for f in files if f.get("module") == module]
    if search:
        s = search.lower()
        files = [f for f in files if s in f.get("name", "").lower()]
    return {"files": files}


@router.get("/files/{filename}/preview")
def preview_admin_file(
    filename: str,
    current_admin: dict = Depends(require_permission("view_files")),
):
    filepath = _find_uploaded_file(filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="File not found")
    media_type = _guess_media_type(filename)
    return FileResponse(filepath, media_type=media_type, headers={"Content-Disposition": f"inline; filename=\"{filename}\""})


@router.get("/files/{filename}/download")
def download_admin_file(
    filename: str,
    current_admin: dict = Depends(require_permission("view_files")),
):
    filepath = _find_uploaded_file(filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="File not found")
    media_type = _guess_media_type(filename)
    return FileResponse(filepath, filename=filename, media_type=media_type, headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})


@router.get("/download-remote")
def download_remote_file(
    url: str = Query(...),
    filename: str = Query(None),
    current_admin: dict = Depends(require_permission("view_files")),
):
    """Proxy-download an arbitrary remote file (e.g. catbox/image hosts) so the
    browser always receives Content-Disposition: attachment, avoiding CORS and
    MIME issues that break direct cross-origin downloads."""
    import httpx
    import mimetypes

    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")
    name = filename or url.split("/")[-1].split("?")[0] or "download"
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            resp = client.get(url)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"download-remote failed for {url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch remote file: {e}")
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(
        content=resp.content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=\"{name}\""},
    )


@router.delete("/files/{filename}")
def delete_admin_file_api(
    filename: str,
    current_admin: dict = Depends(require_permission("delete_files")),
):
    filepath = _find_uploaded_file(filename)
    if not filepath:
        raise HTTPException(status_code=404, detail="File not found on disk")
    deleted_faq = delete_file_chunks(filename)
    deleted_kb = delete_knowledge_base_file(filename)
    delete_admin_file(filename, actor=current_admin)
    try:
        os.remove(filepath)
    except OSError:
        pass
    logger.info(f"Deleted: {filename} (faq={deleted_faq}, kb={deleted_kb})")
    return {"status": "ok", "filename": filename, "deleted_faq": deleted_faq, "deleted_kb": deleted_kb}


@router.post("/files/upload")
async def upload_admin_file(
    request: Request,
    module: str = Query("faq"),
    url: str = Query(None),
    media_type: str = Query(None),
    current_admin: dict = Depends(get_current_admin),
):
    """Upload a FAQ/KB/catalogue file (single-tenant path).

    The tenant-aware variant lives in ``routes/tenant_files.py``; both share
    ``run_upload`` so the extraction/indexing logic exists once.
    """
    return await run_upload(request, module, url, media_type, current_admin, tenant_id=None)


async def run_upload(
    request: Request,
    module: str,
    url: str | None,
    media_type: str | None,
    current_admin: dict,
    tenant_id: str | None = None,
):
    if module == "kb":
        if not has_permission(current_admin, "upload_kb"):
            raise HTTPException(status_code=403, detail="You do not have permission to upload KB files")
    else:
        if not has_permission(current_admin, "upload_faq"):
            raise HTTPException(status_code=403, detail="You do not have permission to upload FAQ files")
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    content_type = request.headers.get("content-type", "")
    filename = ""
    content = b""
    is_image = False

    if "application/json" in content_type:
        body = await request.json()
        filename = body.get("filename", "")
        content = base64.b64decode(body.get("content", ""))
        if not url:
            url = body.get("url")
        if not media_type:
            media_type = body.get("media_type")
    elif "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload and hasattr(upload, "read"):
            filename = upload.filename or "unknown"
            content = await upload.read()
            if hasattr(upload, "content_type") and upload.content_type and upload.content_type.startswith("image/"):
                is_image = True
        url = form.get("url") or url
        media_type = form.get("media_type") or media_type
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(filename).suffix.lower()
    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    if ext in image_exts or is_image:
        # Upload image to imghippo
        if not IMGHIPPO_API_KEY:
            raise HTTPException(status_code=400, detail="Imghippo API key not configured")
        import aiohttp
        img_payload = aiohttp.FormData()
        img_payload.add_field("api_key", IMGHIPPO_API_KEY)
        img_payload.add_field("file", content, filename=filename or "image")
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.imghippo.com/v1/upload", data=img_payload) as resp:
                img_data = await resp.json()
                if not resp.ok or not img_data.get("success"):
                    raise HTTPException(status_code=400, detail=img_data.get("message", "Imghippo upload failed"))
                effective_url = img_data["data"]["url"]
                effective_media_type = media_type or ext.lstrip(".")
                save_admin_file(filename, ext.lstrip("."), module, len(content), url=effective_url, tenant_id=tenant_id, actor=current_admin)
                return {
                    "status": "ok",
                    "filename": filename,
                    "module": module,
                    "chunks": 0,
                    "size": len(content),
                    "file_url": effective_url,
                }

    if ext not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # Auto-host uploaded PDFs on catbox.moe so the bot can send the document
    # directly to WhatsApp from a permanent public URL (no dependency on the
    # transient tunnel PUBLIC_BASE_URL). Text extraction still runs below and
    # its chunks are stored in faq_dataset, with the catbox URL as the
    # media_url for the answer. Catalogue PDF text is intentionally NOT
    # imported into the products table — "catalogue" requests send the PDF.
    catbox_url = None
    if ext == ".pdf" and module in ("faq", "catalogue", "new_arrival") and not url:
        try:
            catbox_url = await _upload_to_catbox(filename, content, media_type or "application/pdf")
            logger.info(f"CATBOX_UPLOAD | {filename} -> {catbox_url}")
        except Exception as e:
            logger.error(f"Catbox upload failed for {filename}: {e}")
            catbox_url = None

    def _process():
        module_dir = os.path.join(UPLOAD_DIR, module)
        os.makedirs(module_dir, exist_ok=True)
        filepath = os.path.join(module_dir, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        size = len(content)
        save_admin_file(filename, ext.lstrip("."), module, size, file_path=filepath, url=url or catbox_url, tenant_id=tenant_id, actor=current_admin)
        chunks = []
        try:
            results = process_file(filepath)
            if results:
                chunks = results_to_chunks(results)
                if chunks:
                    effective_url = url or catbox_url or f"/uploaded_files/{module}/{filename}"
                    effective_media_type = media_type or ext.lstrip(".")
                    if module == "kb":
                        from database import save_knowledge_base_chunks
                        save_knowledge_base_chunks(chunks, filename, media_url=effective_url, media_type=effective_media_type, tenant_id=tenant_id)
                        try:
                            from kb.services.rag import build_chunks_for_kb, generate_missing_embeddings, rebuild_faiss_index
                            build_chunks_for_kb()
                            generate_missing_embeddings()
                            rebuild_faiss_index()
                            logger.info(f"KB_FAISS_REBUILT | {filename}")
                        except Exception as e:
                            logger.error(f"KB FAISS rebuild failed after upload {filename}: {e}")
                    else:
                        save_chunks(chunks, module=module, media_url=effective_url, media_type=effective_media_type, tenant_id=tenant_id)
                    if module in ("faq", "catalogue", "new_arrival"):
                        from faq.service import faq_index
                        faq_index.build(force=True)
        except Exception as e:
            logger.error(f"Extraction failed for {filename}: {e}")
        return {
            "status": "ok",
            "filename": filename,
            "module": module,
            "chunks": len(chunks),
            "size": size,
            "file_url": url or catbox_url or f"/uploaded_files/{module}/{filename}",
        }

    result = await run_in_threadpool(_process)
    return result


# ── Chat history with user lookup ─────────────────────────────────────────

@router.get("/chat-history")
def get_chat_history_api(
    days: int = Query(30, ge=1, le=1095),
    from_date: str = Query(None),
    to_date: str = Query(None),
    search: str = Query(None),
    current_admin: dict = Depends(require_permission("chat_history")),
):
    conn = get_db()
    try:
        if from_date and to_date:
            query = """SELECT ch.*
                       FROM chat_history ch
                       WHERE ch.created_at >= ? AND ch.created_at <= ?"""
            params = [from_date, to_date + " 23:59:59"]
        else:
            query = """SELECT ch.*
                       FROM chat_history ch
                       WHERE ch.created_at >= DATE('now', ?)"""
            params = [f"-{days} days"]
        if search:
            query += " AND (ch.wa_id LIKE ? OR ch.sender_name LIKE ? OR ch.message LIKE ? OR ch.response LIKE ?)"
            params.extend([f"%{search}%"] * 4)
        query += " ORDER BY ch.created_at DESC LIMIT 500"
        rows = conn.execute(query, params).fetchall()
        return {"history": [dict(r) for r in rows]}
    finally:
        conn.close()


# ── Products / Catalogue ──────────────────────────────────────────────────

@router.get("/products")
def list_products_api(
    category: str = Query(None),
    search: str = Query(None),
    current_admin: dict = Depends(require_permission("view_products")),
):
    products = list_products(category=category, active_only=False)
    if search:
        s = search.lower()
        products = [p for p in products if s in p.get("name", "").lower() or s in p.get("description", "").lower()]
    return {"products": products}


@router.post("/products")
def create_product_api(
    data: dict,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    name = data.get("name", "")
    slug = data.get("slug", "")
    if not name or not slug:
        raise HTTPException(status_code=400, detail="name and slug are required")
    pid = save_product(
        name=name,
        slug=slug,
        category=data.get("category", "general"),
        description=data.get("description", ""),
        short_description=data.get("short_description", ""),
        price=data.get("price", ""),
        mrp=data.get("mrp", ""),
        unit=data.get("unit", "piece"),
        moq=data.get("moq", ""),
        media_url=data.get("media_url"),
        media_type=data.get("media_type", "image"),
        ingredients=data.get("ingredients", []),
        sort_order=data.get("sort_order", 0),
        stock_quantity=data.get("stock_quantity"),
        nutritional_facts=data.get("nutritional_facts"),
        bulk_discount_tiers=data.get("bulk_discount_tiers", []),
        actor=current_admin,
    )
    return {"status": "ok", "id": pid}


@router.put("/products/{product_id}")
def update_product_api(
    product_id: int,
    data: dict,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    allowed = {k: v for k, v in data.items() if k in {
        "name", "slug", "category", "description", "short_description",
        "price", "mrp", "unit", "moq", "media_url", "media_type", "ingredients", "is_active", "sort_order",
        "stock_quantity", "nutritional_facts", "bulk_discount_tiers"
    }}
    if "ingredients" in allowed and isinstance(allowed["ingredients"], list):
        allowed["ingredients"] = json.dumps(allowed["ingredients"])
    if "bulk_discount_tiers" in allowed and isinstance(allowed["bulk_discount_tiers"], list):
        allowed["bulk_discount_tiers"] = json.dumps(allowed["bulk_discount_tiers"])
    ok = update_product(product_id, actor=current_admin, **allowed)
    if not ok:
        raise HTTPException(status_code=400, detail="Update failed")
    return {"status": "ok"}


@router.delete("/products/{product_id}")
def delete_product_api(
    product_id: int,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    ok = delete_product(product_id, hard=True, actor=current_admin)
    if not ok:
        raise HTTPException(status_code=400, detail="Delete failed")
    return {"status": "ok"}


IMGHIPPO_API_KEY = os.environ.get("IMGHIPPO_API_KEY", "d5f26052bf1b041f160e530a28d19cfd")
CATBOX_API_URL = "https://catbox.moe/user/api.php"


async def _upload_to_catbox(filename: str, content: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to catbox.moe and return the permanent public URL."""
    payload = aiohttp.FormData()
    payload.add_field("reqtype", "fileupload")
    payload.add_field("fileToUpload", content, filename=filename, content_type=content_type)

    async with aiohttp.ClientSession() as session:
        async with session.post(CATBOX_API_URL, data=payload) as resp:
            text = (await resp.text()).strip()
            if not resp.ok or text.lower().startswith("error"):
                raise HTTPException(status_code=400, detail=f"Catbox upload failed: {text}")
            return text


@router.post("/upload/image")
async def upload_image_to_imghippo(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    contents = await file.read()
    payload = aiohttp.FormData()
    payload.add_field("api_key", IMGHIPPO_API_KEY)
    payload.add_field("file", contents, filename=file.filename or "image", content_type=file.content_type or "application/octet-stream")

    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.imghippo.com/v1/upload", data=payload) as resp:
            data = await resp.json()
            if not resp.ok or not data.get("success"):
                raise HTTPException(status_code=400, detail=data.get("message", "Imghippo upload failed"))
            url = data["data"]["url"]
            return {"url": url, "media_type": file.content_type}


@router.post("/upload/catbox")
async def upload_to_catbox(file: UploadFile = File(...)):
    contents = await file.read()
    url = await _upload_to_catbox(
        file.filename or "file",
        contents,
        file.content_type or "application/octet-stream",
    )
    return {"url": url, "media_type": file.content_type or "application/octet-stream"}


#: Chat attachments are hosted public (imghippo for images, catbox otherwise) so
#: the console can render them inline and the live inbox can hand the URL to
#: WhatsApp. Kept small enough not to hold a request open for minutes.
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def decode_attachment_body(data: dict) -> tuple[str, bytes, str | None]:
    """Validate a base64 JSON attachment body into ``(filename, bytes, type)``."""
    filename = (data.get("filename") or "").strip()
    raw = data.get("content") or ""
    if not filename or not raw:
        raise HTTPException(status_code=400, detail="filename and content are required")
    try:
        content = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="content must be base64")
    if not content:
        raise HTTPException(status_code=400, detail="The file is empty")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Attachments must be under {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB",
        )
    return filename, content, data.get("media_type")


async def store_chat_attachment(filename: str, content: bytes, media_type: str | None = None) -> dict:
    """Host one chat attachment and return a descriptor the UI can use."""
    ext = Path(filename).suffix.lower()
    is_image = (media_type or "").startswith("image/") or ext in _IMAGE_EXTS
    if is_image:
        payload = aiohttp.FormData()
        payload.add_field("api_key", IMGHIPPO_API_KEY)
        payload.add_field("file", content, filename=filename or "image",
                          content_type=media_type or "application/octet-stream")
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.imghippo.com/v1/upload", data=payload) as resp:
                data = await resp.json()
                if not resp.ok or not data.get("success"):
                    raise HTTPException(status_code=400, detail=data.get("message", "Image upload failed"))
                url = data["data"]["url"]
        kind = "image"
    else:
        url = await _upload_to_catbox(filename or "file", content, media_type or "application/octet-stream")
        kind = "document"
    return {
        "url": url,
        "name": filename,
        "type": kind,
        "size": len(content),
        "media_type": media_type or ("image/*" if is_image else "application/octet-stream"),
    }


# ── Menu Editor (admin-editable WhatsApp menus) ──────────────────────────
#
# HOW IT WORKS NOW (the "toggling one item kills the whole menu" fix):
# The `menus` table stores PER-ITEM OVERRIDES on top of the hard-coded
# defaults in services/menu_catalog.py — it is never a replacement for the
# whole menu. GET endpoints therefore ALWAYS return the full merged list
# (every default item + admin-created items, with override values applied),
# so the editor keeps showing all items no matter how many have been edited.
# A single PUT toggling is_active now hides exactly that one item at runtime.

KNOWN_MENU_KEYS = ["kb_main"]


@router.get("/menus")
def list_menus_api(current_admin: dict = Depends(get_current_admin)):
    """All menu keys with their full merged item lists (defaults + overrides)."""
    return {
        "menus": [
            {"menu_key": key, "items": get_menu_editor_items(key)}
            for key in KNOWN_MENU_KEYS
        ]
    }


@router.get("/menus/{menu_key}")
def get_menu_api(menu_key: str, current_admin: dict = Depends(get_current_admin)):
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")

    # BUG FIX: this used to return ONLY the raw DB rows once a single edit
    # existed, which made every other menu item vanish from the editor after
    # the first save/toggle. get_menu_editor_items() always merges the code
    # defaults with the DB overrides so the editor sees the complete menu.
    return {
        "menu_key": menu_key,
        "items": get_menu_editor_items(menu_key),
        "settings": get_menu_settings(menu_key),
    }


@router.get("/menus/{menu_key}/settings")
def get_menu_settings_api(menu_key: str, current_admin: dict = Depends(get_current_admin)):
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")
    return {"menu_key": menu_key, "settings": get_menu_settings(menu_key)}


# NOTE: settings routes are declared BEFORE the /{item_id} route so that
# "settings" is never captured as an item_id path parameter.
@router.put("/menus/{menu_key}/settings")
def set_menu_settings_api(
    menu_key: str,
    data: dict,
    request: Request,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")
    before = get_menu_settings(menu_key)
    if not set_menu_settings(menu_key, **data):
        raise HTTPException(status_code=400, detail="No valid settings fields supplied")
    after = get_menu_settings(menu_key)
    changed = {key: {"before": before.get(key), "after": after.get(key)} for key in data if before.get(key) != after.get(key)}
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="menu_settings_updated", actor=current_admin, resource_type="menu", resource_id=menu_key, details={"changed_fields": sorted(changed), "changes": changed})
    invalidate_menu_cache()
    return {"ok": True, "menu_key": menu_key, "settings": after}


@router.put("/menus/{menu_key}/{item_id}")
def update_menu_item_api(
    menu_key: str,
    item_id: str,
    data: dict,
    request: Request,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    """Edit any field of a menu item, including item_id.

    Only the supplied fields are changed; everything else keeps its current
    effective value (DB override or code default). This is the fix for
    "can't edit menu items": a toggle of is_active no longer wipes the
    item's other fields, and editing/renaming an item that has never been
    saved to the DB works too (it used to 404 for renames).
    """
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")

    # ── item_id rename ──────────────────────────────────────────────────
    new_item_id = data.get("item_id")
    if new_item_id and new_item_id != item_id:
        new_item_id = str(new_item_id).strip()
        if not new_item_id:
            raise HTTPException(status_code=400, detail="item_id cannot be empty")
        if get_effective_item(menu_key, new_item_id):
            raise HTTPException(status_code=400, detail=f"item_id '{new_item_id}' already exists")

        # BUG FIX: resolve the CURRENT item through the merged view so
        # renaming a never-edited (code-default) item works instead of 404.
        effective = get_effective_item(menu_key, item_id)
        if not effective:
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

        # Merge incoming fields over the effective (DB-over-default) values
        merged = {
            "title": data.get("title", effective["title"]),
            "description": data.get("description", effective["description"]),
            "section": data.get("section", effective["section"]),
            "icon": data.get("icon", effective["icon"]),
            "sort_order": data.get("sort_order", effective["sort_order"]),
            "is_active": data.get("is_active", bool(effective["is_active"])),
        }

        # Delete old override row (if any), upsert the full item under the new key.
        # If the old id is a hard-coded code default, hide it with an inactive
        # override row — with per-item merge semantics the default would
        # otherwise keep reappearing alongside the renamed copy.
        try:
            from database import delete_menu_item
        except Exception:
            def delete_menu_item(mkey, iid):
                with get_db_context() as conn:
                    cur = conn.execute(
                        "DELETE FROM menus WHERE menu_key=? AND item_id=?", (mkey, iid)
                    )
                return cur.rowcount > 0

        delete_menu_item(menu_key, item_id)
        if effective["is_default"]:
            upsert_menu_item(menu_key, item_id, is_active=False)
        upsert_menu_item(menu_key, new_item_id, **merged)
        with get_db_context() as conn:
            record_admin_audit_event(conn, action="menu_item_updated", actor=current_admin, resource_type="menu_item", resource_id=f"{menu_key}/{new_item_id}", details={"menu_key": menu_key, "item_id": new_item_id, "renamed_from": item_id, "changed_fields": ["item_id", "title", "description", "section", "icon", "sort_order", "is_active"]})
        invalidate_menu_cache()
        return {"ok": True, "menu_key": menu_key, "item_id": new_item_id, "renamed_from": item_id}

    # ── normal field update (partial — unprovided fields are preserved) ──
    allowed = {"title", "description", "section", "icon", "sort_order", "is_active"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        raise HTTPException(status_code=400, detail="No editable fields supplied")
    effective = get_effective_item(menu_key, item_id)
    if not effective:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    changed = {key: {"before": effective.get(key), "after": value} for key, value in fields.items() if effective.get(key) != value}
    upsert_menu_item(menu_key, item_id, **fields)
    if changed:
        with get_db_context() as conn:
            record_admin_audit_event(conn, action="menu_item_updated", actor=current_admin, resource_type="menu_item", resource_id=f"{menu_key}/{item_id}", details={"menu_key": menu_key, "item_id": item_id, "changed_fields": sorted(changed), "changes": changed})
    invalidate_menu_cache()
    return {"ok": True, "menu_key": menu_key, "item_id": item_id}


@router.post("/menus/{menu_key}/items")
def create_menu_item_api(
    menu_key: str,
    data: dict,
    request: Request,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    """Add a brand-new item to the menu (stored as a DB row; it is not part
    of the code defaults, so Reset removes it)."""
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")

    item_id = str(data.get("item_id", "")).strip()
    title = str(data.get("title", "")).strip()
    if not item_id or not title:
        raise HTTPException(status_code=400, detail="item_id and title are required")
    if get_effective_item(menu_key, item_id):
        raise HTTPException(status_code=400, detail=f"item_id '{item_id}' already exists")

    ok = upsert_menu_item(
        menu_key,
        item_id,
        title=title,
        description=data.get("description", ""),
        section=data.get("section", "General"),
        icon=data.get("icon", ""),
        sort_order=data.get("sort_order"),
        is_active=bool(data.get("is_active", True)),
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Could not create menu item")
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="menu_item_created", actor=current_admin, resource_type="menu_item", resource_id=f"{menu_key}/{item_id}", details={"menu_key": menu_key, "item_id": item_id, "title": title[:120], "section": str(data.get("section", "General"))[:80]})
    invalidate_menu_cache()
    return {"ok": True, "menu_key": menu_key, "item_id": item_id}


@router.post("/menus/{menu_key}/reorder")
def reorder_menu_items_api(
    menu_key: str,
    data: dict,
    request: Request,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    """Set the display order for the whole menu in one call.

    Body: {"item_ids": ["menu_products", "menu_new_arrivals", ...]} — the
    list position becomes each item's sort_order. Items not included keep
    their current order (they sort after the listed ones).
    """
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")

    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    item_ids = data.get("item_ids")
    if not isinstance(item_ids, list) or not item_ids:
        raise HTTPException(status_code=400, detail="item_ids (non-empty list) is required")

    applied = 0
    for idx, iid in enumerate(item_ids):
        if upsert_menu_item(menu_key, str(iid).strip(), sort_order=idx):
            applied += 1
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="menu_reordered", actor=current_admin, resource_type="menu", resource_id=menu_key, details={"menu_key": menu_key, "item_count": applied, "item_ids": [str(i)[:80] for i in item_ids[:100]]})
    invalidate_menu_cache()
    return {"ok": True, "menu_key": menu_key, "reordered": applied}


@router.delete("/menus/{menu_key}/{item_id}")
def delete_menu_item_api(
    menu_key: str,
    item_id: str,
    request: Request,
    current_admin: dict = Depends(require_permission("edit_delete_products")),
):
    """Remove an item from the menu.

    - Admin-created items: the DB row is deleted entirely.
    - Code-default items: cannot be removed (they live in code), so they are
      hidden with an inactive override row — they come back on Reset.
    """
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")

    effective = get_effective_item(menu_key, item_id)
    if not effective:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    if effective["is_default"]:
        upsert_menu_item(menu_key, item_id, is_active=False)
        with get_db_context() as conn:
            record_admin_audit_event(conn, action="menu_item_deleted", actor=current_admin, resource_type="menu_item", resource_id=f"{menu_key}/{item_id}", details={"menu_key": menu_key, "item_id": item_id, "title": str(effective.get("title", ""))[:120], "hidden": True})
        invalidate_menu_cache()
        return {"ok": True, "menu_key": menu_key, "item_id": item_id, "hidden": True}

    try:
        from database import delete_menu_item
    except Exception:
        def delete_menu_item(mkey, iid):
            with get_db_context() as conn:
                cur = conn.execute(
                    "DELETE FROM menus WHERE menu_key=? AND item_id=?", (mkey, iid)
                )
            return cur.rowcount > 0

    deleted = delete_menu_item(menu_key, item_id)
    invalidate_menu_cache()
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="menu_item_deleted", actor=current_admin, resource_type="menu_item", resource_id=f"{menu_key}/{item_id}", details={"menu_key": menu_key, "item_id": item_id, "title": str(effective.get("title", ""))[:120], "hidden": False})
    return {"ok": True, "menu_key": menu_key, "item_id": item_id, "hidden": False}


@router.post("/menus/{menu_key}/reset")
def reset_menu_api(menu_key: str, request: Request, current_admin: dict = Depends(require_permission("edit_delete_products"))):
    """Delete DB overrides (items + settings) for one menu; code defaults take effect again."""
    try:
        from backend.services.audit_context import set_audit_actor
        set_audit_actor(current_admin)
    except Exception:
        pass
    if menu_key not in KNOWN_MENU_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown menu_key: {menu_key}")
    removed = reset_menu(menu_key)
    with get_db_context() as conn:
        record_admin_audit_event(conn, action="menu_reset", actor=current_admin, resource_type="menu", resource_id=menu_key, details={"menu_key": menu_key, "removed_count": removed})
    invalidate_menu_cache()
    return {"ok": True, "menu_key": menu_key, "removed": removed}


# ============================================================================
# BROCHURE MANAGEMENT ENDPOINTS
# ============================================================================

class BrochureInfo(BaseModel):
    name: str
    module: str
    description: str = ""
    category: str = ""
    tags: List[str] = []


@router.get("/brochures", dependencies=[Depends(get_current_admin)])
async def list_brochures(tenant_id: str = Query(None)):
    """List all brochures for a tenant or globally."""
    from backend.services.brochure_service import BrochureService
    
    service = BrochureService()
    brochures = service.get_all_brochures(tenant_id)
    
    result = []
    for brochure in brochures:
        result.append({
            "id": brochure.file_id,
            "tenant_id": brochure.tenant_id,
            "module": brochure.module,
            "name": brochure.name,
            "filename": brochure.filename,
            "url": brochure.url,
            "size": brochure.size,
            "keywords": brochure.keywords,
            "metadata": brochure.metadata,
            "created_at": brochure.created_at,
        })
    
    return {"ok": True, "brochures": result, "count": len(result)}


@router.get("/brochures/{brochure_id}", dependencies=[Depends(get_current_admin)])
async def get_brochure(brochure_id: int):
    """Get information about a specific brochure."""
    from backend.services.brochure_service import BrochureService
    
    service = BrochureService()
    
    try:
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM admin_files WHERE id = ?", (brochure_id,)
            ).fetchone()
            
            if row:
                brochure = service.Brochure(
                    file_id=row["id"],
                    tenant_id=row["tenant_id"] or "",
                    module=row["module"] or "general",
                    name=row["name"] or "",
                    filename=row["name"] or row.get("filename", ""),
                    url=row["url"] or "",
                    file_path=row["file_path"] or "",
                    ext=row["ext"] or "",
                    size=row["size"] or 0,
                    doc_id=row["doc_id"] or None,
                    created_at=row["created_at"] or "",
                )
                return {
                    "ok": True,
                    "brochure": {
                        "id": brochure.file_id,
                        "tenant_id": brochure.tenant_id,
                        "module": brochure.module,
                        "name": brochure.name,
                        "filename": brochure.filename,
                        "url": brochure.url,
                        "size": brochure.size,
                        "keywords": brochure.keywords,
                        "metadata": brochure.metadata,
                        "created_at": brochure.created_at,
                    }
                }
    except Exception as e:
        logger.error(f"Failed to get brochure {brochure_id}: {e}")
    
    return {"ok": False, "error": f"Brochure {brochure_id} not found"}


@router.delete("/brochures/{brochure_id}", dependencies=[Depends(get_current_admin)])
async def delete_brochure(brochure_id: int, current_admin: dict = Depends(get_current_admin)):
    """Delete a specific brochure."""
    try:
        with get_db_context() as conn:
            # Get brochure info first for audit
            row = conn.execute(
                "SELECT * FROM admin_files WHERE id = ?", (brochure_id,)
            ).fetchone()
            
            if not row:
                return {"ok": False, "error": f"Brochure {brochure_id} not found"}
            
            # Delete the brochure
            conn.execute("DELETE FROM admin_files WHERE id = ?", (brochure_id,))
            
            # Record audit event
            record_admin_audit_event(
                conn, 
                action="brochure_delete", 
                actor=current_admin, 
                resource_type="brochure", 
                resource_id=brochure_id,
                details={"filename": row.get("name", "Unknown"), "module": row.get("module", "unknown")}
            )
        
        return {"ok": True, "deleted": brochure_id}
        
    except Exception as e:
        logger.error(f"Failed to delete brochure {brochure_id}: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/brochures/upload", dependencies=[Depends(get_current_admin)])
async def upload_brochure(
    file: UploadFile = File(...),
    module: str = Form("catalogue"),
    name: str = Form(""),
    description: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    tenant_id: str = Form(None),
    current_admin: dict = Depends(get_current_admin)
):
    """Upload a new brochure file."""
    from backend.services.brochure_service import extract_file_metadata
    from backend.services.audit_context import set_audit_actor
    
    # Ensure we have admin permissions
    if not has_permission(current_admin, "upload_files"):
        raise HTTPException(status_code=403, detail="You do not have permission to upload brochures")
    
    if module not in ["catalogue", "new_arrival", "product_brochure", "service_brochure", 
                     "company_profile", "technical_brochure", "pricing", "customer_case_study",
                     "industry_brochure", "general"]:
        return {"ok": False, "error": f"Invalid module. Must be one of: {BROCHURE_MODULES}"}
    
    try:
        set_audit_actor(current_admin)
    except Exception:
        pass
    
    # Read file content
    content = await file.read()
    filename = file.filename or "brochure"
    ext = os.path.splitext(filename)[1].lower()
    
    # Validate file type
    if ext not in SUPPORTED:
        return {"ok": False, "error": f"Unsupported file type: {ext}. Supported: {SUPPORTED}"}
    
    # Save the file
    try:
        # Create upload directory if it doesn't exist
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # Generate unique filename
        import hashlib
        import time
        timestamp = int(time.time())
        file_hash = hashlib.md5(content[:1024]).hexdigest()[:8]
        unique_filename = f"{timestamp}_{file_hash}_{filename}"
        filepath = os.path.join(UPLOAD_DIR, unique_filename)
        
        with open(filepath, "wb") as f:
            f.write(content)
        
        # Extract metadata
        if not name:
            name = filename
        metadata = extract_file_metadata(filename)
        if description:
            metadata['description'] = description
        if category:
            metadata['category'] = category
        if tags:
            metadata['tags'] = [tag.strip() for tag in tags.split(",") if tag.strip()]
        
        # Save to database
        save_admin_file(
            name=name,
            ext=ext.lstrip("."),
            module=module,
            size=len(content),
            file_path=filepath,
            url=None,  # No direct URL, will use file path
            tenant_id=tenant_id,
            actor=current_admin
        )
        
        # Record audit event
        with get_db_context() as conn:
            record_admin_audit_event(
                conn,
                action="brochure_upload",
                actor=current_admin,
                resource_type="brochure",
                resource_id=filename,
                details={
                    "filename": filename,
                    "module": module,
                    "size": len(content),
                    "metadata": metadata
                }
            )
        
        return {
            "ok": True,
            "message": "Brochure uploaded successfully",
            "filename": filename,
            "module": module,
            "path": filepath,
            "metadata": metadata
        }
        
    except Exception as e:
        logger.error(f"Failed to upload brochure: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/brochures/extract-metadata", dependencies=[Depends(get_current_admin)])
async def extract_brochure_metadata(
    file: UploadFile = File(...),
    current_admin: dict = Depends(get_current_admin)
):
    """Extract metadata from a brochure file for preview."""
    from backend.services.brochure_service import extract_file_metadata
    
    if not has_permission(current_admin, "upload_files"):
        raise HTTPException(status_code=403, detail="You do not have permission to extract metadata")
    
    try:
        # For now, we only extract from filename
        # Could be extended to parse PDF/DOCX content
        filename = file.filename or "brochure"
        metadata = extract_file_metadata(filename)
        
        return {
            "ok": True,
            "filename": filename,
            "metadata": metadata
        }
    except Exception as e:
        logger.error(f"Failed to extract metadata: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/brochures/relevant", dependencies=[Depends(get_current_admin)])
async def find_relevant_brochures(
    query: str = Query(""),
    tenant_id: str = Query(None),
    module: str = Query(None)
):
    """Find brochures relevant to a specific query."""
    from backend.services.brochure_service import BrochureService, categorize_query
    
    service = BrochureService()
    
    if module:
        # Get by specific module
        brochure = service.get_brochure_by_module(module, tenant_id)
        relevant_brochures = [brochure] if brochure else []
    elif query:
        # Categorize query and get relevant brochures
        category = categorize_query(query)
        relevant_brochures = service.get_brochures_by_category(category, tenant_id)
        if not relevant_brochures:
            # Fallback to general search
            relevant_brochures = service.get_all_brochures(tenant_id)
    else:
        # Return all brochures
        relevant_brochures = service.get_all_brochures(tenant_id)
    
    result = []
    for brochure in relevant_brochures:
        result.append({
            "id": brochure.file_id,
            "tenant_id": brochure.tenant_id,
            "module": brochure.module,
            "name": brochure.name,
            "filename": brochure.filename,
            "url": brochure.url,
            "keywords": brochure.keywords,
            "metadata": brochure.metadata,
        })
    
    return {
        "ok": True, 
        "query": query,
        "category": module or (categorize_query(query) if query else "unknown"),
        "brochures": result,
        "count": len(result)
    }


# Available brochure modules for the frontend
BROCHURE_MODULES = [
    "catalogue", "new_arrival", "product_brochure", "service_brochure",
    "company_profile", "technical_brochure", "pricing", "customer_case_study",
    "industry_brochure", "general"
]
