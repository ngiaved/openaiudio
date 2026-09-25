"""WebSocket de la audiencia (elige sesión + idioma) y feeds de texto para OBS/vMix."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect

from app.config import AUDIO_RATE, LANGUAGES, lang_name
from app.store import Store


def build_audience_router(store: Store) -> APIRouter:
    router = APIRouter()

    @router.get("/api/languages")
    async def languages() -> dict:
        return {"audio_rate": AUDIO_RATE, "languages": {k: lang_name(k) for k in LANGUAGES}}

    @router.websocket("/ws/audience/{session_id}")
    async def audience_ws(ws: WebSocket, session_id: str, lang: str | None = None) -> None:
        session = store.get(session_id)
        if session is None:
            await ws.close(code=4404, reason="sesión no encontrada")
            return
        if lang is None:
            lang = session.original_language
        lang = lang.strip().lower()
        if lang not in session.targets:
            await ws.close(code=4404, reason="idioma no disponible para esta sesión")
            return
        await ws.accept()
        snapshot, conn = store.register_audience(session, lang, ws)
        try:
            await ws.send_json(snapshot)
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text"):
                    try:
                        msg = json.loads(message["text"])
                        if msg.get("type") == "ping":
                            await ws.send_json({"type": "pong", "t": msg.get("t")})
                    except json.JSONDecodeError:
                        pass
        except WebSocketDisconnect:
            pass
        finally:
            store.unregister_audience(session.id, lang, ws)

    @router.get("/feed/{session_id}/live")
    async def feed_live(session_id: str, lang: str) -> Response:
        """Texto plano del último bloque de subtítulos (overlays, OBS por HTTP, vMix)."""
        text = store.feed(session_id, lang)
        if text is None:
            raise HTTPException(status_code=404, detail="sesión/idioma no encontrado")
        return Response(content=text, media_type="text/plain; charset=utf-8")

    return router