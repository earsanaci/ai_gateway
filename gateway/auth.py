"""Gateway erisim anahtari dogrulamasi (Bearer)."""
import hmac

from starlette.responses import JSONResponse

from gateway.config import GATEWAY_TOKEN
from gateway.core import audit


class BearerAuth:
    def __init__(self, app):
        self.app = app
        self.expected = f"Bearer {GATEWAY_TOKEN}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                audit({"event": "auth_denied", "client": (scope.get("client") or [None])[0],
                       "path": scope.get("path")})
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)

