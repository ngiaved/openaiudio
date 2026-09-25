"""Anthropic Messages API provider (translation by text, streaming SSE)."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from app.providers.base import TranscriptProvider
from app.providers.openai_compat import build_stt_prompt, quota_delay

log = logging.getLogger("openaiudio.anthropic")

SYSTEM_HINT = (
    "\nUse the anthropic-version 2023-06-01 and produce only the requested output."
)


class AnthropicTextTranslateProvider(TranscriptProvider):
    """Traducción por texto con la API de Messages de Anthropic (Claude)."""

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
                        self._translate_one("\n".join(candidate)),
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

    async def _translate_one(self, payload: str) -> None:
        url = f"{self.ctx.vendor.base_url.rstrip('/')}/messages"
        headers = {
            "x-api-key": self.ctx.vendor.api_key,
            "anthropic-version": self.ctx.vendor.extra.get("anthropic_version", "2023-06-01"),
            "content-type": "application/json",
        }
        body = {
            "model": self._model,
            "max_tokens": 512,
            "temperature": 0.2,
            "stream": True,
            "system": build_stt_prompt(self.ctx),
            "messages": [{"role": "user", "content": payload}],
        }
        acc: list[str] = []
        last_len = 0
        async with httpx.AsyncClient(timeout=self._request_timeout) as hx:
            async with hx.stream("POST", url, headers=headers, json=body) as resp:
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
                    if obj.get("type") == "content_block_delta":
                        delta = obj.get("delta") or {}
                        piece = delta.get("text")
                        if piece:
                            acc.append(piece)
                            text = "".join(acc)
                            if len(text) - last_len >= 3:
                                self._emit("partial", text)
                                last_len = len(text)
        out = "".join(acc).strip()
        if out:
            self._emit("final", out)

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()