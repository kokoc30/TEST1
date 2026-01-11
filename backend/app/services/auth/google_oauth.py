# app/services/auth/google_oauth.py  (UPDATED)

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlencode

import httpx

from app.core.settings import (
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REDIRECT_URI,
    GOOGLE_OAUTH_SCOPES,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class OAuthError(Exception):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _b64url(digest)


def _extract_client_id_secret(data: dict) -> tuple[str, str]:
    block = data.get("web") or data.get("installed") or {}
    cid = (block.get("client_id") or "").strip()
    sec = (block.get("client_secret") or "").strip()
    return cid, sec


def _try_load_client_secrets_json() -> tuple[str, str]:
    """
    Priority:
      1) env GOOGLE_OAUTH_CLIENT_ID/SECRET (or GOOGLE_CLIENT_ID/SECRET via settings)
      2) env GOOGLE_OAUTH_CLIENT_SECRETS_FILE (downloaded OAuth client JSON)
      3) backend/keys common filenames + glob client_secret*.json
    """
    cid = (GOOGLE_OAUTH_CLIENT_ID or "").strip()
    sec = (GOOGLE_OAUTH_CLIENT_SECRET or "").strip()
    if cid and sec:
        return cid, sec

    here = Path(__file__).resolve()
    backend_root = here.parents[3]  # .../backend
    keys_dir = backend_root / "keys"

    candidates: list[Path] = []

    env_path = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "") or "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = (backend_root / p).resolve()
        candidates.append(p)

    for name in ("oauth_client.json", "google_oauth.json", "client_secret.json", "oauth.json"):
        candidates.append(keys_dir / name)

    # also accept Google's typical downloaded name: client_secret_*.json
    try:
        if keys_dir.exists():
            candidates.extend(sorted(keys_dir.glob("client_secret*.json")))
    except Exception:
        pass

    for p in candidates:
        try:
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            c, s = _extract_client_id_secret(data)
            if c and s:
                return c, s
        except Exception:
            continue

    return cid, sec


def _pkce_verifier() -> str:
    """
    RFC7636: verifier length 43..128.
    secrets.token_urlsafe(64) ~ 86 chars; clamp to 128 and ensure >= 43.
    """
    v = secrets.token_urlsafe(64)
    v = v[:128]
    if len(v) < 43:
        v = (v + secrets.token_urlsafe(64))[:43]
    return v


@dataclass
class GoogleOAuthClient:
    timeout_s: float = 12.0
    _cached: tuple[str, str] | None = field(default=None, init=False, repr=False)

    def _client_id_secret(self) -> tuple[str, str]:
        if self._cached:
            return self._cached

        cid, sec = _try_load_client_secrets_json()
        cid = (cid or "").strip()
        sec = (sec or "").strip()

        if not cid or not sec:
            raise OAuthError(
                "Google OAuth client ID/secret missing. "
                "Set GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET "
                "(or GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET), "
                "or set GOOGLE_OAUTH_CLIENT_SECRETS_FILE to your downloaded OAuth JSON."
            )

        self._cached = (cid, sec)
        return cid, sec

    def _redirect_uri(self) -> str:
        ru = (GOOGLE_OAUTH_REDIRECT_URI or "").strip()
        if not ru:
            raise OAuthError(
                "GOOGLE_OAUTH_REDIRECT_URI is empty. "
                "Set BASE_URL so redirect becomes <BASE_URL>/api/auth/callback."
            )
        return ru

    def build_authorize_url(self) -> Tuple[str, str, str]:
        client_id, _ = self._client_id_secret()
        redirect_uri = self._redirect_uri()

        state = secrets.token_urlsafe(24)

        verifier = _pkce_verifier()
        challenge = _pkce_challenge(verifier)

        scopes = GOOGLE_OAUTH_SCOPES or ["openid", "email", "profile"]
        scope = " ".join([s for s in scopes if (s or "").strip()])

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "include_granted_scopes": "true",
            "prompt": "select_account",
        }

        return state, verifier, f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> Dict[str, Any]:
        client_id, client_secret = self._client_id_secret()
        redirect_uri = self._redirect_uri()

        code = (code or "").strip()
        code_verifier = (code_verifier or "").strip()
        if not code or not code_verifier:
            raise OAuthError("Missing code or code_verifier")

        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }

        try:
            timeout = httpx.Timeout(self.timeout_s)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(TOKEN_URL, data=data)
        except Exception as e:
            raise OAuthError(f"Token exchange request failed: {e}")

        if r.status_code >= 400:
            msg = r.text
            try:
                j = r.json()
                msg = j.get("error_description") or j.get("error") or msg
            except Exception:
                pass
            raise OAuthError(f"Token exchange failed: {msg}")

        j = r.json()
        access_token = (j.get("access_token") or "").strip()
        if not access_token:
            raise OAuthError("Token exchange returned no access_token")

        out: Dict[str, Any] = {"access_token": access_token}
        for k in ("id_token", "refresh_token", "expires_in", "scope", "token_type"):
            if k in j:
                out[k] = j.get(k)
        return out

    async def fetch_userinfo(self, *, access_token: str) -> Dict[str, str]:
        access_token = (access_token or "").strip()
        if not access_token:
            raise OAuthError("Missing access_token")

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            timeout = httpx.Timeout(self.timeout_s)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(USERINFO_URL, headers=headers)
        except Exception as e:
            raise OAuthError(f"Userinfo request failed: {e}")

        if r.status_code >= 400:
            raise OAuthError(f"Userinfo fetch failed: {r.text}")

        j = r.json()
        return {
            "sub": (j.get("sub") or "").strip(),
            "email": (j.get("email") or "").strip(),
            "name": (j.get("name") or "").strip(),
            "picture": (j.get("picture") or "").strip(),
        }
