"""Provider principal: Gemini Live API (respuesta en texto) para transcribir y traducir en vivo.

Un LiveConnection por (sesión, idioma). Todo el audio entrante de la sesión se
reenvía a cada conexión. La salida son deltas de texto que convertimos en
subtítulos "partial" y "final" (turno completo).
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.providers.base import TranscriptProvider

log = logging.getLogger("openaiudio.gemini")

TRANSCRIBE_PROMPT = (
    "You are the live closed-caption engine of a tech conference. "
    "Transcribe VERBATIM, in the original language ({lang}), everything the speaker says. "
    "Output only the plain transcription text, nothing else: no explanations, no headers, "
    "no trivia, no translation. Preserve technical terms, product names and proper nouns "
    "exactly as spoken (e.g. Kubernetes, Kafka, Nerdearla). "
    "If it is silent, output nothing.\n"
)
TRANSLATE_PROMPT = (
    "You are the simultaneous interpreter of a tech conference. "
    "Produce a fluent, natural real-time translation into {lang_name} ({lang}) of everything "
    "the speaker says. Output only the translated text, nothing else. Keep technical terms in "
    "English when that is natural and idiomatic; translate everything else faithfully.\n"
)


def build_prompt(ctx) -> str:
    if ctx.kind == "original":
        base = TRANSCRIBE_PROMPT.format(lang=ctx.original_language)
    else:
        from app.config import lang_name

        base = TRANSLATE_PROMPT.format(lang=ctx.lang, lang_name=lang_name(ctx.lang))
    glossary = ctx.glossary_block
    if glossary:
        base += "\nGlossary / terminology map — always honor it:\n" + glossary + "\n"
    return base


class GeminiProvider(TranscriptProvider):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.model = ctx.settings.gemini_model
        self._session = None
        self._client = None
        self._out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._tasks: list[asyncio.Task] = []
        self._partial: str = ""
        self._max_retries = 3

    def _make_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.ctx.settings.gemini_api_key)
        return self._client

    async def start(self) -> None:
        try:
            self._state("warming")
            await self._connect()
            self._state("live")
            self.started_at = time.time()
            log.info("gemini live conectado para %s/%s", self.ctx.session_id, self.ctx.lang)
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self._state("error")
            self.ctx.on_error(f"Gemini connect: {exc}")
            log.exception("gemini connect falló para %s/%s", self.ctx.session_id, self.ctx.lang)

    async def _connect(self) -> None:
        from google.genai import types

        client = self._make_client()
        config = {
            "response_modalities": ["TEXT"],
            "system_instruction": {"parts": [{"text": build_prompt(self.ctx)}]},
        }
        session = await client.aio.live.connect(model=self.model, config=config)
        self._session = session
        self._tasks = [
            asyncio.create_task(self._audio_loop()),
            asyncio.create_task(self._receive_loop()),
        ]

    async def on_audio(self, chunk: bytes) -> None:
        await super().on_audio(chunk)
        if self._session is None or self.state in ("idle", "stopped", "error"):
            return
        try:
            self._out_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                self._out_queue.get_nowait()  # drop el chunk más viejo: importa fresh
            except asyncio.QueueEmpty:
                pass
            self._out_queue.put_nowait(chunk)

    async def _audio_loop(self) -> None:
        from google.genai import types

        assert self._session is not None
        while not self._stopping:
            try:
                chunk = await asyncio.wait_for(self._out_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                # Sin audio: mantener viva la conexión con un silencio mínimo no se envía; solo seguimos.
                continue
            try:
                await self._session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                )
            except Exception:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error("send_realtime_input falló")
                break

    async def _receive_loop(self) -> None:
        assert self._session is not None
        while not self._stopping:
            try:
                async for msg in self._session.receive():
                    content = getattr(msg, "server_content", None)
                    if content is None:
                        continue
                    model_turn = getattr(content, "model_turn", None)
                    if model_turn is not None:
                        for part in getattr(model_turn, "parts", []):
                            text = getattr(part, "text", None)
                            if isinstance(text, str) and text:
                                self._partial += text
                                self._emit("partial", self._partial)
                    if getattr(content, "turn_complete", False) or getattr(
                        content, "generation_complete", False
                    ) or getattr(content, "interrupted", False):
                        self._finalize_turn()
                break
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error(f"Gemini streaming: {exc}")
                self._finalize_turn()
                await self._reconnect()
                break

    def _finalize_turn(self) -> None:
        if self._partial.strip():
            self._emit("final", self._partial)
        self._partial = ""

    async def _reconnect(self) -> None:
        if self._stopping:
            return
        for attempt in range(self._max_retries):
            await asyncio.sleep(1.5 * (attempt + 1))
            try:
                if self._session is not None:
                    try:
                        await self._session.close()
                    except Exception:  # noqa: BLE001
                        pass
                await self._connect()
                self._state("live")
                log.info("gemini reconectado %s/%s", self.ctx.session_id, self.ctx.lang)
                return
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error(f"Gemini reconnect {attempt + 1}: {exc}")
        self._state("error")
        self.ctx.on_error(f"Gemini sin conexión tras {self._max_retries} reintentos")

    async def stop(self) -> None:
        await super().stop()
        for task in self._tasks:
            task.cancel()
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001
                pass
        self._session = None
        self._state("stopped")


class GeminiTextTranslateProvider(TranscriptProvider):
    """Traducción por texto (topología B/C): consume los segmentos finales del original y
    traduce con el modelo de texto Gemini vía generate_content streaming.

    Mucho más barato que una conexión Live por idioma: ideal como fallback o cuando
    hay presupuesto limitado. La traducción parte del texto transcrito (1 salto más
    que la vía audio, por eso TRANSLATION_MODE=text es la opción económica).
    """

    CONTEXT_LEN = 2

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._task: asyncio.Task | None = None
        self._context: list[str] = []
        self._client = None

    def _make_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.ctx.settings.gemini_api_key)
        return self._client

    async def start(self) -> None:
        self._state("warming")
        try:
            self._make_client()
            self._state("live")
            self.started_at = time.time()
            self._task = asyncio.create_task(self._translate_loop())
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self._state("error")
            self.ctx.on_error(f"Gemini texto: {exc}")

    async def on_text(self, text: str) -> None:
        norm = " ".join(text.split())
        if not norm:
            return
        try:
            self._q.put_nowait(norm)
        except asyncio.QueueFull:
            return

    async def _translate_loop(self) -> None:
        from google.genai import types

        client = self._make_client()
        system = build_prompt(self.ctx)
        while not self._stopping:
            text = await self._q.get()
            self._context = (self._context + [text])[-self.CONTEXT_LEN :]
            payload = "\n".join(self._context)
            acc: list[str] = []
            last_emit = ""
            try:
                async for chunk in client.aio.models.generate_content_stream(
                    model=self.ctx.settings.gemini_text_model,
                    contents=payload,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.2,
                        max_output_tokens=512,
                    ),
                ):
                    piece = getattr(chunk, "text", None)
                    if not isinstance(piece, str) or not piece:
                        continue
                    acc.append(piece)
                    partial = "".join(acc)
                    if len(partial) - len(last_emit) >= 3:
                        self._emit("partial", partial)
                        last_emit = partial
                if "".join(acc).strip():
                    self._emit("final", "".join(acc).strip())
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error(f"Gemini texto: {exc}")
                await asyncio.sleep(0.3)

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()