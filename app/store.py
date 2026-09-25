"""Orquestador: sesiones, providers por (sesión, idioma), fan-out de audio y broadcast a la audiencia.

Diseño a escala:
  - Cada sesión tiene N objetivos (original + N traducciones).
  - El audio entrante se replica a todos los providers que escuchan audio.
  - Los providers de traducción de la rute local consumen el texto transcrito original.
  - Cada (sesión, idioma) tiene un buffer de subtítulos y un set de clientes de audiencia.
  - Los providers en idle se detienen automáticamente (ahorra cupo/costo) y se reinician al volver el audio.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass, field

from app.audio import AUDIO_RATE
from app.captions import CaptionBuffer, export_captions, feed_text
from app.config import Settings, default_targets
from app.models import CreateSessionRequest, GlossaryEntry, TargetSpec, slugify

log = logging.getLogger("openaiudio.store")

SWEEP_INTERVAL = 30.0


@dataclass
class Target:
    lang: str
    kind: str  # "original" | "translate"
    via: str = "audio"  # cómo se produce: "audio" (live) o "text" (desde transcripción)
    provider: object | None = None
    state: str = "idle"  # idle | warming | live | paused | error | stopped
    errors: int = 0
    buffer: CaptionBuffer = field(init=False)
    uses_audio: bool = False
    uses_text: bool = False
    stash: list[str] = field(default_factory=list)  # texto pendiente si el provider aún arranca
    _starting: bool = False

    def __post_init__(self) -> None:
        self.buffer = CaptionBuffer(lang=self.lang, kind=self.kind)


@dataclass
class Session:
    id: str
    title: str
    stage: str | None
    original_language: str
    provider: str
    translation_mode: str
    glossary: list[dict[str, str]]
    created_at: float = field(default_factory=time.time)
    last_audio_at: float = 0.0
    ingesting: bool = False
    targets: dict[str, Target] = field(default_factory=dict)

    def language_list(self) -> list[str]:
        return list(self.targets.keys())

    def on_air(self) -> bool:
        return self.ingesting or time.time() - self.last_audio_at < 10.0


@dataclass(eq=False)
class AudienceConn:
    ws: object
    q: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=512))
    task: asyncio.Task | None = None

    __hash__ = object.__hash__


def provider_shape(provider: str, kind: str, via: str) -> tuple[bool, bool]:
    """(usa_audio, usa_texto) para (provider, rol, vía) dados."""
    if provider == "local":
        return (True, False) if kind == "original" else (False, True)
    if kind == "original":
        return True, False
    return (True, False) if via == "audio" else (False, True)


def default_via(provider: str, mode: str) -> str:
    """Decide la vía de traducción según el modo configurado (audio | text | auto).

    La vía por texto es robusta y económica (generate_content sobre segmentos
    finales); es el default para Gemini. La vía por audio (Live streaming)
    queda como opción experimental con `audio` explícito o con el mock.
    """
    if mode == "audio":
        return "audio"
    if mode == "text":
        return "text"
    return "text" if provider in ("gemini", "local") else "audio"


class Store:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, Session] = {}
        self._audience: dict[tuple[str, str], set[AudienceConn]] = {}
        self._active_providers = 0
        self._sweeper: asyncio.Task | None = None
        if settings.obs_out_dir:
            os.makedirs(settings.obs_out_dir, exist_ok=True)

    # ------------------------------------------------------------- sesiones
    def create_session(self, req: CreateSessionRequest) -> Session:
        if len(self.sessions) >= self.settings.max_sessions:
            raise ValueError(f"máximo de {self.settings.max_sessions} sesiones alcanzado")
        sid = req.session_id or (slugify(req.title) + "-" + secrets.token_hex(2))
        while sid in self.sessions:
            sid = slugify(req.title) + "-" + secrets.token_hex(2)
        provider = req.provider or self.settings.effective_provider
        mode = req.translation_mode or self.settings.translation_mode
        targets: list[TargetSpec] = req.targets or [
            TargetSpec(lang=ln, kind="translate")
            for ln in sorted({d["lang"] for d in default_targets(req.original_language)})
        ]
        session = Session(
            id=sid,
            title=req.title.strip(),
            stage=req.stage,
            original_language=req.original_language,
            provider=provider,
            translation_mode=mode,
            glossary=[g.model_dump() for g in req.glossary],
        )
        by_lang = {t.lang: t for t in targets}
        by_lang.setdefault(req.original_language, TargetSpec(lang=req.original_language, kind="original"))
        for lang, spec in by_lang.items():
            kind = "original" if lang == req.original_language else "translate"
            via = spec.via or default_via(provider, mode)
            t = Target(lang=lang, kind=kind, via="audio" if kind == "original" else via)
            t.uses_audio, t.uses_text = provider_shape(provider, kind, t.via)
            session.targets[lang] = t
        self.sessions[sid] = session
        log.info(
            "sesión %s creada (original=%s, targets=%s, provider=%s, traducción=%s)",
            sid,
            session.original_language,
            sorted(by_lang),
            provider,
            mode,
        )
        return session

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self.sessions.values())

    async def delete_session(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False
        for t in session.targets.values():
            await self._stop_target(t)
            self._close_audience(session_id, t.lang)
        log.info("sesión %s eliminada", session_id)
        return True

    def set_glossary(self, session_id: str, entries: list[GlossaryEntry]) -> Session | None:
        session = self.get(session_id)
        if session is None:
            return None
        session.glossary = [g.model_dump() for g in entries]
        return session

    # -------------------------------------------------------------- providers
    def _make_provider(self, session: Session, target: Target):
        from app.providers import gemini as gemini_mod
        from app.providers import local as local_mod
        from app.providers import mock as mock_mod

        ctx = self._ctx(session, target)
        if session.provider == "mock":
            return mock_mod.MockProvider(ctx)
        if session.provider == "local":
            if target.kind == "original":
                return local_mod.LocalWhisperProvider(ctx)
            return local_mod.OllamaTranslateProvider(ctx)
        if target.kind == "original":
            return gemini_mod.GeminiChunkSttProvider(ctx)
        if target.via == "audio":
            return gemini_mod.GeminiProvider(ctx)
        return gemini_mod.GeminiTextTranslateProvider(ctx)

    def _ctx(self, session: Session, target: Target):
        from app.providers.base import TargetContext

        return TargetContext(
            session_id=session.id,
            lang=target.lang,
            kind=target.kind,
            original_language=session.original_language,
            glossary=session.glossary,
            settings=self.settings,
            emit=lambda kind, text: self.push_caption(session.id, target.lang, kind, text),
            on_state=lambda state: self._set_state(session.id, target.lang, state),
            on_error=lambda msg: self._target_error(session.id, target.lang, msg),
        )

    async def _start_target(self, session: Session, target: Target) -> None:
        if target.provider is not None and target.state in ("live", "warming"):
            return
        if self._active_providers >= self.settings.max_providers:
            target.state = "queued"
            self._set_state(session.id, target.lang, "queued")
            return
        target.provider = self._make_provider(session, target)
        self._active_providers += 1
        log.info("iniciando provider %s para %s/%s (activos=%d)", session.provider, session.id, target.lang, self._active_providers)
        try:
            await target.provider.start()
        except Exception:  # noqa: BLE001
            log.exception("provider %s/%s lanzó excepción", session.id, target.lang)
            target.provider.state = "error"
        if target.provider.state == "error":
            self._active_providers = max(0, self._active_providers - 1)
            target.provider = None
            target._starting = False
            await self._promote_queued()
            return
        target._starting = False
        if target.stash:
            staged, target.stash = target.stash, []
            for seg in staged:
                asyncio.create_task(self._safe_on_text(target, seg))

    async def _release_budget(self) -> None:
        self._active_providers = max(0, self._active_providers - 1)
        await self._promote_queued()

    async def _promote_queued(self) -> None:
        for session in list(self.sessions.values()):
            for lang, target in list(session.targets.items()):
                if target.state == "queued" and self._active_providers < self.settings.max_providers:
                    asyncio.create_task(self._start_target(session, target))

    async def _stop_target(self, target: Target) -> None:
        if target.provider is not None:
            try:
                await target.provider.stop()
            except Exception:  # noqa: BLE001
                log.exception("error al detener provider")
            await self._release_budget()
            target.provider = None
        target.state = "stopped"

    async def _pause_target(self, target: Target) -> None:
        if target.provider is None:
            return
        try:
            await target.provider.stop()
        except Exception:  # noqa: BLE001
            pass
        await self._release_budget()
        target.provider = None
        target.state = "paused"

    # ---------------------------------------------------------------- audio
    async def on_audio(self, session_id: str, chunk: bytes) -> bool:
        session = self.get(session_id)
        if session is None:
            return False
        session.last_audio_at = time.time()
        for t in session.targets.values():
            if not t.uses_audio:
                continue
            if t.state in ("idle", "paused", "queued", "error", "stopped"):
                if t.state != "queued":
                    t.state = "idle"
                asyncio.create_task(self._start_target(session, t))
                continue
            if t.provider is not None:
                try:
                    await t.provider.on_audio(chunk)
                except Exception:  # noqa: BLE001
                    t.errors += 1
        return True

    # --------------------------------------------------------------- captions
    def push_caption(self, session_id: str, lang: str, kind: str, text: str) -> None:
        session = self.get(session_id)
        if session is None:
            return
        target = session.targets.get(lang)
        if target is None:
            return
        buf = target.buffer
        ev: dict
        if kind == "partial":
            buf.set_partial(text)
            ev = {"type": "caption", "lang": lang, "kind": "partial", "text": text, "seq": buf._seq}
        else:
            seg = buf.finalize(text)
            if seg is None:
                return
            ev = {"type": "caption", "lang": lang, "kind": "final", "text": seg.text, "seq": seg.seq}
            if kind == "original":
                self._fanout_text(session, seg.text)
        self._broadcast(session_id, lang, ev)
        self._write_obs_feed(session, lang)

    def _fanout_text(self, session: Session, text: str) -> None:
        for t in session.targets.values():
            if not t.uses_text:
                continue
            t.stash.append(text)
            if len(t.stash) > 32:  # acotado: no crecer indefinidamente
                del t.stash[: len(t.stash) - 32]
            if t.provider is not None:
                asyncio.create_task(self._safe_on_text(t, text))
            else:
                self._ensure_text_started(session, t)

    def _ensure_text_started(self, session: Session, target: Target) -> None:
        """Arranca a demanda un traductor por texto (no lo inicia el audio).

        Hasta que el provider esté listo, el texto queda en `target.stash` y
        `_start_target` lo drena apenas el provider queda vivo.
        """
        if target._starting or target.state in ("live", "warming"):
            return
        target._starting = True
        target.state = "idle"
        asyncio.create_task(self._start_target(session, target))

    async def _safe_on_text(self, target: Target, text: str) -> None:
        try:
            if target.provider is not None:
                await target.provider.on_text(text)
        except Exception:  # noqa: BLE001
            target.errors += 1

    def _set_state(self, session_id: str, lang: str, state: str) -> None:
        session = self.get(session_id)
        if session and lang in session.targets:
            session.targets[lang].state = state
        self._broadcast(session_id, lang, {"type": "state", "lang": lang, "state": state})

    def _target_error(self, session_id: str, lang: str, message: str) -> None:
        session = self.get(session_id)
        if session and lang in session.targets:
            session.targets[lang].errors += 1
        self._broadcast(
            session_id,
            lang,
            {"type": "state", "lang": lang, "state": "error", "error": message},
        )
        log.warning("%s/%s: %s", session_id, lang, message)

    def _write_obs_feed(self, session: Session, lang: str) -> None:
        out = self.settings.obs_out_dir
        if not out:
            return
        buf = session.targets[lang].buffer
        try:
            with open(os.path.join(out, f"{session.id}.{lang}.live.txt"), "w", encoding="utf-8") as f:
                f.write(feed_text(buf))
            with open(os.path.join(out, f"{session.id}.{lang}.full.txt"), "w", encoding="utf-8") as f:
                f.write(buf.full_text())
        except OSError:
            log.exception("no se pudo escribir feed OBS")

    # -------------------------------------------------------------- audience
    def register_audience(self, session: Session, lang: str, ws: object) -> tuple[dict, AudienceConn]:
        key = (session.id, lang)
        conn = AudienceConn(ws=ws)
        self._audience.setdefault(key, set()).add(conn)
        conn.task = asyncio.create_task(self._forwarder(conn))
        snapshot = self._audience_snapshot(session, lang)
        return snapshot, conn

    def _audience_snapshot(self, session: Session, lang: str) -> dict:
        target = session.targets.get(lang)
        if target is None:
            return {}
        view = {
            "type": "snapshot",
            "session": session.id,
            "title": session.title,
            "stage": session.stage or "",
            "lang": lang,
            "original_language": session.original_language,
            "kind": target.kind,
            "state": target.state,
            **target.buffer.snapshot(),
        }
        return view

    def unregister_audience(self, session_id: str, lang: str, ws: object) -> None:
        key = (session_id, lang)
        conn_set = self._audience.get(key)
        if not conn_set:
            return
        for conn in list(conn_set):
            if conn.ws is ws:
                conn_set.discard(conn)
                if conn.task:
                    conn.task.cancel()
        if not conn_set:
            self._audience.pop(key, None)

    async def _forwarder(self, conn: AudienceConn) -> None:
        try:
            while True:
                ev = await conn.q.get()
                await conn.ws.send_json(ev)
        except Exception:  # noqa: BLE001
            pass

    def _broadcast(self, session_id: str, lang: str, ev: dict) -> None:
        key = (session_id, lang)
        conn_set = self._audience.get(key)
        if not conn_set:
            return
        for conn in list(conn_set):
            try:
                conn.q.put_nowait(ev)
            except asyncio.QueueFull:
                conn_set.discard(conn)
                if conn.task:
                    conn.task.cancel()

    def _close_audience(self, session_id: str, lang: str) -> None:
        key = (session_id, lang)
        conn_set = self._audience.pop(key, None)
        if not conn_set:
            return
        for conn in list(conn_set):
            if conn.task:
                conn.task.cancel()
            asyncio.create_task(self._close_ws(conn.ws))

    async def _close_ws(self, ws: object) -> None:
        try:
            await getattr(ws, "close")(code=1000, reason="sesión terminada")
        except Exception:  # noqa: BLE001
            pass

    def audience_count(self, session_id: str, lang: str) -> int:
        return len(self._audience.get((session_id, lang), set()))

    def audience_total(self, session_id: str) -> int:
        total = 0
        for (sid, _lang), conns in self._audience.items():
            if sid == session_id:
                total += len(conns)
        return total

    def top_audience(self, top: int = 25) -> list[tuple[str, str, int]]:
        """Sesiones/idiomas con más espectadores (para priorizar providers)."""
        pairs = []
        for (sid, lang), conns in self._audience.items():
            if conns:
                pairs.append((sid, lang, len(conns)))
        return sorted(pairs, key=lambda x: x[2], reverse=True)[:top]

    # --------------------------------------------------------------- exports
    def export(self, session_id: str, lang: str, fmt: str) -> str | None:
        session = self.get(session_id)
        if session is None or lang not in session.targets:
            return None
        return export_captions(session.targets[lang].buffer, fmt)

    def feed(self, session_id: str, lang: str) -> str | None:
        session = self.get(session_id)
        if session is None or lang not in session.targets:
            return None
        return feed_text(session.targets[lang].buffer)

    # -------------------------------------------------------------- monitoreo
    def admin_status(self) -> dict:
        out = []
        for session in sorted(self.sessions.values(), key=lambda s: s.created_at):
            targets = []
            for lang, t in session.targets.items():
                targets.append(
                    {
                        "lang": lang,
                        "kind": t.kind,
                        "via": t.via,
                        "state": t.state,
                        "errors": t.errors,
                        "audience": self.audience_count(session.id, lang),
                        "partial": t.buffer.partial[-96:],
                        "segments": len(t.buffer.segments),
                        "provider": type(t.provider).__name__ if t.provider else None,
                    }
                )
            out.append(
                {
                    "id": session.id,
                    "title": session.title,
                    "stage": session.stage or "",
                    "provider": session.provider,
                    "translation_mode": session.translation_mode,
                    "original_language": session.original_language,
                    "on_air": session.on_air(),
                    "created_at": session.created_at,
                    "last_audio_at": session.last_audio_at,
                    "targets": targets,
                }
            )
        return {
            "active_providers": self._active_providers,
            "max_providers": self.settings.max_providers,
            "sessions_count": len(self.sessions),
            "max_sessions": self.settings.max_sessions,
            "model": self.settings.gemini_model,
            "sessions": out,
        }

    # ----------------------------------------------------------------- sweep
    def start_sweeper(self) -> None:
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL)
            for session in list(self.sessions.values()):
                if not session.targets:
                    continue
                any_live = any(t.state in ("live", "warming") for t in session.targets.values())
                if not any_live or session.on_air():
                    continue
                if session.last_audio_at and session.last_audio_at > 0 and time.time() - session.last_audio_at > self.settings.idle_timeout_sec:
                    log.info("pausando providers de %s por inactividad", session.id)
                    for t in session.targets.values():
                        await self._pause_target(t)

    async def close_all(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        for session in list(self.sessions.values()):
            for t in session.targets.values():
                await self._stop_target(t)
            for lang in list(session.targets):
                self._close_audience(session.id, lang)