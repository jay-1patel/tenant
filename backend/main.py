import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "routing"))

import logging
import asyncio
import uvicorn
from fastapi import FastAPI, Request
import json
import jwt
from routing.config import ADMIN_SECRET_KEY
from database import get_db_context, record_admin_audit_event
from fastapi.middleware.cors import CORSMiddleware
from middleware import SecurityHeadersMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from database import (
    init_db,
    set_audit_request_context,
    clear_audit_request_context,
    trusted_client_ip,
)
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from routing.config import ROUTER_PORT
from routing import classify_query
from routing.message import forward_to_bot
from routes.chat import router as chat_router
from routes.faqs import router as faqs_router
from routes.status import router as status_router
from routes.admin import router as admin_router
from routes.auth import router as auth_router
from routes.auth import RATE_LIMIT_ENABLED, limiter, rate_limit_exceeded_handler
try:
    from slowapi.errors import RateLimitExceeded
except ImportError:
    RateLimitExceeded = None
from routes.chat_admin import router as chat_admin_router
from routing import webhook_router
from faq.router import faq_router
from kb.router import kb_router
from routes.catalog import router as catalog_router
from routes.distributors import router as distributors_router
from routes.campaigns import router as campaigns_router
from routes.unified import router as unified_router
from routes.inbox import router as inbox_router
from routes.dynamic_config import router as dynamic_config_router
from routes.orders import router as orders_router
from routes.complaints import router as complaints_router
from routes.tenants import router as tenants_router
from routes.offerings import router as offerings_router
from routes.conversations import router as conversations_router
from routes.tenant_files import router as tenant_files_router
from routes.tenant_chat import router as tenant_chat_router
from routes.tenant_operations import router as tenant_operations_router
from routes.leads import router as leads_router
from routes.api_onboarding import router as api_onboarding_router
from routes.audit import router as audit_router
from routes.audit_logs import router as audit_logs_router
from routes.tenant_approvals import router as tenant_approvals_router
from routes.integrations import router as integrations_router
from routes.callbacks import router as callbacks_router
from services.handoff_timeout import handoff_timeout_monitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[STARTUP] lifespan entered")
    init_db()
    logger.info("[STARTUP] init_db done")

    from faq.service import faq_index
    logger.info(f"[STARTUP] faq_index id={id(faq_index)}, is_built={faq_index.is_built}")

    try:
        faq_index.build()
        logger.info(f"[STARTUP] build() returned, is_built={faq_index.is_built}, "
                    f"ntotal={getattr(faq_index.index, 'ntotal', 'no-index')}")
        if faq_index.is_built:
            logger.info(f"FAQ index built: {faq_index.index.ntotal} vectors")
        else:
            logger.warning("FAQ index build returned but index not marked as built")
    except Exception as exc:
        logger.error(f"FAQ index init FAILED: {exc}", exc_info=True)

    try:
        from kb.services.rag import build_chunks_for_kb, rebuild_faiss_index, generate_missing_embeddings
        build_chunks_for_kb()
        generate_missing_embeddings()
        rebuild_faiss_index()
        logger.info("[STARTUP] KB index built")
    except Exception as exc:
        logger.warning(f"KB index init skipped: {exc}", exc_info=True)

    try:
        from kb.services.rag import rebuild_product_faiss_index
        rebuild_product_faiss_index()
        logger.info("[STARTUP] Product FAISS index built")
    except Exception as exc:
        logger.warning(f"Product index init skipped: {exc}", exc_info=True)

    # Start the handoff timeout monitor
    handoff_stop_event = asyncio.Event()
    handoff_task = asyncio.create_task(handoff_timeout_monitor(handoff_stop_event))
    logger.info("[STARTUP] Handoff timeout monitor started (1h auto-revert)")

    # Start the cart/checkout TTL cleanup loop (7-day carts, 15-min checkouts)
    cart_cleanup_stop_event = asyncio.Event()
    cart_cleanup_task = asyncio.create_task(cart_cleanup_monitor(cart_cleanup_stop_event))
    logger.info("[STARTUP] Cart/checkout TTL cleanup monitor started")

    try:
        yield
    finally:
        handoff_stop_event.set()
        handoff_task.cancel()
        try:
            await handoff_task
        except asyncio.CancelledError:
            pass
        cart_cleanup_stop_event.set()
        cart_cleanup_task.cancel()
        try:
            await cart_cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("[SHUTDOWN] Server stopped")


