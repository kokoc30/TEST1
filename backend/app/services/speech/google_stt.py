# app/services/speech/google_stt.py

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from starlette.concurrency import run_in_threadpool
from google.cloud import speech_v1 as speech
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import service_account

from app.core import settings
from app.services.speech.stt_base import (
    STTProvider,
    STTResult,
    clamp_str,
    extract_wav_pcm16,
)

_LANG_MAP = {
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    # IMPORTANT: ar-XA is a TTS locale; STT works better with real locales like ar-SA/ar-EG
    "ar": "ar-SA",
    "hy": "hy-AM",
    "ru": "ru-RU",
    "de": "de-DE",
    "it": "it-IT",
    "pt": "pt-BR",
    "tr": "tr-TR",
}


def normalize_lang(lang: str) -> str:
    x = clamp_str(lang, default="en", max_len=32).strip()
    if not x:
        return "en-US"

    x_low = x.lower()

    # If user passes "ar-XA" (from old code), fix it
    if x_low == "ar-xa":
        return "ar-SA"

    # If already looks like a locale, keep it
    if "-" in x_low:
        return x

    return _LANG_MAP.get(x_low, x)


def _resolve_creds_path() -> str:
    candidates = []
    for p in [
        getattr(settings, "GOOGLE_STT_CREDENTIALS", ""),
        getattr(settings, "GOOGLE_APPLICATION_CREDENTIALS", ""),
    ]:
        p = (p or "").strip()
        if p:
            candidates.append(p)

    for p in candidates:
        try:
            if Path(p).exists():
                return p
        except Exception:
            pass

    try:
        backend_root = Path(__file__).resolve().parents[4]  # backend/
        keys_dir = backend_root / "keys"
        if keys_dir.exists():
            for name in ("stt.json", "google.json", "tts.json"):
                fp = keys_dir / name
                if fp.exists():
                    return str(fp)
    except Exception:
        pass

    return ""


class GoogleSTT(STTProvider):
    name = "google"

    def __init__(self) -> None:
        # 1) JSON secret style (optional)
        raw_json = (
            os.getenv("GOOGLE_STT_CREDENTIALS_JSON", "").strip()
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
        )
        if raw_json:
            try:
                info = json.loads(raw_json)
                creds = service_account.Credentials.from_service_account_info(info)
                self.client = speech.SpeechClient(credentials=creds)
                return
            except Exception as e:
                raise RuntimeError(f"Invalid GOOGLE_STT_CREDENTIALS_JSON: {e}") from e

        # 2) File path style
        creds_path = _resolve_creds_path()
        if creds_path:
            try:
                creds = service_account.Credentials.from_service_account_file(creds_path)
                self.client = speech.SpeechClient(credentials=creds)
                return
            except Exception as e:
                raise RuntimeError(f"Failed to load STT credentials file: {e}") from e

        # 3) ADC
        self.client = speech.SpeechClient()

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        lang: str,
        content_type: str = "audio/wav",
    ) -> STTResult:
        # Expect WAV PCM16 from frontend
        pcm, sample_rate_hz, channels = extract_wav_pcm16(audio_bytes)

        language_code = normalize_lang(lang)

        cfg_kwargs = dict(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=int(sample_rate_hz),
            language_code=language_code,
            audio_channel_count=int(channels),
            enable_automatic_punctuation=bool(getattr(settings, "GOOGLE_STT_ENABLE_PUNCTUATION", True)),
        )

        model = (getattr(settings, "GOOGLE_STT_MODEL", "") or "").strip()
        if model:
            cfg_kwargs["model"] = model

        if bool(getattr(settings, "GOOGLE_STT_USE_ENHANCED", False)):
            cfg_kwargs["use_enhanced"] = True

        alt = getattr(settings, "GOOGLE_STT_ALTERNATIVE_LANGUAGE_CODES", None) or []
        alt = [x.strip() for x in alt if isinstance(x, str) and x.strip()]
        # avoid duplicating primary language
        alt = [x for x in alt if x.lower() != language_code.lower()]
        if alt:
            cfg_kwargs["alternative_language_codes"] = alt

        hints = getattr(settings, "GOOGLE_STT_PHRASE_HINTS", None) or []
        hints = [x.strip() for x in hints if isinstance(x, str) and x.strip()]
        if hints:
            boost = float(getattr(settings, "GOOGLE_STT_PHRASE_BOOST", 12.0) or 12.0)
            cfg_kwargs["speech_contexts"] = [
                speech.SpeechContext(phrases=hints, boost=boost)
            ]

        config = speech.RecognitionConfig(**cfg_kwargs)
        audio = speech.RecognitionAudio(content=pcm)

        def _call():
            return self.client.recognize(config=config, audio=audio)

        try:
            resp = await run_in_threadpool(_call)
        except DefaultCredentialsError as e:
            raise RuntimeError(
                "Google STT credentials not found. Set GOOGLE_STT_CREDENTIALS / GOOGLE_APPLICATION_CREDENTIALS "
                "or provide GOOGLE_STT_CREDENTIALS_JSON."
            ) from e
        except GoogleAPIError as e:
            raise RuntimeError(f"Google STT error: {e}") from e

        parts = []
        conf: Optional[float] = None

        for r in (resp.results or []):
            if not r.alternatives:
                continue
            alt0 = r.alternatives[0]
            t = (alt0.transcript or "").strip()
            if t:
                parts.append(t)
            if conf is None and getattr(alt0, "confidence", None):
                try:
                    conf = float(alt0.confidence)
                except Exception:
                    pass

        text = " ".join(parts).strip()
        if not text:
            raise ValueError("No speech detected")

        return STTResult(
            text=text,
            confidence=conf,
            language=language_code,
            raw={"results": len(resp.results or [])},
        )
