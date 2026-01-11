# app/services/speech/assemblyai.py

from __future__ import annotations

from app.services.speech.stt_base import STTProvider, STTResult


class AssemblyAISTT(STTProvider):
    """
    Optional provider placeholder.
    Keep this file so switching providers later is clean.
    """
    name = "assemblyai"

    async def transcribe(
        self, *, audio_bytes: bytes, lang: str, content_type: str = "audio/wav"
    ) -> STTResult:
        raise RuntimeError("AssemblyAI STT not configured in this build.")
