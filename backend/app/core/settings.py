# app/core/settings.py

import os
from pathlib import Path
from typing import Optional

# Load .env if available (safe even if python-dotenv isn't installed)
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../backend
KEYS_DIR = BACKEND_ROOT / "keys"

if load_dotenv:
    # backend/.env (works no matter where uvicorn is launched from)
    env_path = BACKEND_ROOT / ".env"
    load_dotenv(env_path)


def _norm_path(p: str) -> str:
    p = (p or "").strip()
    if not p:
        return ""
    p = os.path.expandvars(os.path.expanduser(p))
    try:
        pp = Path(p)
        if not pp.is_absolute():
            pp = (BACKEND_ROOT / pp).resolve()
        return str(pp)
    except Exception:
        return p


def _fallback_key(*names: str) -> str:
    if not KEYS_DIR.exists():
        return ""
    for n in names:
        fp = KEYS_DIR / n
        if fp.exists():
            return str(fp)
    return ""


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "")
    if v is None or str(v).strip() == "":
        return bool(default)
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except Exception:
        return float(default)


def _env_csv(name: str) -> list[str]:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _strip_slash(url: str) -> str:
    return (url or "").strip().rstrip("/")


# -----------------------------
# App / Environment
# -----------------------------
ENV = (os.getenv("ENV", os.getenv("APP_ENV", "dev")) or "dev").strip().lower()
IS_PROD = ENV in ("prod", "production")
BASE_URL = _strip_slash(os.getenv("BASE_URL", ""))  # e.g. https://<BACKEND_PUBLIC_URL>

# Frontend URL is used for redirects after login (optional but recommended)
FRONTEND_URL = _strip_slash(os.getenv("FRONTEND_URL", os.getenv("FRONTEND_PUBLIC_URL", "")))

# -----------------------------
# Translator (Microsoft)
# -----------------------------
MICROSOFT_TRANSLATOR_KEY = os.getenv("MICROSOFT_TRANSLATOR_KEY", "").strip()
MICROSOFT_TRANSLATOR_REGION = os.getenv("MICROSOFT_TRANSLATOR_REGION", "").strip()
MICROSOFT_TRANSLATOR_ENDPOINT = os.getenv(
    "MICROSOFT_TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com/",
).strip()

# -----------------------------
# CORS
# -----------------------------
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").strip()
ALLOWED_ORIGIN_REGEX = (os.getenv("ALLOWED_ORIGIN_REGEX", "") or "").strip() or None
CORS_EXPOSE_HEADERS = _env_csv("CORS_EXPOSE_HEADERS") or [
    "X-Audio-Content-Type",
    "Content-Disposition",
]
# Optional override (useful when you KNOW you want cookies)
CORS_ALLOW_CREDENTIALS: Optional[bool]
_raw_cac = (os.getenv("CORS_ALLOW_CREDENTIALS", "") or "").strip()
if _raw_cac == "":
    CORS_ALLOW_CREDENTIALS = None
else:
    CORS_ALLOW_CREDENTIALS = _env_bool("CORS_ALLOW_CREDENTIALS", True)

# -----------------------------
# Google Cloud TTS / STT (service account JSON path)
# -----------------------------
GOOGLE_APPLICATION_CREDENTIALS = _norm_path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""))

if GOOGLE_APPLICATION_CREDENTIALS and not Path(GOOGLE_APPLICATION_CREDENTIALS).exists():
    GOOGLE_APPLICATION_CREDENTIALS = _fallback_key("tts.json", "google.json", "stt.json")

if not GOOGLE_APPLICATION_CREDENTIALS:
    GOOGLE_APPLICATION_CREDENTIALS = _fallback_key("tts.json", "google.json")

# Ensure google libraries see the final resolved path (helps on Windows + when using load_dotenv)
try:
    if GOOGLE_APPLICATION_CREDENTIALS and Path(GOOGLE_APPLICATION_CREDENTIALS).exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
except Exception:
    pass

# (Optional) Separate creds for STT. If empty, we fallback to GOOGLE_APPLICATION_CREDENTIALS.
GOOGLE_STT_CREDENTIALS = _norm_path(os.getenv("GOOGLE_STT_CREDENTIALS", ""))

if GOOGLE_STT_CREDENTIALS and not Path(GOOGLE_STT_CREDENTIALS).exists():
    GOOGLE_STT_CREDENTIALS = _fallback_key("stt.json", "google.json")

