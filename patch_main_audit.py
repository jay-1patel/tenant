import os

filepath = "backend/main.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

if "audit_mutations_middleware" not in content:
    # Add imports
    content = content.replace(
        "from fastapi import FastAPI, Request",
        "from fastapi import FastAPI, Request\nimport json\nimport jwt\nfrom routing.config import ADMIN_SECRET_KEY\nfrom database import get_db_context, record_admin_audit_event"
    )

    middleware_code = """
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

"""
    # Find a good place to inject the middleware, e.g., after audit_request_context
    target_str = """    finally:
        clear_audit_request_context()"""
    
    if target_str in content:
        content = content.replace(target_str, target_str + "\n\n" + middleware_code)
    else:
        print("Could not find injection target in main.py")
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
        print("Patched main.py with audit_mutations_middleware")
