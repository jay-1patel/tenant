import os
import re

findings = []
for root, dirs, files in os.walk("backend"):
    for fn in files:
        if fn.endswith(".py"):
            p = os.path.join(root, fn)
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            matches = re.findall(r"(\w+\.execute\(\s*f[\"'].*?[\"'])", content, re.DOTALL)
            for m in matches:
                if "{" in m:
                    findings.append((fn, m.strip().replace("\n", " ")))

print(f"Total dynamic execute statements: {len(findings)}")
for fn, stmt in findings[:50]:
    print(f"{fn:25} | {stmt[:90]}")
