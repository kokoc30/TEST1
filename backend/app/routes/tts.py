# app/routes/tts.py

from __future__ import annotations

import struct
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services.speech.google_tts import GoogleTTS
from app.core.settings import GOOGLE_TTS_MAX_CHARS

router = APIRouter()

_tts: GoogleTTS | None = None


def get_tts() -> GoogleTTS:
    global _tts
    if _tts is None:
        _tts = GoogleTTS()
    return _tts


def pcm16_to_wav(pcm: bytes, sample_rate_hz: int = 24000, channels: int = 1) -> bytes:
    if not pcm:
        return b""

    bits_per_sample = 16
    byte_rate = sample_rate_hz * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(pcm)
    riff_size = 36 + data_size

    header = b"".join(
        [
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack("<H", 1),
            struct.pack("<H", channels),
            struct.pack("<I", sample_rate_hz),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits_per_sample),
            b"data",
            struct.pack("<I", data_size),
        ]
    )
    return header + pcm


class TTSIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=(GOOGLE_TTS_MAX_CHARS or 5000))
    lang: str = Field(..., min_length=2, max_length=20)  # en, en-US, etc
    encoding: str = Field(default="mp3")  # mp3 | ogg_opus | ogg | wav | linear16
    speaking_rate: float = Field(default=1.0, ge=0.25, le=4.0)
    pitch: float = Field(default=0.0, ge=-20.0, le=20.0)
    voice_name: str | None = Field(default=None)


@router.post("/tts")
async def tts(payload: TTSIn):
    try:
        enc = (payload.encoding or "mp3").lower().strip()

        # normalize aliases
        if enc == "ogg":
            enc = "ogg_opus"

        if enc in ("wav", "linear16"):
            sample_rate = 24000
            pcm = await get_tts().speak(
                payload.text,
                payload.lang,
                encoding="linear16",
                speaking_rate=payload.speaking_rate,
                pitch=payload.pitch,
                voice_name=payload.voice_name,
                sample_rate_hz=sample_rate,
            )
            wav = pcm16_to_wav(pcm, sample_rate_hz=sample_rate, channels=1)
            media_type = "audio/wav"
            return Response(
                content=wav,
                media_type=media_type,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": 'inline; filename="tts.wav"',
                    "X-Audio-Content-Type": media_type,
                },
            )

        audio = await get_tts().speak(
            payload.text,
            payload.lang,
            encoding=enc,
            speaking_rate=payload.speaking_rate,
            pitch=payload.pitch,
            voice_name=payload.voice_name,
        )

        if enc == "mp3":
            media_type = "audio/mpeg"
            filename = "tts.mp3"
        elif enc == "ogg_opus":
            media_type = "audio/ogg; codecs=opus"
            filename = "tts.ogg"
        else:
            media_type = "application/octet-stream"
            filename = "tts.bin"

        return Response(
            content=audio,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'inline; filename="{filename}"',
                "X-Audio-Content-Type": media_type,
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")
