"""Starts the four services on throwaway e2e_* databases, wired like production: Identity signs RS256 session tokens
(JWKS), every service verifies them and checks revocation; services use client-credentials service tokens."""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # the folder holding the four service folders and evr-erp-deploy
cfg = json.load(open(HERE / "e2e_secrets.json"))
key = next(l.split("=", 1)[1].strip().strip('"') for l in open(ROOT / "identity-service/.env") if l.startswith("JWT_PRIVATE_KEY="))
key = key.replace("\\n", "\n")
ORIGIN = '["http://localhost:5173"]'
ID = "http://127.0.0.1:8001"
verify = {"AUTH_JWKS_URL": f"{ID}/.well-known/jwks.json", "AUTH_JWT_PUBLIC_KEY": "", "AUTH_JWT_ISSUER": "evr-identity", "AUTH_JWT_AUDIENCE": "evr-erp",
          "AUTH_REVOCATION_URL": f"{ID}/internal/sessions", "AUTH_REVOCATION_CACHE_SECONDS": "0", "AUTH_DEV_MODE": "false", "IDENTITY_BASE_URL": ID, "ALLOWED_ORIGINS": ORIGIN}
c = cfg["clients"]
services = {
    "identity": (8001, {"DATABASE_URL": cfg["db"]["identity"], "JWT_PRIVATE_KEY": key, "AUTH_COOKIE_SECURE": "false", "ALLOWED_ORIGINS": ORIGIN, "HRMS_BASE_URL": "http://127.0.0.1:8000",
                        "SERVICE_CLIENTS": json.dumps({k: hashlib.sha256(v.encode()).hexdigest() for k, v in c.items()}),
                        "SERVICE_CLIENT_SCOPES": json.dumps({"hrms-service": ["identity:sessions.read", "identity:users.read", "platform:notifications.write"],
                                                             "platform-service": ["identity:sessions.read", "identity:users.read"], "manufacturing-service": ["identity:sessions.read"]})}),
    "hrms": (8000, {**verify, "DATABASE_URL": cfg["db"]["hrms"], "IDENTITY_CLIENT_ID": "hrms-service", "IDENTITY_CLIENT_SECRET": c["hrms-service"],
                    "PLATFORM_NOTIFICATIONS_URL": "http://127.0.0.1:8002/internal/notifications", "PLATFORM_SERVICE_TOKEN": ""}),
    "platform": (8002, {**verify, "DATABASE_URL": cfg["db"]["platform"], "IDENTITY_CLIENT_ID": "platform-service", "IDENTITY_CLIENT_SECRET": c["platform-service"], "HRMS_BASE_URL": "http://127.0.0.1:8000"}),
    "manufacturing": (8003, {**verify, "DATABASE_URL": cfg["db"]["manufacturing"], "IDENTITY_CLIENT_ID": "manufacturing-service", "IDENTITY_CLIENT_SECRET": c["manufacturing-service"]}),
}


def env_for(name):
    port, extra = services[name]
    return {**os.environ, "ENVIRONMENT": "development", "LOG_LEVEL": "WARNING", **extra}


if __name__ == "__main__":
    for name, (port, _) in services.items():
        d = ROOT / f"{name}-service"
        subprocess.run([str(d / ".venv/bin/alembic"), "upgrade", "head"], cwd=d, env=env_for(name), check=True, capture_output=True)
        log = open(HERE / f"{name}.log", "w")
        subprocess.Popen([str(d / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=d, env=env_for(name), stdout=log, stderr=log, start_new_session=True)
    time.sleep(6)
    print("started")
