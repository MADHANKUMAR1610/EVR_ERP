"""Creates e2e_secrets.json for a local end-to-end run: the throwaway database URLs (e2e_<service>, built from each
service's own .env), random service-client secrets and a random first-administrator password. The file stays local
(never commit or zip it). Create the e2e_* databases first, owned by each service's database role."""
import json, secrets
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
db = {}
for s in ["identity", "hrms", "platform", "manufacturing"]:
    url = next(l.split("=", 1)[1].strip() for l in open(ROOT / f"{s}-service/.env") if l.startswith("DATABASE_URL="))
    db[s] = url.rsplit("/", 1)[0] + f"/e2e_{s}"
cfg = {"db": db, "clients": {c: secrets.token_urlsafe(24) for c in ["hrms-service", "platform-service", "manufacturing-service"]},
       "admin_password": "E2e-" + secrets.token_urlsafe(12) + "9a"}
path = HERE / "e2e_secrets.json"
path.write_text(json.dumps(cfg))
path.chmod(0o600)
print(f"Wrote {path}")
