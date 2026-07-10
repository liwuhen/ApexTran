"""Shared identity and authorization helpers for apextran-app modules.

Public module endpoints ignore identity. Private endpoints should depend on
``require_current_user`` / ``require_scope`` so JWT parsing, audience checks and
scope checks stay centralized instead of being reimplemented per module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from ..config import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    scopes: frozenset[str]
    jti: str = ""

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def get_user_id(request: Request) -> str:
    """Legacy trusted-header identity used by analysis/WebChannel paths."""

    raw = (request.headers.get("X-ApexTran-User") or "").strip()
    return _SAFE.sub("", raw)[:128] or "default"


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}")
    except Exception as exc:
        raise ValueError("invalid base64url") from exc


def _json_decode(segment: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_b64url_decode(segment))
    except Exception as exc:
        raise ValueError("invalid jwt json") from exc
    if not isinstance(decoded, dict):
        raise TypeError("invalid jwt object")
    return decoded


def _scope_set(value: object) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset(part for part in value.split() if part)
    if isinstance(value, list):
        return frozenset(item for item in value if isinstance(item, str) and item)
    return frozenset()


def _verify_hs256(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid jwt format")
    header_segment, payload_segment, signature_segment = parts
    header = _json_decode(header_segment)
    if header.get("alg") != "HS256":
        raise ValueError("unsupported jwt alg")
    signing_input = f"{header_segment}.{payload_segment}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    supplied = _b64url_decode(signature_segment)
    if not hmac.compare_digest(expected, supplied):
        raise ValueError("invalid jwt signature")
    return _json_decode(payload_segment)


def _audience_matches(claim: object, expected: str) -> bool:
    if isinstance(claim, str):
        return claim == expected
    if isinstance(claim, list):
        return expected in claim
    return False


def _claims_to_current_user(claims: dict[str, Any]) -> CurrentUser:
    settings = get_settings()
    now = int(time.time())
    if claims.get("iss") != settings.internal_jwt_issuer:
        raise ValueError("invalid issuer")
    if not _audience_matches(claims.get("aud"), settings.internal_jwt_audience):
        raise ValueError("invalid audience")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp <= now:
        raise ValueError("jwt expired")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ValueError("missing subject")
    if len(sub) > 128 or _SAFE.search(sub):
        raise ValueError("invalid subject")
    return CurrentUser(
        user_id=sub,
        scopes=_scope_set(claims.get("scope")),
        jti=str(claims.get("jti") or ""),
    )


async def require_current_user(request: Request) -> CurrentUser:
    auth = request.headers.get("authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    secret = get_settings().internal_jwt_secret
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="internal jwt is not configured")

    try:
        return _claims_to_current_user(_verify_hs256(token.strip(), secret))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_scope(scope: str) -> Callable[[Annotated[CurrentUser, Depends(require_current_user)]], CurrentUser]:
    def dependency(user: Annotated[CurrentUser, Depends(require_current_user)]) -> CurrentUser:
        if not user.has_scope(scope):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient scope")
        return user

    return dependency
