"""HTTP authentication for TradeIQ.

Single-user app. When TRADEIQ_AUTH_USER and TRADEIQ_AUTH_PASSWORD are
set (or TRADEIQ_AUTH_TOKEN is set), every request except /api/health and
/api/keepalive must authenticate. When nothing is set, auth is off and
the app behaves exactly as before, with a warning in the startup log.

Why HTTP Basic auth: the browser prompts once on first page load and
then attaches the credentials to every same-origin fetch automatically,
so the React frontend needs no code change. A Bearer token is also
accepted, for scripts (curl -H "Authorization: Bearer <token>").

API keys (Anthropic, Polygon, Finnhub, Telegram) stay server-side
environment variables and are never involved in this check. This
middleware only gates who can reach the already-running app.
"""
import base64
import binascii
import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Liveness probes stay public so the external uptime pinger can hit
# them without credentials. Everything else is gated when auth is on.
PUBLIC_PATHS = {"/api/health", "/api/keepalive"}
REALM = "TradeIQ"


def _auth_config():
    """Read auth settings from the environment on every call.

    Read per request (not cached) so tests can toggle auth by setting
    env vars, and so a dashboard change takes effect on the next
    deploy without a code change. Values come from os.environ, which
    also picks up the repo .env file via config.py's load_dotenv.
    """
    return {
        "user": os.environ.get("TRADEIQ_AUTH_USER", "").strip(),
        "password": os.environ.get("TRADEIQ_AUTH_PASSWORD", ""),
        "token": os.environ.get("TRADEIQ_AUTH_TOKEN", "").strip(),
    }


def auth_enabled(cfg=None):
    """True when auth is fully configured (token, or user plus password)."""
    cfg = cfg or _auth_config()
    if cfg.get("token"):
        return True
    return bool(cfg.get("user") and cfg.get("password"))


def auth_status_message():
    """One-line startup log describing the auth state (no secrets)."""
    cfg = _auth_config()
    if cfg.get("token") and cfg.get("user"):
        return "AUTH: enabled (token plus basic user configured)"
    if cfg.get("token"):
        return "AUTH: enabled (token only)"
    if cfg.get("user") and cfg.get("password"):
        return "AUTH: enabled (basic user configured)"
    if cfg.get("user") or cfg.get("password"):
        return (
            "AUTH: WARNING: only one of TRADEIQ_AUTH_USER / "
            "TRADEIQ_AUTH_PASSWORD is set, auth is OFF. Set both to enable it."
        )
    return (
        "AUTH: WARNING: no TRADEIQ_AUTH_* set, app is open to anyone "
        "with the URL. Set TRADEIQ_AUTH_USER and TRADEIQ_AUTH_PASSWORD "
        "in the Render dashboard to lock it down."
    )


def _basic_ok(authorization, cfg):
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    username, _, password = decoded.partition(":")
    if not username or not cfg.get("user"):
        return False
    return secrets.compare_digest(username, cfg["user"]) and secrets.compare_digest(
        password, cfg["password"]
    )


def _bearer_ok(authorization, cfg):
    if not authorization or not cfg.get("token"):
        return False
    scheme, _, token = authorization.partition(" ")
    return scheme == "Bearer" and bool(token) and secrets.compare_digest(token, cfg["token"])


def is_authorized(request, cfg=None):
    """True when the request may proceed: auth off, or valid credentials."""
    cfg = cfg or _auth_config()
    if not auth_enabled(cfg):
        return True
    authorization = request.headers.get("authorization", "")
    if _bearer_ok(authorization, cfg):
        return True
    if _basic_ok(authorization, cfg):
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate every route except the public liveness endpoints, when auth is on."""

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path.rstrip("/") or "/"
        if path in PUBLIC_PATHS:
            return await call_next(request)
        if is_authorized(request):
            return await call_next(request)
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="%s"' % REALM},
        )
