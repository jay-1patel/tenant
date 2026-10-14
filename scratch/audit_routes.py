import os
import re

routes_dir = "backend/routes"
unprotected = []
for fn in os.listdir(routes_dir):
    if fn.endswith(".py"):
        path = os.path.join(routes_dir, fn)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        endpoints = re.findall(
            r"@router\.(get|post|put|delete|patch)\((.*?)\)\s*(?:@\w+.*?\s*)*(?:async\s+)?def\s+(\w+)\s*\((.*?)\):",
            content,
            re.DOTALL
        )
        for method, route_args, func_name, func_args in endpoints:
            has_auth = "Depends" in func_args and any(
                k in func_args.lower() for k in ["admin", "auth", "token", "user", "bearer", "security", "permission"]
            )
            route_path = route_args.strip().split(",")[0].strip("\"' ")
            if not has_auth:
                unprotected.append((fn, method.upper(), route_path, func_name))

print(f"Total potentially unprotected endpoints found: {len(unprotected)}")
for fn, method, path, func in unprotected[:40]:
    print(f"{fn:25} | {method:6} | {path:35} | {func}")
