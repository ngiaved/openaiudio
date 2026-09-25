"""OpenAIudio — transcripción y traducción simultánea open source para conferencias.

Un solo servidor FastAPI sirve:
  - API REST + WebSockets (ingestión de audio, audiencia, monitoreo, exportación).
  - Frontend estático (vista de audiencia, consola de broadcast, panel de producción).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.routers.admin import build_admin_router
from app.routers.audience import build_audience_router
from app.routers.sessions import build_sessions_router
from app.routers.vendors import build_vendors_router
from app.store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("openaiudio.main")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.start_sweeper()
        log.info(
            "OpenAIudio lista · provider efectivo=%s · traducción=%s · modelo=%s · max_providers=%d · max_sessions=%d",
            settings.effective_provider,
            settings.translation_mode,
            settings.gemini_model,
            settings.max_providers,
            settings.max_sessions,
        )
        yield
        await store.close_all()

    store = Store(settings)
    app = FastAPI(title="OpenAIudio", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store

    for builder in (build_vendors_router, build_sessions_router, build_audience_router, build_admin_router):
        routers = builder(store)
        if not isinstance(routers, (list, tuple)):
            routers = [routers]
        for r in routers:
            app.include_router(r)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "ok": True,
            "provider": settings.effective_provider,
            "translation_mode": settings.translation_mode,
        }

    web_root = WEB_DIST if WEB_DIST.is_dir() else WEB_DIR
    if web_root.is_dir():
        app.mount("/", StaticFiles(directory=str(web_root), html=True), name="web")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    s = Settings()
    uvicorn.run(app, host=s.host, port=s.port)