async def cart_cleanup_monitor(stop_event: asyncio.Event = None) -> None:
    """Hourly cleanup of expired carts and checkout sessions."""
    while not (stop_event and stop_event.is_set()):
        try:
            from services.cart_service import cleanup_expired
            counts = cleanup_expired()
            if counts.get("carts") or counts.get("checkouts"):
                logger.info(f"CART_CLEANUP | expired carts={counts['carts']} checkouts={counts['checkouts']}")
        except Exception as exc:
            logger.error(f"CART_CLEANUP_MONITOR_FAIL: {exc}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3600)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise


FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"

app = FastAPI(
    title="Chiki Unified Service",
    version="2.0.0", 
    lifespan=lifespan,
    # SECURITY FIX: Enforce HTTPS for all connections
    https_redirect=FORCE_HTTPS,
)

try:
    from services.audit_context import install_writer_context
except ImportError:
    from backend.services.audit_context import install_writer_context
import database as _audit_database
install_writer_context(_audit_database)


@app.middleware("http")
async def audit_request_context(request: Request, call_next):
    """Provide trusted network metadata to audit writes for this request."""
    peer = request.client.host if request.client else None
    ip = trusted_client_ip(peer, request.headers.get("x-forwarded-for"))
    set_audit_request_context(ip_address=ip, user_agent=request.headers.get("user-agent"))
    try:
        return await call_next(request)
    finally:
        clear_audit_request_context()


@app.middleware("http")
async def audit_mutations_middleware(request: Request, call_next):
    if request.method not in ("POST", "PUT", "PATCH", "DELETE") or not request.url.path.startswith("/api/admin"):
        return await call_next(request)

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        body_content = "<multipart_file_upload>"
    else:
        try:
            body_bytes = await request.body()
            async def receive(): return {"type": "http.request", "body": body_bytes}
            request._receive = receive
            body_content = body_bytes.decode('utf-8')
            if "application/json" in content_type:
                body_content = json.loads(body_content)
        except Exception:
            body_content = "<unparseable>"

    response = await call_next(request)

    if 200 <= response.status_code < 300:
        auth_header = request.headers.get("Authorization")
        actor_username = "unknown"
        if auth_header and auth_header.startswith("Bearer "):
            try:
                payload = jwt.decode(auth_header.split(" ")[1], ADMIN_SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False})
                actor_username = payload.get("sub", "unknown")
            except Exception:
                pass
        
        try:
            with get_db_context() as conn:
                record_admin_audit_event(
                    conn,
                    action=f"{request.method} {request.url.path}",
                    actor={"username": actor_username},
                    resource_type="api_endpoint",
                    resource_id=request.url.path,
                    details={"request_body": body_content, "query_params": dict(request.query_params)}
                )
        except Exception as e:
            pass

    return response




# slowapi requires the limiter on app.state plus an app-level exception handler
if RATE_LIMIT_ENABLED:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    # SECURITY FIX: Restricted CORS to specific trusted origins only
    # Wildcard (*) allows any website to make cross-origin requests
    allow_origins=os.getenv("CORS_ORIGINS", "https://your-production-domain.com,https://your-admin-domain.com,http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language", "X-Requested-With"],
    allow_credentials=True,
)

