"""Panel de monitoreo para el equipo de producción."""

from __future__ import annotations

from fastapi import APIRouter

from app.store import Store


def build_admin_router(store: Store) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/admin/status")
    async def admin_status() -> dict:
        status = store.admin_status()
        status["audience_top"] = store.top_audience()
        return status

    return router