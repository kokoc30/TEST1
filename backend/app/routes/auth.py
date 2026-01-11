# app/routes/auth.py

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import FRONTEND_URL
from app.db.db import get_db
from app.services.auth.google_oauth import GoogleOAuthClient, OAuthError
from app.services.storage.history_store import HistoryStore

router = APIRouter(tags=["auth"])
oauth = GoogleOAuthClient()


def _session_user(request: Request) -> Optional[dict]:
    try:
        u = request.session.get("user")  # type: ignore[attr-defined]
        return u if isinstance(u, dict) else None
    except Exception:
        return None


def _require_user(request: Request) -> dict:
    u = _session_user(request)
    if not u:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return u


def _safe_next_url(next_url: str) -> str:
    """
    Allow:
      - relative paths like /kiosk.html (NOT //kiosk.html)
      - absolute URLs that start with FRONTEND_URL (if set)
    """
    nxt = (next_url or "").strip()
    if not nxt:
        return ""

    # block scheme-relative redirects
    if nxt.startswith("//"):
        return ""

    if nxt.startswith("/"):
        return nxt

    fe = (FRONTEND_URL or "").strip().rstrip("/")
    if fe and nxt.startswith(fe):
        return nxt

    return ""


@router.get("/auth/login")
async def login(request: Request, next: str = "/kiosk.html") -> RedirectResponse:
    """
    Starts Google OAuth flow. Sets state + PKCE verifier in session cookie, then redirects to Google.
    """
    if not hasattr(request, "session"):
        raise HTTPException(
            status_code=500,
            detail="Session middleware not enabled (SESSION_SECRET missing?)",
        )

    safe_next = _safe_next_url(next) or "/kiosk.html"

    state, verifier, authorize_url = oauth.build_authorize_url()

    request.session["oauth_state"] = state  # type: ignore[attr-defined]
    request.session["oauth_verifier"] = verifier  # type: ignore[attr-defined]
    request.session["oauth_next"] = safe_next  # type: ignore[attr-defined]

    return RedirectResponse(url=authorize_url, status_code=302)


# IMPORTANT:
# Do NOT use a union return type like RedirectResponse | JSONResponse in FastAPI,
# it triggers response-model generation errors at import-time.
@router.get("/auth/callback", response_model=None)
async def callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth callback URL registered in Google Console:
      http://localhost:8000/api/auth/callback
      (or https://<BACKEND_PUBLIC_URL>/api/auth/callback)
    """
    if not hasattr(request, "session"):
        raise HTTPException(
            status_code=500,
            detail="Session middleware not enabled (SESSION_SECRET missing?)",
        )

    qp = request.query_params

    if qp.get("error"):
        detail = qp.get("error_description") or qp.get("error") or "OAuth error"
        raise HTTPException(status_code=400, detail=detail)

    code = (qp.get("code") or "").strip()
    state = (qp.get("state") or "").strip()

    expected_state = (request.session.get("oauth_state") or "").strip()  # type: ignore[attr-defined]
    verifier = (request.session.get("oauth_verifier") or "").strip()  # type: ignore[attr-defined]
    next_url = (request.session.get("oauth_next") or "").strip()  # type: ignore[attr-defined]

    # one-time cleanup
    try:
        request.session.pop("oauth_state", None)  # type: ignore[attr-defined]
        request.session.pop("oauth_verifier", None)  # type: ignore[attr-defined]
        request.session.pop("oauth_next", None)  # type: ignore[attr-defined]
    except Exception:
        pass

    if not code or not state or not expected_state or state != expected_state or not verifier:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        tokens = await oauth.exchange_code(code=code, code_verifier=verifier)
        userinfo = await oauth.fetch_userinfo(access_token=tokens["access_token"])
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    sub = (userinfo.get("sub") or "").strip()
    email = (userinfo.get("email") or "").strip().lower()
    name = (userinfo.get("name") or "").strip()
    picture = (userinfo.get("picture") or "").strip()

    if not sub:
        raise HTTPException(status_code=400, detail="Google userinfo missing sub")

    from app.db.models import User  # local import to avoid circular

    user = await User.upsert_google_user(
        db,
        google_sub=sub,
        email=email,
        name=name,
        picture=picture,
    )

    request.session["user"] = {  # type: ignore[attr-defined]
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "google_sub": user.google_sub,
    }

    nxt = _safe_next_url(next_url) or "/kiosk.html"
    fe = (FRONTEND_URL or "").strip().rstrip("/")

    # redirect back to frontend when configured
    if nxt.startswith("/") and fe:
        return RedirectResponse(url=f"{fe}{nxt}", status_code=302)
    if fe and nxt.startswith(fe):
        return RedirectResponse(url=nxt, status_code=302)

    # fallback (no FRONTEND_URL)
    return JSONResponse({"ok": True, "user": request.session["user"]})  # type: ignore[attr-defined]


@router.get("/auth/me")
async def me(request: Request) -> JSONResponse:
    u = _session_user(request)
    return JSONResponse({"user": u})


@router.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    try:
        request.session.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    return JSONResponse({"ok": True})


# -------------------------
# Per-user history endpoints
# -------------------------

@router.get("/history")
async def get_history(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    u = _require_user(request)
    store = HistoryStore(db)
    history = await store.load(user_id=u["id"])
    return JSONResponse({"history": history})


@router.put("/history")
async def put_history(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: Any = Body(...),
) -> JSONResponse:
    u = _require_user(request)
    store = HistoryStore(db)

    history = payload.get("history") if isinstance(payload, dict) else payload
    await store.save(user_id=u["id"], history=history)
    return JSONResponse({"ok": True})
