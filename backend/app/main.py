# app/main.py  (UPDATED — keep your version, just ensure auth is always mounted)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from starlette.middleware.sessions import SessionMiddleware
except Exception:
    SessionMiddleware = None  # type: ignore

from app.core.settings import (
    ALLOWED_ORIGINS,
    ALLOWED_ORIGIN_REGEX,
    CORS_EXPOSE_HEADERS,
    CORS_ALLOW_CREDENTIALS,
    SESSION_SECRET,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    SESSION_COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_DOMAIN,
    SESSION_COOKIE_PATH,
)

from app.routes.health import router as health_router
from app.routes.translate import router as translate_router
from app.routes.tts import router as tts_router
from app.routes.stt import router as stt_router

app = FastAPI(title="TalkBridge API")

if SessionMiddleware and SESSION_SECRET:
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET,
        session_cookie=SESSION_COOKIE_NAME,
        max_age=SESSION_MAX_AGE_SECONDS,
        same_site=SESSION_COOKIE_SAMESITE,
        https_only=SESSION_COOKIE_SECURE,
        domain=SESSION_COOKIE_DOMAIN,
        path=SESSION_COOKIE_PATH,
    )

raw = (ALLOWED_ORIGINS or "*").strip()

cors_kwargs = dict(
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=CORS_EXPOSE_HEADERS,
)

if raw == "" or raw == "*":
    cors_kwargs.update(
        allow_origins=["*"],
        allow_credentials=False,
    )
else:
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if any(o == "*" for o in origins):
        cors_kwargs.update(
            allow_origins=["*"],
            allow_credentials=False,
        )
    else:
        allow_credentials = True if CORS_ALLOW_CREDENTIALS is None else bool(CORS_ALLOW_CREDENTIALS)
        cors_kwargs.update(
            allow_origins=origins,
            allow_credentials=allow_credentials,
        )
        if ALLOWED_ORIGIN_REGEX:
            cors_kwargs["allow_origin_regex"] = ALLOWED_ORIGIN_REGEX

app.add_middleware(CORSMiddleware, **cors_kwargs)

app.include_router(health_router, prefix="/api")
app.include_router(translate_router, prefix="/api")
app.include_router(tts_router, prefix="/api")
app.include_router(stt_router, prefix="/api")

# IMPORTANT: mount auth router (so /api/auth/login and /api/auth/me don’t 404)
from app.routes.auth import router as auth_router  # noqa: WPS433
app.include_router(auth_router, prefix="/api")
