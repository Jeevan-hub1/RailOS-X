"""
RailOS Authentication and Authorization Middleware
====================================================
FastAPI dependency that:
  1. Extracts Bearer JWT from Authorization header
  2. Validates RS256 signature using Keycloak JWKS (cached, 300s TTL)
  3. Extracts realm_access.roles from claims
  4. Checks caller roles against the permission matrix (role_permissions.py)
  5. Returns HTTP 401 on missing/invalid token
  6. Returns HTTP 403 + audit log entry when role is insufficient

Design §9.1 / Req 23 / Req 24 / Task 15.4
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from keycloak_jwks import JWTError, decode_token, get_roles_from_claims
from role_permissions import is_permitted

log = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "AUDIT_DATABASE_URL",
    "postgresql://railos_app:CHANGE_ME@postgresql-primary.railos.svc.cluster.local:5432/railos_audit",
)

_security = HTTPBearer(auto_error=False)
_db_pool: asyncpg.Pool | None = None


async def get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _db_pool


async def _write_auth_audit(
    pool: asyncpg.Pool,
    user_identity: str,
    attempted_action: str,
    endpoint: str,
    allowed: bool,
    reason: str,
) -> None:
    """Append audit record to auth_audit table (append-only — no UPDATE/DELETE)."""
    sql = """
        INSERT INTO auth_audit
            (audit_id, user_identity, attempted_action, endpoint, allowed, reason, timestamp_utc)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                sql,
                str(uuid.uuid4()),
                user_identity,
                attempted_action,
                endpoint,
                allowed,
                reason,
                datetime.now(timezone.utc),
            )
    except Exception as exc:
        # Log the failure but do not block the request on audit write failure
        log.error("Auth audit write failed: %s", exc)


class RailOSAuthMiddleware:
    """
    Reusable FastAPI dependency class.
    Usage:
        @app.get("/api/v1/advisories")
        async def get_advisories(auth=Depends(RailOSAuthMiddleware())):
            ...
    """

    async def __call__(
        self,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
    ) -> dict[str, Any]:
        # ── 1. Token extraction ───────────────────────────────────────────────
        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials

        # ── 2. Token validation ───────────────────────────────────────────────
        try:
            claims = decode_token(token)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        caller_roles = get_roles_from_claims(claims)
        user_identity = claims.get("sub", "unknown")
        preferred_username = claims.get("preferred_username", user_identity)

        # ── 3. Role-based authorization ───────────────────────────────────────
        method = request.method
        path   = request.url.path
        permitted, reason = is_permitted(method, path, caller_roles)

        # ── 4. Audit log ───────────────────────────────────────────────────────
        try:
            pool = await get_db_pool()
            await _write_auth_audit(
                pool=pool,
                user_identity=preferred_username,
                attempted_action=f"{method} {path}",
                endpoint=path,
                allowed=permitted,
                reason=reason,
            )
        except Exception as exc:
            log.error("Audit pool unavailable: %s", exc)

        # ── 5. Deny if not permitted ──────────────────────────────────────────
        if not permitted:
            log.warning(
                "RBAC denial: user=%s roles=%s %s %s reason=%s",
                preferred_username, sorted(caller_roles), method, path, reason,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {reason}",
            )

        log.debug("Auth OK: user=%s roles=%s %s %s", preferred_username, sorted(caller_roles), method, path)
        return {"user": preferred_username, "sub": user_identity, "roles": caller_roles, "claims": claims}


# Singleton instance for use as a FastAPI Depends
require_auth = RailOSAuthMiddleware()
