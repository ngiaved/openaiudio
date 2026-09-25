"""Utilidades de audio: PCM16 <-> float32, resample y energía. Sin dependencias pesadas."""

from __future__ import annotations

import numpy as np

from app.config import AUDIO_RATE


def pcm16_to_float32(data: bytes) -> np.ndarray:
    """bytes PCM16 little-endian mono -> float32 en [-1, 1]."""
    if not data or len(data) % 2:
        return np.zeros(0, dtype=np.float32)
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    return np.clip(samples, -1.0, 1.0)


def float32_to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def energy_db(samples: np.ndarray) -> float:
    """Energía RMS en dBFS (-inf si silencio)."""
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(samples))))
    if rms < 1e-8:
        return float("-inf")
    return 20.0 * np.log10(rms)


def resample_pcm16_to_rate(data: bytes, src_rate: int) -> bytes:
    """Resample lineal de PCM16 mono a AUDIO_RATE (16 kHz). Corrige cualquier tasa del origen."""
    if src_rate == AUDIO_RATE:
        return data
    samples = np.frombuffer(data, dtype="<i2")
    if samples.size == 0:
        return b""
    n = max(1, round(samples.size * AUDIO_RATE / float(src_rate)))
    x = np.linspace(0.0, 1.0, n)
    src = np.linspace(0.0, 1.0, samples.size)
    out = np.interp(x, src, samples).astype("<i2")
    return out.tobytes()


class SilentAudio:
    """Generador de chunks de silencio (para tests y calibración)."""

    def __init__(self, chunk_size: int = 1600) -> None:
        self.chunk = np.zeros(chunk_size, dtype="<i2").tobytes()