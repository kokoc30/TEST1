# app/routes/stt.py

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core import settings
from app.services.speech.google_stt import GoogleSTT
from app.services.speech.stt_base import clamp_str

router = APIRouter()

_stt: GoogleSTT | None = None


def get_stt() -> GoogleSTT:
    global _stt
    if _stt is None:
        _stt = GoogleSTT()
    return _stt


class STTOut(BaseModel):
    text: str
    confidence: float | None = None
    language: str | None = None
    provider: str = "google"


@router.post("/stt", response_model=STTOut)
async def stt(
    audio: UploadFile = File(...),
    lang: str = Form("en"),
):
    try:
        lang = clamp_str(lang, default="en", max_len=32)

        b = await audio.read()
        if not b:
            raise HTTPException(status_code=400, detail="Empty audio upload")

        max_bytes = int(settings.GOOGLE_STT_MAX_AUDIO_BYTES)
        if max_bytes > 0 and len(b) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio too large ({len(b)} bytes). Max is {max_bytes}.",
            )

        res = await get_stt().transcribe(
            audio_bytes=b,
            lang=lang,
            content_type=(audio.content_type or "audio/wav"),
        )

        return STTOut(
            text=res.text,
            confidence=res.confidence,
            language=res.language,
            provider=get_stt().name,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STT failed: {e}")
