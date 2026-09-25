"""Provider de demo (sin red, sin API key): genera subtítulos de prueba según la energía del audio.

Útil para probar el flujo completo (broadcaster -> backend -> audiencia), para
ensayos y para que cualquier conferencia pueda correr el pipeline sin costo.
"""

from __future__ import annotations

import asyncio
import time

from app.audio import energy_db, pcm16_to_float32
from app.providers.base import TranscriptProvider

PHRASES = [
    "Señal de audio en vivo y en directo.",
    "Este es un subtítulo simulado, el proveedor real es Gemini o la rute local.",
    "OpenAIudio: transcripción simultánea open source para conferencias.",
]


class MockProvider(TranscriptProvider):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._active = 0
        self._silence = 0
        self._idx = 0
        self._phrase = ""
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._state("warming")
        await asyncio.sleep(0.1)
        self._state("live")
        self.started_at = time.time()
        self._task = asyncio.create_task(self._ticker())

    async def on_audio(self, chunk: bytes) -> None:
        await super().on_audio(chunk)
        samples = pcm16_to_float32(chunk)
        db = energy_db(samples)
        if db > -45.0:
            self._active += 1
            self._silence = 0
        else:
            self._silence += 1
            if self._silence > 4 and self._phrase:
                self._emit("final", self._phrase)
                self._phrase = ""

    async def _ticker(self) -> None:
        phrase = PHRASES[self._idx % len(PHRASES)]
        words = phrase.split()
        n = 0
        while not self._stopping:
            await asyncio.sleep(0.45)
            if self._active < 2:
                continue
            n += 1
            if n > len(words) + 2:
                self._emit("final", self._phrase or phrase)
                self._phrase = ""
                n = 0
                self._idx += 1
                continue
            if n <= len(words):
                self._phrase = " ".join(words[:n])
                self._emit("partial", self._phrase)

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()
        if self._phrase:
            self._emit("final", self._phrase)
            self._phrase = ""