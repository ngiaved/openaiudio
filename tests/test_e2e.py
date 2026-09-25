"""Pipeline end-to-end con provider mock (sin red ni API key):
broadcaster -> backend -> audiencia produce subtítulos partial/final.
"""

import json
import time

import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _noisy_chunk(n: int = 3200) -> bytes:
    return (np.random.default_rng().integers(-12000, 12000, size=n, dtype=np.int16)).tobytes()


def test_end_to_end_mock():
    app = create_app(Settings(provider="mock"))
    with TestClient(app) as client:
        res = client.post(
            "/api/sessions",
            json={"session_id": "e2e-1", "title": "E2E", "original_language": "en"},
        )
        assert res.status_code == 201
        sid = res.json()["id"]

        # --- broadcaster: conecta, saluda y manda audio ---
        with client.websocket_connect(f"/ws/ingest/{sid}") as ing:
            ing.send_text(json.dumps({"engine": "browser", "sampleRate": 16000}))
            hello = ing.receive_json()
            assert hello["type"] == "hello"
            assert set(hello["languages"]) == {"en", "es"}
            for _ in range(60):
                ing.send_bytes(_noisy_chunk())
            time.sleep(1.0)  # deja que arranque el provider mock

            # --- audiencia: sees snapshot + subtítulos parciales y finales ---
            with client.websocket_connect(f"/ws/audience/{sid}?lang=es") as aud:
                snap = aud.receive_json()
                assert snap["type"] == "snapshot"
                assert snap["lang"] == "es"
                assert snap["kind"] == "translate"

                seen = {"partial": False, "final": False}
                deadline = time.time() + 12
                while time.time() < deadline and not (seen["partial"] and seen["final"]):
                    msg = aud.receive_json()
                    if msg["type"] == "caption":
                        seen[msg["kind"]] = True
                    elif msg["type"] == "state":
                        assert msg["state"] in ("live", "warming", "error", "idle")

                assert seen["partial"], "debería llegar un subtítulo parcial"
                assert seen["final"], "debería llegar un subtítulo final"

        # el export debería tener al menos un segmento ahora
        txt = client.get("/api/sessions/e2e-1/export", params={"lang": "es", "fmt": "txt"})
        assert txt.status_code == 200
        assert txt.text.strip() != ""


def test_audience_unknown_session_closed():
    app = create_app(Settings(provider="mock"))
    raised = False
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/ws/audience/nope?lang=es") as ws:
                ws.receive_json()
        except Exception:  # noqa: BLE001 - el servidor cierra 4404 antes de aceptar
            raised = True
    assert raised