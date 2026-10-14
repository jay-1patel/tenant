import os
import re

routes_dir = "backend/routes"
no_depends = []
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
            if "Depends" not in func_args:
                route_path = route_args.strip().split(",")[0].strip("\"' ")
                no_depends.append((fn, method.upper(), route_path, func_name))

print(f"Total routes with ZERO Depends: {len(no_depends)}")
for fn, method, path, func in no_depends:
    print(f"{fn:25} | {method:6} | {path:40} | {func}")