# SECURITY FIX: Add security headers to prevent common web vulnerabilities
app.add_middleware(
    SecurityHeadersMiddleware,
    content_security_policy="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:;",
    force_https=FORCE_HTTPS,
    frame_options="DENY",
    content_type_nosniff=True,
    strict_transport_security="max-age=31536000; includeSubDomains; preload",
    referrer_policy="strict-origin-when-cross-origin",
    x_xss_protection="1; mode=block",
    x_content_type_options="nosniff",
    x_frame_options="DENY",
)

# SECURITY FIX: Enforce HTTPS redirect (in addition to FastAPI's https_redirect option)
# This provides an additional layer of protection
if FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)

app.include_router(chat_router, tags=["chat"])
app.include_router(faqs_router, tags=["faqs"])
app.include_router(status_router, tags=["status"])
app.include_router(admin_router, tags=["admin"])
app.include_router(auth_router, tags=["auth"])
app.include_router(chat_admin_router, tags=["chat-admin"])
app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
app.include_router(faq_router, tags=["faq"])
app.include_router(kb_router, tags=["kb"])
app.include_router(catalog_router, tags=["catalog"])
app.include_router(distributors_router, tags=["distributors"])
app.include_router(campaigns_router, tags=["campaigns"])
app.include_router(unified_router, tags=["unified"])
app.include_router(inbox_router, tags=["inbox"])
app.include_router(dynamic_config_router, tags=["dynamic-config"])
app.include_router(orders_router, tags=["orders"])
app.include_router(complaints_router, tags=["complaints"])
app.include_router(tenants_router, tags=["tenants"])
app.include_router(offerings_router, tags=["offerings"])
app.include_router(conversations_router, tags=["conversations"])
app.include_router(tenant_files_router, tags=["tenant-files"])
app.include_router(tenant_chat_router, tags=["tenant-chat"])
app.include_router(tenant_operations_router, tags=["tenant-operations"])
app.include_router(leads_router, tags=["leads"])
app.include_router(api_onboarding_router, tags=["api-onboarding"])
app.include_router(audit_router, tags=["audit-history"])
app.include_router(audit_logs_router, tags=["audit-logs"])
app.include_router(tenant_approvals_router, tags=["tenant-approvals"])
app.include_router(integrations_router, tags=["integrations"])
app.include_router(callbacks_router, tags=["callbacks"])

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
if os.path.isdir(IMAGES_DIR):
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

UPLOADED_DIR = os.path.join(os.path.dirname(__file__), "uploaded_files")
if os.path.isdir(UPLOADED_DIR):
    app.mount("/uploaded_files", StaticFiles(directory=UPLOADED_DIR), name="uploaded-files")

ADMIN_BUILD_DIR = os.path.join(os.path.dirname(__file__), "admin_build")


@app.get("/")
def root():
    return {
        "status": "Unified Bot Service running",
    }


@app.get("/chat-history")
def legacy_chat_history():
    """Legacy compatibility route used by old admin panel."""
    from database import get_db
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM chat_history ORDER BY created_at DESC LIMIT 50").fetchall()
        return {"history": [dict(row) for row in rows]}
    finally:
        conn.close()


@app.post("/classify")
async def classify(request: Request):
    body = await request.json()
    text = body.get("message", "")
    return {"message": text, "type": classify_query(text)}


@app.post("/forward")
async def forward(request: Request):
    body = await request.json()
    text = body.get("message", "")
    qtype = body.get("type") or classify_query(text)
    answer = await forward_to_bot(qtype, text)
    return {"type": qtype, "answer": answer}


if os.path.isdir(ADMIN_BUILD_DIR):
    admin_assets_dir = os.path.join(ADMIN_BUILD_DIR, "assets")
    if os.path.isdir(admin_assets_dir):
        app.mount("/assets", StaticFiles(directory=admin_assets_dir), name="admin-assets")

    @app.get("/admin")
    @app.get("/admin/{full_path:path}")
    def serve_admin(full_path: str = ""):
        file_path = os.path.join(ADMIN_BUILD_DIR, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(ADMIN_BUILD_DIR, "index.html"))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=ROUTER_PORT, reload=False)
