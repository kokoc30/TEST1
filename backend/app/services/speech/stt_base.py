# app/services/speech/stt_base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class STTResult:
    text: str
    confidence: Optional[float] = None
    language: Optional[str] = None
    raw: Optional[dict] = None


class STTProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        lang: str,
        content_type: str = "audio/wav",
    ) -> STTResult:
        raise NotImplementedError


def clamp_str(s: str, default: str = "", max_len: int = 64) -> str:
    x = (s or "").strip()
    if not x:
        return default
    return x[:max_len]


def is_wav(audio_bytes: bytes) -> bool:
    return (
        isinstance(audio_bytes, (bytes, bytearray))
        and len(audio_bytes) >= 12
        and audio_bytes[0:4] == b"RIFF"
        and audio_bytes[8:12] == b"WAVE"
    )


def _read_u16_le(b: bytes, off: int) -> int:
    return int.from_bytes(b[off : off + 2], "little", signed=False)


def _read_u32_le(b: bytes, off: int) -> int:
    return int.from_bytes(b[off : off + 4], "little", signed=False)


def parse_wav_info(wav_bytes: bytes) -> Tuple[int, int]:
    """
    Minimal WAV parser to extract (sample_rate_hz, channels).
    Raises ValueError if malformed/unsupported.
    """
    sr, ch, _, _, _ = parse_wav_details(wav_bytes)
    return sr, ch


def parse_wav_details(wav_bytes: bytes) -> Tuple[int, int, int, int, int]:
    """
    Returns: (sample_rate_hz, channels, bits_per_sample, audio_format, data_offset)
    - audio_format: PCM=1, IEEE float=3, extensible=65534
    - data_offset: where PCM data starts (points to 'data' payload)
    """
    if not is_wav(wav_bytes):
        raise ValueError("Not a WAV file")

    i = 12  # after RIFF header
    fmt_found = False
    data_found = False

    sample_rate = 0
    channels = 0
    audio_format = 0
    bits_per_sample = 0
    data_offset = -1
    data_size = 0

    while i + 8 <= len(wav_bytes):
        chunk_id = wav_bytes[i : i + 4]
        chunk_size = _read_u32_le(wav_bytes, i + 4)
        i += 8

        if i + chunk_size > len(wav_bytes):
            break

        if chunk_id == b"fmt ":
            if chunk_size < 16:
                raise ValueError("Invalid WAV fmt chunk")
            audio_format = _read_u16_le(wav_bytes, i + 0)
            channels = _read_u16_le(wav_bytes, i + 2)
            sample_rate = _read_u32_le(wav_bytes, i + 4)
            bits_per_sample = _read_u16_le(wav_bytes, i + 14)
            fmt_found = True

        elif chunk_id == b"data":
            data_offset = i
            data_size = chunk_size
            data_found = True

        # chunks are word-aligned
        i += chunk_size + (chunk_size % 2)

        if fmt_found and data_found:
            break

    if not fmt_found or not data_found:
        raise ValueError("WAV fmt/data chunk not found")

    if audio_format not in (1, 3, 65534):
        raise ValueError(f"Unsupported WAV audio format: {audio_format}")

    if sample_rate <= 0 or sample_rate > 192000:
        raise ValueError(f"Unreasonable WAV sample rate: {sample_rate}")

    if channels <= 0 or channels > 2:
        raise ValueError(f"Unsupported channel count: {channels}")

    if bits_per_sample not in (16,):
        raise ValueError(f"Unsupported bits_per_sample: {bits_per_sample} (expected 16)")

    if data_offset < 0 or data_offset + data_size > len(wav_bytes):
        raise ValueError("Invalid WAV data chunk bounds")

    return sample_rate, channels, bits_per_sample, audio_format, data_offset


def extract_wav_pcm16(wav_bytes: bytes) -> Tuple[bytes, int, int]:
    """
    Extract raw PCM bytes from a WAV (expects PCM16).
    Returns: (pcm_bytes, sample_rate_hz, channels)
    """
    sr, ch, bps, fmt, data_off = parse_wav_details(wav_bytes)

    # only allow PCM (1) or extensible (65534) when still PCM16
    if fmt not in (1, 65534):
        raise ValueError(f"WAV must be PCM16 (audio_format={fmt})")

    if bps != 16:
        raise ValueError("WAV must be 16-bit PCM")

    # data chunk size is not returned from parse_wav_details; recompute safely
    # find the 'data' chunk again to get size (cheap, avoids threading state)
    i = 12
    data_size = None
    while i + 8 <= len(wav_bytes):
        cid = wav_bytes[i : i + 4]
        csz = _read_u32_le(wav_bytes, i + 4)
        i += 8
        if i + csz > len(wav_bytes):
            break
        if cid == b"data":
            data_size = csz
            break
        i += csz + (csz % 2)

    if data_size is None:
        raise ValueError("WAV data chunk not found")

    pcm = wav_bytes[data_off : data_off + data_size]
    if not pcm:
        raise ValueError("Empty WAV audio data")

    return pcm, sr, ch
