"""API REST de sesiones + WebSocket de ingestión de audio del broadcaster."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect

from app.audio import AUDIO_RATE, resample_pcm16_to_rate
from app.config import lang_name
from app.models import CreateSessionRequest, SetGlossaryRequest
from app.store import Store

log = logging.getLogger("openaiudio.sessions")


def session_out(store: Store, session) -> dict:
    langs = []
    for lang, t in session.targets.items():
        langs.append(
            {
                "lang": lang,
                "name": lang_name(lang),
                "kind": t.kind,
                "via": t.via,
                "state": t.state,
                "is_original": t.kind == "original",
                "partial": t.buffer.partial[-160:],
                "preview": t.buffer.segments[-1].text if t.buffer.segments else "",
            }
        )
    return {
        "id": session.id,
        "title": session.title,
        "stage": session.stage or "",
        "provider": session.provider,
        "translation_mode": session.translation_mode,
        "original_language": session.original_language,
        "created_at": session.created_at,
        "on_air": session.on_air(),
        "ingesting": session.ingesting,
        "glossary": session.glossary,
        "languages": langs,
        "audience_total": store.audience_total(session.id),
    }


def build_sessions_router(store: Store) -> list[APIRouter]:
    """Routers REST (/api) e ingestión de audio (/ws), que viven fuera del prefijo /api."""
    router = APIRouter(prefix="/api")
    ws_router = APIRouter()

    @router.get("/sessions")
    async def list_sessions() -> dict:
        rows = [session_out(store, s) for s in store.list_sessions()]
        return {"sessions": rows}

    @router.post("/sessions", status_code=201)
    async def create_session(req: CreateSessionRequest) -> dict:
        try:
            session = store.create_session(req)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session_out(store, session)

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="sesión no encontrada")
        return session_out(store, session)

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        if not await store.delete_session(session_id):
            raise HTTPException(status_code=404, detail="sesión no encontrada")
        return Response(status_code=204)

    @router.post("/sessions/{session_id}/glossary")
    async def set_glossary(session_id: str, req: SetGlossaryRequest) -> dict:
        session = store.set_glossary(session_id, req.glossary)
        if session is None:
            raise HTTPException(status_code=404, detail="sesión no encontrada")
        return session_out(store, session)

    @router.get("/sessions/{session_id}/export")
    async def export_session(session_id: str, lang: str, fmt: str = "srt") -> Response:
        if fmt not in ("srt", "vtt", "txt"):
            raise HTTPException(status_code=400, detail="fmt debe ser srt, vtt o txt")
        text = store.export(session_id, lang, fmt)
        if text is None:
            raise HTTPException(status_code=404, detail="sesión/idioma no encontrado")
        media = {
            "srt": "application/x-subrip",
            "vtt": "text/vtt",
            "txt": "text/plain; charset=utf-8",
        }[fmt]
        filename = f"{session_id}.{lang}.{fmt}"
        return Response(
            content=text,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @ws_router.websocket("/ws/ingest/{session_id}")
    async def ingest(ws: WebSocket, session_id: str) -> None:
        session = store.get(session_id)
        if session is None:
            await ws.close(code=4404, reason="sesión no encontrada")
            return
        if session.ingesting:
            await ws.close(code=4409, reason="ya hay una señal de audio activa para esta sesión")
            return
        session.ingesting = True
        sample_rate = AUDIO_RATE
        qp = ws.query_params.get("sample_rate")
        if qp:
            try:
                sample_rate = int(qp)
            except ValueError:
                sample_rate = AUDIO_RATE
        try:
            await ws.accept()
            first = await ws.receive()
            if first["type"] == "websocket.disconnect":
                return
            if first.get("text"):
                try:
                    hello = json.loads(first["text"])
                    sample_rate = int(hello.get("sampleRate") or sample_rate)
                except ValueError:
                    pass
            await ws.send_json(
                {
                    "type": "hello",
                    "sessionId": session_id,
                    "sampleRate": sample_rate,
                    "chunkRate": AUDIO_RATE,
                    "languages": list(session.targets.keys()),
                }
            )
            async def ingest_bytes(st: Store, sid: str, rate: int, payload: bytes) -> None:
                data = payload if rate == AUDIO_RATE else resample_pcm16_to_rate(payload, rate)
                if not data:
                    return
                ok = await st.on_audio(sid, data)
                if not ok:
                    log.warning("audio hacia sesión inexistente %s", sid)

            if isinstance(first.get("bytes"), (bytes, bytearray)):
                await ingest_bytes(store, session_id, sample_rate, bytes(first["bytes"]))
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if isinstance(message.get("bytes"), (bytes, bytearray)):
                    await ingest_bytes(store, session_id, sample_rate, bytes(message["bytes"]))
                elif message.get("text"):
                    try:
                        msg = json.loads(message["text"])
                        if msg.get("type") == "control" and msg.get("cmd") == "stop":
                            break
                    except json.JSONDecodeError:
                        continue
        except WebSocketDisconnect:
            pass
        finally:
            session.ingesting = False
            log.info("sostenedor de audio desconectado de %s", session_id)

    return [router, ws_router]