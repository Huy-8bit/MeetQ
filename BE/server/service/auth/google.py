"""Verification of Google Identity Services ID tokens (the `credential` the
frontend receives from the Sign in with Google button).

Checks: RS256 signature against Google's published keys, `aud` == our client
ID, `iss` is Google, not expired, `email_verified`, optional domain allow-list.
https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

import httpx
from jose import ExpiredSignatureError, JWTError, jwt

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
_DEFAULT_JWKS_TTL_SECONDS = 3600
_MAX_AGE_RE = re.compile(r"max-age=(\d+)")

JwksFetcher = Callable[[], Awaitable[tuple[Dict[str, Any], int]]]


class GoogleTokenError(Exception):
    """The credential is not a valid Google ID token for this app."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GoogleAccountNotAllowedError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: Optional[str]
    picture: Optional[str]
    hosted_domain: Optional[str]


async def fetch_google_jwks() -> tuple[Dict[str, Any], int]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(GOOGLE_JWKS_URL)
        response.raise_for_status()
        match = _MAX_AGE_RE.search(response.headers.get("cache-control", ""))
        ttl = int(match.group(1)) if match else _DEFAULT_JWKS_TTL_SECONDS
        return response.json(), ttl


class GoogleIdTokenVerifier:
    def __init__(
        self,
        client_id: str,
        *,
        allowed_domains: Iterable[str] = (),
        jwks_fetcher: JwksFetcher = fetch_google_jwks,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.allowed_domains = {domain.strip().lower() for domain in allowed_domains if domain.strip()}
        self._fetch = jwks_fetcher
        self._clock = clock
        self._jwks: Optional[Dict[str, Any]] = None
        self._jwks_expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _keys(self, *, force: bool = False) -> Dict[str, Any]:
        async with self._lock:
            if force or self._jwks is None or self._clock() >= self._jwks_expires_at:
                jwks, ttl = await self._fetch()
                self._jwks = jwks
                self._jwks_expires_at = self._clock() + max(60, ttl)
            return self._jwks

    async def _key_for(self, kid: Optional[str]) -> Dict[str, Any]:
        for force in (False, True):  # refetch once: Google rotates keys
            jwks = await self._keys(force=force)
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    return key
        raise GoogleTokenError("unknown_signing_key")

    async def verify(self, credential: str) -> GoogleIdentity:
        try:
            header = jwt.get_unverified_header(credential)
        except JWTError:
            raise GoogleTokenError("malformed_token")
        if header.get("alg") != "RS256":
            raise GoogleTokenError("unexpected_algorithm")
        key = await self._key_for(header.get("kid"))
        try:
            claims = jwt.decode(
                credential,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"verify_at_hash": False},
            )
        except ExpiredSignatureError:
            raise GoogleTokenError("expired")
        except JWTError:
            raise GoogleTokenError("invalid_signature_or_claims")

        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise GoogleTokenError("unexpected_issuer")
        if claims.get("email_verified") not in (True, "true"):
            raise GoogleTokenError("email_not_verified")
        subject = str(claims.get("sub") or "")
        email = str(claims.get("email") or "").strip().lower()
        if not subject or not email:
            raise GoogleTokenError("missing_identity")

        hosted_domain = (claims.get("hd") or "").lower() or None
        if self.allowed_domains:
            email_domain = email.rsplit("@", 1)[-1]
            if email_domain not in self.allowed_domains and hosted_domain not in self.allowed_domains:
                raise GoogleAccountNotAllowedError()

        return GoogleIdentity(
            subject=subject,
            email=email,
            name=(claims.get("name") or None),
            picture=(claims.get("picture") or None),
            hosted_domain=hosted_domain,
        )
