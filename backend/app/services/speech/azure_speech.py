# app/services/speech/azure_speech.py

from __future__ import annotations

from app.services.speech.stt_base import STTProvider, STTResult


class AzureSpeechSTT(STTProvider):
    """
    Optional provider placeholder.
    Keep this file so switching providers later is clean.
    """
    name = "azure"

    async def transcribe(
        self, *, audio_bytes: bytes, lang: str, content_type: str = "audio/wav"
    ) -> STTResult:
        raise RuntimeError("Azure STT not configured in this build.")
