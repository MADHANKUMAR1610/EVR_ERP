"""Checks that every frontend call (hrms-service/tools/endpoint_map.tsv: method + path of all 178 calls) has a route in exactly
one service, and that nginx.conf sends it to that service. Run from the folder holding the four services:

    python evr-erp-deploy/tools/route_coverage.py
"""
import json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = {"hrms": "hrms-service", "identity": "identity-service", "platform": "platform-service", "manufacturing": "manufacturing-service"}
norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)  # noqa: E731
routes = {}
for d in SERVICES.values():
    out = subprocess.run([str(ROOT / d / ".venv/bin/python"), "-c", "import json\nfrom app.main import create_app\nprint(json.dumps(sorted({m+' '+r.path for r in create_app().routes if hasattr(r,'methods') for m in r.methods})))"],
                         cwd=ROOT / d, capture_output=True, text=True, check=True).stdout
    routes[d] = {(x.split(" ", 1)[0], norm(x.split(" ", 1)[1])) for x in json.loads(out)}
conf = (ROOT / "evr-erp-deploy/nginx.conf").read_text()
locs = re.findall(r"location (?:= )?(/api/v1/\S+)\s+\{[^}]*proxy_pass http://(\w+)", conf)
calls = [l.rstrip("\n").split("\t") for l in open(ROOT / "hrms-service/tools/endpoint_map.tsv", encoding="utf-8")]
problems = []
for c in calls:
    key = (c[2], norm("/api/v1" + c[3]))
    owners = [d for d, rs in routes.items() if key in rs]
    loc = max((l for l in locs if ("/api/v1" + c[3]).startswith(l[0])), key=lambda l: len(l[0]), default=None)
    if len(owners) != 1 or not loc or SERVICES[loc[1]] != owners[0]:
        problems.append((c[2], c[3], owners, loc))
print(f"{len(calls)} frontend calls; problems: {problems or 'none'}")
raise SystemExit(1 if problems else 0)
