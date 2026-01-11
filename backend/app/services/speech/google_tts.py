# app/services/speech/google_tts.py

from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool
from google.cloud import texttospeech
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import service_account

from app.core import settings
from app.core.settings import GOOGLE_TTS_MAX_CHARS

# Map kiosk language codes to Google TTS language codes
LANG_MAP = {
    "en": "en-US",
    "es": "es-ES",
    # TTS supports ar-XA well; if unavailable, voice picker will fallback by base lang.
    "ar": "ar-XA",
    "hy": "hy-AM",
}

_ENCODING_MAP = {
    "mp3": texttospeech.AudioEncoding.MP3,
    "ogg_opus": texttospeech.AudioEncoding.OGG_OPUS,
    "linear16": texttospeech.AudioEncoding.LINEAR16,
    "wav": texttospeech.AudioEncoding.LINEAR16,  # alias
    "ogg": texttospeech.AudioEncoding.OGG_OPUS,  # alias
}


class GoogleTTS:
    def __init__(self) -> None:
        self.client = self._make_client()

        self._voices_loaded = False
        self._voices_lock = threading.Lock()
        self._voices_by_lang: Dict[str, List[texttospeech.Voice]] = {}

    def _make_client(self) -> texttospeech.TextToSpeechClient:
        """
        Supports:
          1) GOOGLE_APPLICATION_CREDENTIALS_JSON (Fly secret style)
          2) Explicit GOOGLE_APPLICATION_CREDENTIALS path (local Windows style)
          3) Default ADC (gcloud auth, etc)
        """
        raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
        if raw:
            try:
                info = json.loads(raw)
                creds = service_account.Credentials.from_service_account_info(info)
                return texttospeech.TextToSpeechClient(credentials=creds)
            except Exception as e:
                raise RuntimeError(f"Invalid GOOGLE_APPLICATION_CREDENTIALS_JSON: {e}") from e

        p = (getattr(settings, "GOOGLE_APPLICATION_CREDENTIALS", "") or "").strip()
        if p:
            try:
                creds = service_account.Credentials.from_service_account_file(p)
                return texttospeech.TextToSpeechClient(credentials=creds)
            except Exception as e:
                raise RuntimeError(f"Failed to load GOOGLE_APPLICATION_CREDENTIALS file: {e}") from e

        return texttospeech.TextToSpeechClient()

    def _ensure_voices(self) -> None:
        if self._voices_loaded:
            return
        with self._voices_lock:
            if self._voices_loaded:
                return
            try:
                resp = self.client.list_voices()
                voices = resp.voices or []
                for v in voices:
                    for lc in (v.language_codes or []):
                        k = (lc or "").strip().lower()
                        if not k:
                            continue
                        self._voices_by_lang.setdefault(k, []).append(v)
                self._voices_loaded = True
            except Exception:
                self._voices_loaded = True
                self._voices_by_lang = {}

    def _pick_voice(
        self, locale: str, voice_name: Optional[str]
    ) -> Tuple[texttospeech.VoiceSelectionParams, str]:
        loc = (locale or "").strip()
        if not loc:
            raise ValueError("lang is required")

        if voice_name:
            vp = texttospeech.VoiceSelectionParams(
                language_code=loc,
                name=voice_name,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
            )
            return vp, loc

        self._ensure_voices()

        if not self._voices_by_lang:
            vp = texttospeech.VoiceSelectionParams(
                language_code=loc,
                ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
            )
            return vp, loc

        loc_l = loc.lower()

        vs = self._voices_by_lang.get(loc_l) or []

        chosen_lang = loc
        base = loc_l.split("-", 1)[0] if "-" in loc_l else loc_l

        if not vs:
            for k, arr in self._voices_by_lang.items():
                if k == base or k.startswith(base + "-"):
                    vs = arr
                    chosen_lang = k
                    break

        if not vs:
            raise ValueError(f"TTS not supported for language '{locale}'")

        v0 = vs[0]

        lang_code = chosen_lang
        if v0.language_codes:
            declared = [x.lower() for x in v0.language_codes]
            if lang_code.lower() not in declared:
                lang_code = v0.language_codes[0]

        vp = texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            name=v0.name,
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
        )
        return vp, lang_code

    async def speak(
        self,
        text: str,
        lang: str,
        *,
        encoding: str = "mp3",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
        voice_name: str | None = None,
        sample_rate_hz: int | None = None,
    ) -> bytes:
        t = (text or "").strip()
        if not t:
            raise ValueError("Text is required")

        if GOOGLE_TTS_MAX_CHARS and len(t) > GOOGLE_TTS_MAX_CHARS:
            raise ValueError(f"Text too long (max {GOOGLE_TTS_MAX_CHARS} characters)")

        code = (lang or "").strip()
        if not code:
            raise ValueError("lang is required")

        locale = LANG_MAP.get(code.lower(), code)

        enc_key = (encoding or "mp3").lower().strip()
        audio_encoding = _ENCODING_MAP.get(enc_key)
        if not audio_encoding:
            raise ValueError("encoding must be one of: mp3, ogg_opus, ogg, linear16, wav")

        try:
            rate = float(speaking_rate)
        except Exception:
            rate = 1.0
        try:
            pit = float(pitch)
        except Exception:
            pit = 0.0

        if rate <= 0:
            rate = 1.0
        pit = max(-20.0, min(20.0, pit))

        synthesis_input = texttospeech.SynthesisInput(text=t)

        voice, _chosen_lang = self._pick_voice(locale, voice_name)

        audio_config_kwargs = dict(
            audio_encoding=audio_encoding,
            speaking_rate=rate,
            pitch=pit,
        )

        if sample_rate_hz is not None:
            try:
                sr = int(sample_rate_hz)
                if 8000 <= sr <= 48000:
                    audio_config_kwargs["sample_rate_hertz"] = sr
            except Exception:
                pass

        audio_config = texttospeech.AudioConfig(**audio_config_kwargs)

        def _call():
            return self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

        try:
            resp = await run_in_threadpool(_call)
        except DefaultCredentialsError as e:
            raise RuntimeError(
                "Google credentials not found. Set GOOGLE_APPLICATION_CREDENTIALS (file path) "
                "or GOOGLE_APPLICATION_CREDENTIALS_JSON (JSON secret)."
            ) from e
        except GoogleAPIError as e:
            raise RuntimeError(f"Google TTS error: {e}") from e

        if not resp.audio_content:
            raise RuntimeError("No audio returned from Google TTS")

        return resp.audio_content
