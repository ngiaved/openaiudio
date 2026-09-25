"""API de vendors: listado, CRUD de vendors custom y prueba de conexión.

Los vendors agrupan proveedores de modelos con capabilities (STT/translation).
Los built-in se encienden/apagan vía el flag `ENABLED_VENDORS` de config; los
custom se configuran 100 % desde esta API (y la GUI de /vendors).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.models import VendorSpec
from app.store import Store
from app.vendors import BUILTIN_IDS, VendorStore

log = logging.getLogger("openaiudio.vendors")


def build_vendors_router(store: Store) -> APIRouter:
    router = APIRouter(prefix="/api")
    vendors: VendorStore = store.vendors

    @router.get("/vendors")
    async def list_vendors() -> dict:
        return {"vendors": [v.to_public() for v in vendors.all()]}

    @router.get("/vendors/{vendor_id}")
    async def get_vendor(vendor_id: str) -> dict:
        v = vendors.get(vendor_id)
        if v is None:
            raise HTTPException(status_code=404, detail="vendor no encontrado")
        return v.to_public()

    @router.post("/vendors", status_code=201)
    async def create_vendor(req: VendorSpec) -> dict:
        if not (req.name or "").strip():
            raise HTTPException(status_code=422, detail="name es requerido para un vendor custom")
        v = vendors.create(req.model_dump())
        if v is None:
            raise HTTPException(status_code=400, detail="no se pudo crear el vendor")
        return v.to_public()

    @router.put("/vendors/{vendor_id}")
    async def update_vendor(vendor_id: str, req: VendorSpec) -> dict:
        payload = req.model_dump(exclude_unset=True)
        if vendor_id in BUILTIN_IDS:
            # solo se permiten overrides: modelos, base_url, enabled (la key sale del env)
            overrides = {k: payload[k] for k in ("stt_model", "translate_model", "live_model", "enabled", "base_url") if k in payload}
            vendors.persist_builtin_overrides(vendor_id, overrides)
            v = vendors.get(vendor_id)
            return v.to_public() if v else HTTPException(status_code=404, detail="vendor no encontrado")
        v = vendors.update(vendor_id, {k: payload[k] for k in payload if k != "id"})
        if v is None:
            raise HTTPException(status_code=404, detail="vendor no encontrado")
        return v.to_public()

    @router.delete("/vendors/{vendor_id}", status_code=204)
    async def delete_vendor(vendor_id: str) -> None:
        if vendor_id in BUILTIN_IDS:
            raise HTTPException(status_code=400, detail="no se puede borrar un vendor built-in")
        if not vendors.delete(vendor_id):
            raise HTTPException(status_code=404, detail="vendor no encontrado")

    @router.post("/vendors/{vendor_id}/test")
    async def test_vendor(vendor_id: str) -> dict:
        v = vendors.get(vendor_id)
        if v is None:
            raise HTTPException(status_code=404, detail="vendor no encontrado")
        if not v.has_api_key:
            raise HTTPException(status_code=400, detail="el vendor no tiene api key configurada")
        ok, detail = await _probe(v)
        return {"ok": ok, "vendor": v.id, "detail": detail}

    return router


async def _probe(v) -> tuple[bool, str]:
    """Validación de credenciales/endpoint sin transmitir. No toca quota de STT."""
    try:
        if v.protocol == "gemini":
            from google import genai

            client = genai.Client(api_key=v.api_key)
            await asyncio.wait_for(client.aio.models.list(config={"page_size": 1}), timeout=10)
            return True, "Gemini ok"
        if v.protocol == "anthropic":
            import httpx

            url = f"{v.base_url.rstrip('/')}/models"
            resp = await asyncio.wait_for(
                httpx.AsyncClient(timeout=10).get(
                    url, headers={"x-api-key": v.api_key, "anthropic-version": "2023-06-01"}
                ),
                timeout=12,
            )
            return resp.status_code < 400, f"HTTP {resp.status_code}"
        import httpx

        url = f"{v.base_url.rstrip('/')}/models" if v.base_url else ""
        if not url:
            return False, "base_url vacío (configurá el endpoint del vendor)"
        resp = await asyncio.wait_for(httpx.AsyncClient(timeout=10).get(url, headers={"Authorization": f"Bearer {v.api_key}"}), timeout=12)
        if resp.status_code == 200:
            return True, "API ok"
        return False, f"HTTP {resp.status_code}: {resp.text[:160]}"
    except asyncio.TimeoutError:
        return False, "timeout al conectar"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:160]