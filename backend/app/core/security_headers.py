"""Response hardening headers applied to every API response.

A small middleware rather than per-route headers so nothing can forget it:
the values are all additive protections for a JSON API that serves its own
SPA on another origin. HSTS is only set when the request arrived over HTTPS
(directly, or via a trusted X-Forwarded-Proto hop), so plain-HTTP local
development is unaffected.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# Paths that carry credentials or full data dumps: nothing may cache them.
_NO_STORE_PREFIXES = ("/api/auth", "/api/export")


def _is_https_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    # Only trust the forwarded proto when the deploy declared its proxies.
    from app.core.config import get_settings

    if get_settings().trusted_proxy_hops > 0:
        return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in _STATIC_HEADERS.items():
            response.headers.setdefault(key, value)
        if _is_https_request(request):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        if request.url.path.startswith(_NO_STORE_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
        return response
