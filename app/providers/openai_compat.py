"""OpenAI-compatible providers: chat-completions streaming translation, Whisper
`/audio/transcriptions` STT and inline-audio windowed STT.

Covers every vendor whose API is OpenAI-shaped (xAI, OpenAI, Groq, Mistral,
DeepSeek, Together, OpenRouter, Azure OpenAI, custom) without extra SDKs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import Callable

import httpx
import numpy as np

from app.providers.base import TranscriptProvider

log = logging.getLogger("openaiudio.openai_compat")

_QUOTA_RE = re.compile(r"retry[- ]?after\s*:?\s*(?:(\d+)\s*s)?|(\d{3})", re.IGNORECASE)


def quota_delay(exc: Exception, headers: dict | None = None) -> float | None:
    """Seconds to wait after a 429/503 before retrying (honors Retry-After)."""
    if headers:
        ra = headers.get("retry-after", headers.get("Retry-After", ""))
        if ra and str(ra).strip().isdigit():
            return max(0.0, float(ra))
    msg = str(exc)
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status = resp.status_code
            retry = resp.headers.get("retry-after")
            if retry and str(retry).isdigit():
                return max(0.0, float(retry))
            if status in (429, 503):
                return 6.0 if status == 503 else 10.0
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"retry[- ]?after:\s*(\d+)", msg, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    if "429" in msg:
        return 10.0
    if "503" in msg:
        return 6.0
    return None


def build_stt_prompt(ctx) -> str:
    from app.providers.gemini import build_prompt

    return build_prompt(ctx)


class _OpenAIClient:
    """Trivial helper for vendor base URL + default headers."""

    def __init__(self, vendor) -> None:
        self.vendor = vendor
        self.azure_endpoint = (vendor.extra or {}).get("azure_endpoint", "")

    @property
    def is_azure(self) -> bool:
        return self.vendor.protocol == "azure"

    def headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.vendor.api_key}", "Content-Type": "application/json"}
        if self.vendor.id == "openrouter":
            h["HTTP-Referer"] = "https://openaiudio.local"
            h["X-Title"] = "OpenAIudio"
        return h

    def chat_url(self, model: str) -> str:
        if self.is_azure:
            base = self.azure_endpoint.rstrip("/")
            deployment = (model.split("/")[-1] if model.find("/") >= 0 else model)
            return f"{base}/chat/completions?api-version={self.vendor.extra.get('api_version', '2024-06-01')}"
        return f"{self.vendor.base_url.rstrip('/')}/chat/completions"

    def transcriptions_url(self, model: str) -> str:
        if self.is_azure:
            base = self.azure_endpoint.rstrip("/")
            return f"{base}/audio/transcriptions?api-version={self.vendor.extra.get('api_version', '2024-06-01')}"
        return f"{self.vendor.base_url.rstrip('/')}/audio/transcriptions"


def _emit_stream_once(acc: list[str], last: list[str], emit: Callable[[str], None], step: int = 3) -> None:
    text = "".join(acc)
    if len(text) - len("".join(last)) >= step:
        emit(text)
        last[:] = [text]


class OpenAITextTranslateProvider(TranscriptProvider):
    """Traducción por texto vía chat completions (streaming, OpenAI-compatible)."""

    CONTEXT_LEN = 2

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._task: asyncio.Task | None = None
        self._context: list[str] = []
        self._request_timeout = ctx.settings.stt_timeout_sec
        self._quota_until = 0.0
        self._error_broadcasted = False

    @property
    def _model(self) -> str:
        return (self.ctx.model_override or self.ctx.vendor.translate_model) if self.ctx.vendor else ""

    async def start(self) -> None:
        self._state("warming")
        if self.ctx.vendor is None or not self.ctx.vendor.api_key or not self._model:
            self._state("error")
            self.ctx.on_error(
                f"vendor {self.ctx.vendor.id if self.ctx.vendor else '?'}: falta api_key o modelo de traducción"
            )
            return
        self._state("live")
        self.started_at = time.time()
        self._task = asyncio.create_task(self._translate_loop())

    async def on_text(self, text: str) -> None:
        norm = " ".join(text.split())
        if not norm:
            return
        try:
            self._q.put_nowait(norm)
        except asyncio.QueueFull:
            return

    async def _translate_loop(self) -> None:
        client = _OpenAIClient(self.ctx.vendor)
        system = build_stt_prompt(self.ctx)
        while not self._stopping:
            if self._quota_until and time.time() < self._quota_until:
                await asyncio.sleep(min(self._quota_until - time.time(), 15.0))
                continue
            text = await self._q.get()
            candidate = (self._context + [text])[-self.CONTEXT_LEN :]
            waits = 0
            while True:
                try:
                    await asyncio.wait_for(
                        self._translate_one(client, system, "\n".join(candidate)),
                        timeout=self._request_timeout,
                    )
                    self._context = candidate
                    self._quota_until = 0.0
                    self._error_broadcasted = False
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.errors += 1
                    delay = quota_delay(exc, getattr(getattr(exc, "response", None), "headers", None))
                    if delay is None:
                        if not self._error_broadcasted:
                            self._error_broadcasted = True
                            self.ctx.on_error(f"{self.ctx.vendor.id} texto: {exc}")
                        break
                    self._quota_until = time.time() + min(max(delay, 3.0), 120.0)
                    if not self._error_broadcasted:
                        self._error_broadcasted = True
                        self.ctx.on_error(
                            f"{self.ctx.vendor.id} texto: rate-limit (reintento en ~{int(round(delay))} s)"
                        )
                    waits += 1
                    if waits > 3:
                        break
                    await asyncio.sleep(min(max(delay, 3.0), 120.0))

    async def _translate_one(self, client: _OpenAIClient, system: str, payload: str) -> None:
        url = client.chat_url(self._model)
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": payload},
            ],
            "stream": True,
            "temperature": 0.2,
            "max_tokens": 512,
        }
        acc: list[str] = []
        last: list[str] = []
        async with httpx.AsyncClient(timeout=self._request_timeout) as hx:
            async with hx.stream("POST", url, headers=client.headers(), json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        acc.append(piece)
                        _emit_stream_once(acc, last, lambda t: self._emit("partial", t), step=3)
        full = "".join(acc).strip()
        if full:
            self._emit("final", full)

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()


class _WindowedSttBase(TranscriptProvider):
    """STT por ventanas: acumula PCM16 16 kHz, transcribe cada `stt_step_sec`.

    Subclases implementan `_run_transcribe(wav_pcm: bytes) -> None` (emite
    partials/final). El gate de energía, ticks, timeout y backoff de cuota son
    comunes.
    """

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._window = bytearray()
        self._ticker: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._busy = False
        self._request_timeout = ctx.settings.stt_timeout_sec
        self._quota_until = 0.0
        self._error_broadcasted = False

    @property
    def _model(self) -> str:
        return (self.ctx.model_override or self.ctx.vendor.stt_model) if self.ctx.vendor else ""

    async def start(self) -> None:
        self._state("warming")
        if self.ctx.vendor is None or not self.ctx.vendor.api_key or not self._model:
            self._state("error")
            self.ctx.on_error(
                f"vendor {self.ctx.vendor.id if self.ctx.vendor else '?'}: falta api_key o modelo de STT"
            )
            return
        self._state("live")
        self.started_at = time.time()
        self._ticker = asyncio.create_task(self._ticker_loop())

    async def on_audio(self, chunk: bytes) -> None:
        await super().on_audio(chunk)
        max_samples = int(self.ctx.settings.stt_window_sec * 16000) * 2
        async with self._lock:
            self._window += chunk
            if len(self._window) > max_samples:
                del self._window[: len(self._window) - max_samples]

    def _energy_db(self, data: bytes) -> float:
        samples = np.frombuffer(bytes(data), dtype="<i2").astype(np.float32) / 32768.0 if data else []
        if len(samples) == 0:
            return -100.0
        rms = float(np.sqrt(np.mean(samples**2)))
        if rms <= 1e-5:
            return -90.0
        return 20.0 * np.log10(max(rms, 1e-8))

    async def _ticker_loop(self) -> None:
        step = max(0.5, float(self.ctx.settings.stt_step_sec))
        while not self._stopping:
            await asyncio.sleep(step)
            if self._quota_until and time.time() < self._quota_until:
                continue
            if self._busy or self.state not in ("live", "warming"):
                continue
            async with self._lock:
                snap = bytes(self._window)
            if not snap:
                continue
            if self._energy_db(snap) < float(self.ctx.settings.stt_min_energy_db):
                continue
            try:
                await asyncio.wait_for(self._run_guard(snap), timeout=self._request_timeout)
            except asyncio.TimeoutError:
                self.errors += 1
                self.ctx.on_error(f"{self.ctx.vendor.id} STT: timeout")
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error(f"{self.ctx.vendor.id} STT: {exc}")
                await asyncio.sleep(1.0)

    async def _run_guard(self, wav_pcm: bytes) -> None:
        self._busy = True
        try:
            await self._run_transcribe(wav_pcm)
        finally:
            self._busy = False

    def _charge_quota(self, exc: Exception) -> dict:
        headers = getattr(getattr(exc, "response", None), "headers", None)
        delay = quota_delay(exc, headers)
        self.errors += 1
        if delay is not None:
            self._quota_until = time.time() + min(max(delay, 3.0), 120.0)
        if not self._error_broadcasted:
            self._error_broadcasted = True
            if delay is not None:
                self.ctx.on_error(
                    f"{self.ctx.vendor.id} STT: rate-limit (reintento en ~{int(round(delay))} s)"
                )
            else:
                self.ctx.on_error(f"{self.ctx.vendor.id} STT: {exc}")

    async def stop(self) -> None:
        await super().stop()
        if self._ticker:
            self._ticker.cancel()

    def _fmt_wav(self, pcm: bytes) -> bytes:
        import struct

        n = len(pcm) // 2
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, 16_000, 16_000 * 2, 2, 16, b"data", len(pcm),
        )
        return header + pcm


class OpenAIWhisperSttProvider(_WindowedSttBase):
    """STT vía POST {base}/audio/transcriptions (Whisper-style, no streaming)."""

    async def _run_transcribe(self, wav_pcm: bytes) -> None:
        client = _OpenAIClient(self.ctx.vendor)
        url = client.transcriptions_url(self._model)
        files = {
            "file": ("audio.wav", self._fmt_wav(wav_pcm), "audio/wav"),
            "model": (None, self._model),
            "language": (None, self.ctx.original_language),
            "response_format": (None, "json"),
        }
        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as hx:
                resp = await hx.post(url, headers=client.headers(), files=files)
                resp.raise_for_status()
            text = (resp.json() or {}).get("text", "").strip()
            if text:
                self._emit("final", text)
            self._quota_until = 0.0
            self._error_broadcasted = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._charge_quota(exc)


class OpenAIInlineAudioSttProvider(_WindowedSttBase):
    """STT por ventanas con chat completions y audio inline (input_audio/b64)."""

    async def _run_transcribe(self, wav_pcm: bytes) -> None:
        client = _OpenAIClient(self.ctx.vendor)
        url = client.chat_url(self._model)
        b64 = base64.b64encode(self._fmt_wav(wav_pcm)).decode("ascii")
        body = {
            "model": self._model,
            "stream": True,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_stt_prompt(self.ctx)},
                        {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                    ],
                }
            ],
        }
        acc: list[str] = []
        last: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as hx:
                async with hx.stream("POST", url, headers=client.headers(), json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            acc.append(piece)
                            _emit_stream_once(acc, last, lambda t: self._emit("partial", t), step=2)
            full = "".join(acc).strip()
            if full:
                self._emit("final", full)
            self._quota_until = 0.0
            self._error_broadcasted = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._charge_quota(exc)