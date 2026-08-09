from __future__ import annotations

import base64
import binascii
import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp, *, username: str, password: str) -> None:
        self.app = app
        self.username = username.encode()
        self.password = password.encode()

    def authorized(self, authorization: str | None) -> bool:
        if not authorization:
            return False
        scheme, separator, credentials = authorization.partition(" ")
        if not separator or scheme.casefold() != "basic":
            return False
        try:
            decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        username, separator, password = decoded.partition(":")
        if not separator:
            return False
        username_matches = secrets.compare_digest(username.encode(), self.username)
        password_matches = secrets.compare_digest(password.encode(), self.password)
        return username_matches and password_matches

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        if self.authorized(Headers(scope=scope).get("authorization")):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Referral Job Monitor", charset="UTF-8"'},
        )
        await response(scope, receive, send)
