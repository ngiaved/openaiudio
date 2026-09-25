"""Rute 100% local (opcional, sin API): STT con faster-whisper + traducción con Gemma vía Ollama.

- Provider "original": transcripción por ventanas deslizantes de faster-whisper
  (latencia ~2-3 s, mejor con la rute Gemini, pensado para eventos sin red).
- Provider "translate": recibe el texto transcrito original y lo traduce con
  Gemma 3 (Ollama) en streaming.

Requisitos:
    pip install openaiudio[local]
    (opcional servicio whisper GPU)  ollama serve  &&  ollama pull gemma3:4b
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from app.providers.base import TranscriptProvider

log = logging.getLogger("openaiudio.local")

WINDOW_SEC = 2.5
HOP_SEC = 0.5


class LocalWhisperProvider(TranscriptProvider):
    """Transcribe el audio entrante por ventanas deslizantes."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._buf = []
        self._buf_samples = 0
        self._task: asyncio.Task | None = None
        self._model = None
        self._last_final = ""

    async def start(self) -> None:
        self._state("warming")
        try:
            from faster_whisper import WhisperModel

            loop = asyncio.get_running_loop()
            compute = "int8"
            self._model = await loop.run_in_executor(
                None,
                lambda: WhisperModel(
                    self.ctx.settings.whisper_model,
                    device=self.ctx.settings.whisper_device,
                    compute_type=compute,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self._state("error")
            self.ctx.on_error(f"whisper: {exc}")
            return
        self._state("live")
        self.started_at = time.time()
        self._task = asyncio.create_task(self._process_loop())

    async def on_audio(self, chunk: bytes) -> None:
        await super().on_audio(chunk)
        import numpy as np

        from app.audio import pcm16_to_float32

        samples = pcm16_to_float32(chunk)
        if samples.size:
            self._buf.append(samples)
            self._buf_samples += samples.size
            self._buf = self._buf[-64:]

    async def _process_loop(self) -> None:
        import numpy as np

        while not self._stopping:
            await asyncio.sleep(HOP_SEC)
            if self._buf_samples < int(WINDOW_SEC * 16000):
                continue
            window_np = np.concatenate(self._buf)[-int(WINDOW_SEC * 16000):]
            self._buf = []
            self._buf_samples = 0
            try:
                text = await self._transcribe(window_np)
                norm = " ".join(text.split())
                if not norm or norm == self._last_final:
                    continue
                self._last_final = norm
                self._emit("partial", norm)
                await asyncio.sleep(0.05)
                self._emit("final", norm)
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error(f"whisper transcribe: {exc}")

    async def _transcribe(self, window: "object") -> str:
        assert self._model is not None
        loop = asyncio.get_running_loop()

        def run() -> str:
            lang = None if self.ctx.kind == "original" else self.ctx.original_language
            segs, _info = self._model.transcribe(
                window,
                language=lang,
                vad_filter=True,
                beam_size=5,
                without_timestamps=True,
            )
            return " ".join(s.text for s in segs)

        return await loop.run_in_executor(None, run)

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()


class OllamaTranslateProvider(TranscriptProvider):
    """Traduce el texto original (transcrito) a ctx.lang con Gemma 3 vía Ollama."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._task: asyncio.Task | None = None
        self._context: list[str] = []

    async def start(self) -> None:
        self._state("warming")
        try:
            import httpx  # noqa: F401

            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.ctx.settings.ollama_url}/api/tags")
                r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self._state("error")
            self.ctx.on_error(f"ollama inalcanzable en {self.ctx.settings.ollama_url}: {exc}")
            return
        self._state("live")
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
        import json

        import httpx

        from app.config import lang_name

        glossary = self.ctx.glossary_block
        system = (
            f"You are the simultaneous interpreter of a tech conference into {lang_name(self.ctx.lang)} "
            f"({self.ctx.lang}). Translate the incoming text of the speaker into {self.ctx.lang}. "
            "Output only the translation, nothing else. Keep terms natural and honor the glossary:\n"
            + (glossary if glossary else "(no glossary)")
        )
        while not self._stopping:
            text = await self._q.get()
            self._context = (self._context + [text])[-3:]
            messages = [{"role": "system", "content": system}]
            for c in self._context[:-1]:
                messages.append({"role": "user", "content": c})
                messages.append({"role": "assistant", "content": "…"})
            messages.append({"role": "user", "content": text})

            result, ok = await self._ollama_stream(messages, httpx)
            if not ok:
                self.errors += 1
                self.ctx.on_error("gemma no respondió")
                await asyncio.sleep(0.5)
                continue
            if result.strip():
                self._emit("final", result.strip())
            await asyncio.sleep(0.1)

    async def _ollama_stream(self, messages: list[dict], httpx) -> tuple[str, bool]:
        try:
            acc: list[str] = []
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.ctx.settings.ollama_url}/api/chat",
                    json={
                        "model": self.ctx.settings.ollama_model,
                        "messages": messages,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    last_emit = ""
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        payload = json.loads(line)
                        token = (payload.get("message") or {}).get("content", "")
                        if token:
                            acc.append(token)
                            partial = "".join(acc)
                            if len(partial) - len(last_emit) >= 3:
                                self._emit("partial", partial)
                                last_emit = partial
            return "".join(acc), True
        except Exception:  # noqa: BLE001
            return "", False

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()