if not GOOGLE_STT_CREDENTIALS:
    GOOGLE_STT_CREDENTIALS = _fallback_key("stt.json")

GOOGLE_TTS_MAX_CHARS = _env_int("GOOGLE_TTS_MAX_CHARS", 5000)

# STT settings
GOOGLE_STT_DEFAULT_SAMPLE_RATE = _env_int("GOOGLE_STT_DEFAULT_SAMPLE_RATE", 16000)
GOOGLE_STT_ENABLE_PUNCTUATION = _env_bool("GOOGLE_STT_ENABLE_PUNCTUATION", True)

# Optional accuracy knobs
GOOGLE_STT_MODEL = (os.getenv("GOOGLE_STT_MODEL", "latest_short") or "").strip()
GOOGLE_STT_USE_ENHANCED = _env_bool("GOOGLE_STT_USE_ENHANCED", False)

# Phrase hints: comma-separated phrases (optional)
GOOGLE_STT_PHRASE_HINTS = _env_csv("GOOGLE_STT_PHRASE_HINTS")
GOOGLE_STT_PHRASE_BOOST = _env_float("GOOGLE_STT_PHRASE_BOOST", 12.0)

# Alternative languages (optional): comma-separated locales (e.g., "en-US,es-ES")
GOOGLE_STT_ALTERNATIVE_LANGUAGE_CODES = _env_csv("GOOGLE_STT_ALTERNATIVE_LANGUAGE_CODES")

# Max bytes accepted by /api/stt
GOOGLE_STT_MAX_AUDIO_BYTES = _env_int("GOOGLE_STT_MAX_AUDIO_BYTES", 2000000)

# -----------------------------
# Auth (Google OAuth) + Sessions (cookie-based)
# -----------------------------
# Accept either naming convention (so Fly secrets can be whichever you already used)
GOOGLE_OAUTH_CLIENT_ID = (
    os.getenv("GOOGLE_OAUTH_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", "")) or ""
).strip()
GOOGLE_OAUTH_CLIENT_SECRET = (
    os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", "")) or ""
).strip()

GOOGLE_OAUTH_SCOPES = _env_csv("GOOGLE_OAUTH_SCOPES") or ["openid", "email", "profile"]

# Redirect URI required by Google Console:
#   https://<BACKEND_PUBLIC_URL>/api/auth/callback
GOOGLE_OAUTH_REDIRECT_PATH = (os.getenv("GOOGLE_OAUTH_REDIRECT_PATH", "/api/auth/callback") or "").strip()
GOOGLE_OAUTH_REDIRECT_URI = ""
if BASE_URL and GOOGLE_OAUTH_REDIRECT_PATH:
    GOOGLE_OAUTH_REDIRECT_URI = f"{BASE_URL}{GOOGLE_OAUTH_REDIRECT_PATH}"

# Session config (HttpOnly cookie)
SESSION_SECRET = (os.getenv("SESSION_SECRET", os.getenv("SESSION_KEY", "")) or "").strip()
SESSION_COOKIE_NAME = (os.getenv("SESSION_COOKIE_NAME", "tb_session") or "tb_session").strip()
SESSION_MAX_AGE_SECONDS = _env_int("SESSION_MAX_AGE_SECONDS", 60 * 60 * 24 * 7)  # 7 days

# For cross-site cookies (frontend on different domain), you MUST use:
#   SameSite=None AND Secure=true (https).
SESSION_COOKIE_SECURE = _env_bool(
    "SESSION_COOKIE_SECURE",
    True if (BASE_URL.lower().startswith("https://") if BASE_URL else IS_PROD) else False,
)

# default: "none" when secure (typical prod cross-site), else "lax" for local dev
SESSION_COOKIE_SAMESITE = (os.getenv("SESSION_COOKIE_SAMESITE", "") or "").strip().lower()
if SESSION_COOKIE_SAMESITE not in ("lax", "strict", "none"):
    SESSION_COOKIE_SAMESITE = "none" if SESSION_COOKIE_SECURE else "lax"

SESSION_COOKIE_DOMAIN = (os.getenv("SESSION_COOKIE_DOMAIN", "") or "").strip() or None
SESSION_COOKIE_PATH = (os.getenv("SESSION_COOKIE_PATH", "/") or "/").strip()
