from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

SESSION_COOKIE = "hengjian_session"


class LocalSessionGuard:
    def __init__(self) -> None:
        self._token = secrets.token_urlsafe(32)

    @property
    def token(self) -> str:
        return self._token

    def verify(self, request: Request) -> None:
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅允许本机访问")
        if request.cookies.get(SESSION_COOKIE) != self._token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="本机会话无效")
