"""Provider principal: Gemini Live API (respuesta en texto) para transcribir y traducir en vivo.

Un LiveConnection por (sesión, idioma). Todo el audio entrante de la sesión se
reenvía a cada conexión. La salida son deltas de texto que convertimos en
subtítulos "partial" y "final" (turno completo).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import numpy as np

from app.providers.base import TranscriptProvider

log = logging.getLogger("openaiudio.gemini")

_QUOTA_RE = re.compile(r"retry in\s+([0-9.]+)", re.IGNORECASE)


def _vendor_ctx(ctx) -> object | None:
    return getattr(ctx, "vendor", None) or None


def _api_key(ctx) -> str:
    vendor = _vendor_ctx(ctx)
    if vendor is not None and getattr(vendor, "api_key", ""):
        return vendor.api_key
    return ctx.settings.gemini_api_key


def _quota_delay(exc: Exception) -> float | None:
    """Segundos sugeridos por el API (RetryInfo) o un backoff razonable si es 429/503."""
    msg = str(exc)
    m = _QUOTA_RE.search(msg)
    if m:
        try:
            return max(0.0, float(m.group(1)))
        except ValueError:
            pass
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return 10.0
    if "503" in msg or "UNAVAILABLE" in msg:
        return 6.0
    return None

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
    """Live streaming experimental (Gemini Live + texto).

    Precisa un modelo que soporte la modalidad TEXT (hoy los previews
    '*-transcribe-live' / '*-live-translate-preview'). Dado que esos modelos son
    inestables en preview, la ruta por defecto de OpenAIudio es el STT por
    chunks (GeminiChunkSttProvider) + traducción por texto.
    """

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        vendor = _vendor_ctx(ctx)
        self.model = (
            vendor.live_model
            if vendor is not None and vendor.live_model
            else ctx.settings.gemini_live_model
        )
        self._session = None
        self._acm = None
        self._client = None
        self._out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._tasks: list[asyncio.Task] = []
        self._partial: str = ""
        self._partial_for: dict[str, str] = {"input_transcription": "", "output_transcription": ""}
        self._max_retries = 3

    def _make_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=_api_key(self.ctx))
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
        config: dict = {"response_modalities": ["TEXT"]}
        if self.ctx.kind == "translate":
            config["translation_config"] = {"target_language_code": self.ctx.lang}
        config["system_instruction"] = {"parts": [{"text": build_prompt(self.ctx)}]}
        self._acm = client.aio.live.connect(model=self.model, config=config)
        self._session = await self._acm.__aenter__()
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
                    emitted = False
                    for tr_field in ("input_transcription", "output_transcription"):
                        tr = getattr(content, tr_field, None)
                        text = getattr(tr, "text", None) if tr is not None else None
                        if isinstance(text, str) and text:
                            if getattr(tr, "finished", False):
                                self._finalize_field(tr_field, text)
                            else:
                                self._partial_for[tr_field] = text
                                self._emit("partial", text)
                            emitted = True
                    model_turn = getattr(content, "model_turn", None)
                    if model_turn is not None and not emitted:
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

    def _finalize_field(self, field: str, text: str) -> None:
        self._emit("final", text)
        self._partial_for[field] = ""

    def _finalize_turn(self) -> None:
        if self._partial.strip():
            self._emit("final", self._partial)
        self._partial = ""
        for k in list(self._partial_for):
            if self._partial_for[k].strip():
                self._emit("final", self._partial_for[k])
            self._partial_for[k] = ""

    async def _reconnect(self) -> None:
        if self._stopping:
            return
        for attempt in range(self._max_retries):
            await asyncio.sleep(1.5 * (attempt + 1))
            try:
                if self._acm is not None:
                    try:
                        await self._acm.__aexit__(None, None, None)
                    except Exception:  # noqa: BLE001
                        pass
                    self._acm = None
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
        if self._acm is not None:
            try:
                await self._acm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._session = None
        self._acm = None
        self._state("stopped")


class GeminiChunkSttProvider(TranscriptProvider):
    """STT del original por **ventanas de audio** con un modelo multimodal por texto.

    Flujo robusto y verificado con la key real: acumulamos PCM16 16 kHz en una
    ventana deslizante (~6,5 s) y cada ~5 s enviamos la ventana como audio inline
    (audio/wav) a generate_content_stream. El modelo devuelve partial tras
    partial (streaming) y cerramos con final. Costo acotado, sin modelos live
    preview: 1 request cada STEP segundos por sesión.
    """

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        vendor = _vendor_ctx(ctx)
        self.model = (
            ctx.model_override or (vendor.stt_model if vendor is not None and vendor.stt_model else "")
            or ctx.settings.gemini_model
        )
        self._client = None
        self._window = bytearray()
        self._ticker: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._busy = False
        self._max_retries = 3
        self._request_timeout = self.ctx.settings.stt_timeout_sec
        self._quota_until = 0.0
        self._error_broadcasted = False

    def _make_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=_api_key(self.ctx))
        return self._client

    async def start(self) -> None:
        self._make_client()
        self._state("warming")
        if not _api_key(self.ctx):
            self._state("error")
            self.ctx.on_error(f"GEMINI_API_KEY / vendor {self.ctx.vendor.id if self.ctx.vendor else '?'} sin clave")
            return
        # No hacemos ping de autenticación aquí: un único 503 (rate limit
        # temporal del modelo) no debe tumbar el provider. La primera ventana
        # de audio ya sonará a key/modelo inválidos vía on_error.
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
        self._state("live" if self.state != "error" else "error")

    def _energy_db(self, data: bytes) -> float:
        samples = (
            np.frombuffer(bytes(data), dtype="<i2").astype(np.float32) / 32768.0
        ) if data else []
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
            log.debug(
                "ticker: transcribiendo ventana de %d bytes (state=%s energy=%.1f)",
                len(snap), self.state, self._energy_db(snap),
            )
            try:
                await asyncio.wait_for(self._transcribe(snap), timeout=self._request_timeout)
            except asyncio.TimeoutError:
                self.errors += 1
                self.ctx.on_error("Gemini STT transcribe: timeout")
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.ctx.on_error(f"Gemini STT transcribe: {exc}")
                await asyncio.sleep(1.0)

    async def _transcribe(self, wav_pcm: bytes) -> None:
        self._busy = True
        try:
            await self._transcribe_impl(wav_pcm)
        finally:
            self._busy = False

    async def _transcribe_impl(self, wav_pcm: bytes) -> None:
        client = self._make_client()
        from google.genai import types

        wav_bytes = _pcm16_to_wav(wav_pcm)
        contents = types.Content(
            parts=[
                types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                types.Part(text=build_prompt(self.ctx)),
            ]
        )
        try:
            await self._stt_stream(client, contents)
            self._quota_until = 0.0
            self._error_broadcasted = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            delay = _quota_delay(exc)
            if delay is not None:
                self._quota_until = time.time() + min(max(delay, 3.0), 120.0)
            if not self._error_broadcasted:
                self._error_broadcasted = True
                if delay is not None:
                    self.ctx.on_error(
                        f"Gemini STT: cuota agotada (reintento en ~{int(round(delay))} s)"
                    )
                else:
                    self.ctx.on_error(f"Gemini STT: {exc}")

    async def _stt_stream(self, client, contents) -> None:
        stream = await client.aio.models.generate_content_stream(
            model=self.model, contents=contents
        )
        acc: list[str] = []
        last_emit = ""
        async for chunk in stream:
            piece = getattr(chunk, "text", None)
            if not isinstance(piece, str) or not piece:
                continue
            acc.append(piece)
            partial = "".join(acc)
            if len(partial) - len(last_emit) >= 2:
                self._emit("partial", partial)
                last_emit = partial
        full = "".join(acc).strip()
        if full:
            self._emit("final", full)

    async def stop(self) -> None:
        await super().stop()
        if self._ticker:
            self._ticker.cancel()


def _pcm16_to_wav(pcm: bytes, rate: int = 16_000) -> bytes:
    """Encapsula PCM16 LE mono en un WAV RIFF mínimal (para inline audio)."""
    import struct

    n = len(pcm) // 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        1,  # mono
        rate,
        rate * 2,  # byte rate
        2,  # block align
        16,  # bits
        b"data",
        len(pcm),
    )
    return header + pcm


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
        self._max_retries = 3
        self._request_timeout = ctx.settings.stt_timeout_sec
        self._quota_until = 0.0
        self._error_broadcasted = False

    def _make_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=_api_key(self.ctx))
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
            if self._quota_until and time.time() < self._quota_until:
                await asyncio.sleep(min(self._quota_until - time.time(), 15.0))
                continue
            text = await self._q.get()
            candidate = (self._context + [text])[-self.CONTEXT_LEN :]
            waits = 0
            while True:
                try:
                    await asyncio.wait_for(
                        self._translate_one(client, types, system, "\n".join(candidate)),
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
                    delay = _quota_delay(exc)
                    if delay is None:
                        if not self._error_broadcasted:
                            self._error_broadcasted = True
                            self.ctx.on_error(f"Gemini texto: {exc}")
                        break  # no transitorio: soltar el segmento
                    self._quota_until = time.time() + min(max(delay, 3.0), 120.0)
                    if not self._error_broadcasted:
                        self._error_broadcasted = True
                        self.ctx.on_error(
                            f"Gemini texto: cuota agotada (reintento en ~{int(round(delay))} s)"
                        )
                    waits += 1
                    if waits > 3:
                        break  # reniega de un segmento tras 3 esperas de cuota seguidas
                    await asyncio.sleep(min(max(delay, 3.0), 120.0))

    async def _translate_one(self, client, types, system: str, payload: str) -> None:
        vendor = _vendor_ctx(self.ctx)
        model = (
            self.ctx.model_override
            or (vendor.translate_model if vendor is not None and vendor.translate_model else "")
            or self.ctx.settings.gemini_text_model
        )
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=payload,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.2,
                max_output_tokens=512,
            ),
        )
        acc: list[str] = []
        last_emit = ""
        async for chunk in stream:
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

    async def stop(self) -> None:
        await super().stop()
        if self._task:
            self._task.cancel()