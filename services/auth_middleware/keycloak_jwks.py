"""
Keycloak JWKS Fetcher / Cache
==============================
Fetches the RS256 public-key set from Keycloak and caches it with a 300-second TTL.
Background refresh runs 30 seconds before expiry to avoid blocking requests.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

log = logging.getLogger(__name__)

KEYCLOAK_ISSUER = os.environ.get(
    "KEYCLOAK_ISSUER",
    "http://keycloak.railos.svc.cluster.local:8080/realms/railos",
)
JWKS_URI = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs"
JWKS_CACHE_TTL = int(os.environ.get("JWKS_CACHE_TTL_SECONDS", "300"))
ALGORITHMS = ["RS256"]


class JWKSCache:
    """Thread-safe JWKS cache with background refresh."""

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}
        self._expires_at: float = 0.0
        self._lock = threading.RLock()
        self._refresh_thread: threading.Thread | None = None

    def _fetch(self) -> dict[str, Any]:
        """Fetch JWKS from Keycloak; raises on failure."""
        resp = httpx.get(JWKS_URI, timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def _refresh(self) -> None:
        """Refresh JWKS and update expiry."""
        try:
            jwks = self._fetch()
            with self._lock:
                self._keys = jwks
                self._expires_at = time.monotonic() + JWKS_CACHE_TTL
            log.info("JWKS cache refreshed; %d keys loaded", len(jwks.get("keys", [])))
        except Exception as exc:
            log.error("JWKS refresh failed: %s", exc)

    def _schedule_background_refresh(self) -> None:
        """Schedule a background refresh 30s before TTL expires."""
        delay = max(0.0, self._expires_at - time.monotonic() - 30)

        def _run():
            time.sleep(delay)
            self._refresh()

        t = threading.Thread(target=_run, daemon=True, name="jwks-refresh")
        t.start()
        self._refresh_thread = t

    def get(self) -> dict[str, Any]:
        """Return cached JWKS, refreshing synchronously if expired."""
        with self._lock:
            if time.monotonic() >= self._expires_at:
                self._refresh()
                self._schedule_background_refresh()
            return self._keys


_cache = JWKSCache()


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate an RS256 JWT from Keycloak.
    Returns the claims dict on success.
    Raises jose.JWTError (or subclass) on failure.
    """
    jwks = _cache.get()
    claims = jwt.decode(
        token,
        jwks,
        algorithms=ALGORITHMS,
        issuer=KEYCLOAK_ISSUER,
        options={
            "verify_exp": True,
            "verify_aud": False,   # audience check done by individual services
        },
    )
    return claims


def get_roles_from_claims(claims: dict[str, Any]) -> set[str]:
    """Extract realm roles from the Keycloak JWT claims."""
    return set(claims.get("realm_access", {}).get("roles", []))
