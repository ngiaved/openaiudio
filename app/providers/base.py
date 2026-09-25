"""Contrato de providers de transcripción/traducción y contexto compartido.

Un provider produce subtítulos para un (sesión, idioma) específico. Puede
consumir audio en vivo (push_audio) o texto ya transcrito (push_text), según
el rol:
  - rol "original":  escucha el audio y transcribe verbatim.
  - rol "translate": escucha el audio (Gemini) o el texto original (Gemma) y traduce.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Callable

EmitKind = str  # "partial" | "final"


@dataclass
class TargetContext:
    """Lo que un provider necesita saber sobre su (sesión, idioma, rol)."""
    session_id: str
    lang: str
    kind: str  # "original" | "translate"
    original_language: str
    glossary: list[dict[str, str]]
    settings: object  # app.config.Settings
    emit: Callable[[EmitKind, str], None] = lambda kind, text: None
    on_state: Callable[[str], None] = lambda state: None
    on_error: Callable[[str], None] = lambda message: None
    vendor: object | None = None  # app.vendors.Vendor resuelto para este target
    model_override: str = ""  # override de modelo para este target (sesión/GUI)

    @property
    def glossary_block(self) -> str:
        """Texto de glosario para inyectar en el prompt del modelo."""
        if not self.glossary:
            return ""
        lines = []
        for g in self.glossary:
            if g.get("target"):
                lines.append(f"- {g['source']} -> {g['target']}" + (f"  ({g['context']})" if g.get("context") else ""))
            else:
                lines.append(f"- {g['source']} (respetar tal cual)")
        return "\n".join(lines)


class TranscriptProvider(abc.ABC):
    state: str = "idle"  # idle | warming | live | paused | error | queued | stopped

    def __init__(self, ctx: TargetContext) -> None:
        self.ctx = ctx
        self.errors: int = 0
        self.started_at: float | None = None
        self.last_partial_at: float = 0.0
        self.last_audio_at: float = 0.0
        self._stopping = False

    @abc.abstractmethod
    async def start(self) -> None: ...

    async def stop(self) -> None:
        self._stopping = True
        self.state = "stopped"

    async def on_audio(self, chunk: bytes) -> None:
        """Chunk PCM16 16 kHz mono little-endian."""
        self.last_audio_at = time.time()

    async def on_text(self, text: str) -> None:
        """Segmento de texto ya transcrito (para traductores a partir del original)."""

    def _emit(self, kind: EmitKind, text: str) -> None:
        if kind == "partial":
            self.last_partial_at = time.time()
        self.ctx.emit(kind, text)

    def _state(self, state: str) -> None:
        if state == self.state:
            return  # solo se transmite cuando el estado cambia de verdad
        self.state = state
        self.ctx.on_state(state)

    @property
    def latency_ms(self) -> int | None:
        if not self.last_partial_at:
            return None
        return int((time.time() - self.last_partial_at) * 1000)

    def describe(self) -> dict:
        return {
            "lang": self.ctx.lang,
            "kind": self.ctx.kind,
            "provider": type(self).__name__,
            "state": self.state,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
            "last_audio_at": self.last_audio_at,
        }