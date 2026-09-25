"""Tests de la API REST de sesiones (create/list/get/delete/glossary/export) y del modo híbrido."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import CreateSessionRequest
from app.store import Store


@pytest.fixture()
def client():
    return TestClient(create_app(Settings(provider="mock")))


def test_create_and_get(client: TestClient):
    res = client.post(
        "/api/sessions",
        json={
            "session_id": "demo-1",
            "title": "Keynote",
            "stage": "Escenario A",
            "original_language": "en",
        },
    )
    assert res.status_code == 201
    s = res.json()
    assert s["id"] == "demo-1"
    assert s["provider"] == "mock"
    langs = {l["lang"] for l in s["languages"]}
    assert langs == {"en", "es"}  # original en + español por defecto
    assert s["languages"][0]["is_original"] is True or any(l["is_original"] for l in s["languages"])

    detail = client.get("/api/sessions/demo-1")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Keynote"


def test_list_empty(client: TestClient):
    data = client.get("/api/sessions").json()
    assert data["sessions"] == []


def test_missing_returns_404(client: TestClient):
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.delete("/api/sessions/nope").status_code == 404


def test_glossary(client: TestClient):
    client.post("/api/sessions", json={"session_id": "g-1", "title": "T", "original_language": "en"})
    res = client.post(
        "/api/sessions/g-1/glossary",
        json={"glossary": [{"source": "Kubernetes", "target": "Kubernetes", "context": "orquestador"}]},
    )
    assert res.status_code == 200
    assert res.json()["glossary"][0]["source"] == "Kubernetes"


def test_export_empty_and_srt(client: TestClient):
    client.post("/api/sessions", json={"session_id": "x-1", "title": "T", "original_language": "en"})
    r = client.get("/api/sessions/x-1/export", params={"lang": "es", "fmt": "txt"})
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('x-1.es.txt"')
    assert client.get("/api/sessions/x-1/export", params={"lang": "es", "fmt": "bad"}).status_code == 400


def test_delete(client: TestClient):
    client.post("/api/sessions", json={"session_id": "d-1", "title": "T"})
    assert client.delete("/api/sessions/d-1").status_code == 204
    assert client.get("/api/sessions/d-1").status_code == 404


def test_max_sessions():
    st = Store(Settings(provider="mock", max_sessions=2))
    st.create_session(CreateSessionRequest(title="A", session_id="a-1"))
    st.create_session(CreateSessionRequest(title="B", session_id="b-1"))
    with pytest.raises(ValueError):
        st.create_session(CreateSessionRequest(title="C", session_id="c-1"))


def test_hybrid_via_by_translation_mode():
    """Topología C: original siempre por audio; traducción por texto o audio según el modo."""
    st = Store(Settings(provider="mock"))
    text = st.create_session(
        CreateSessionRequest(
            title="T",
            original_language="en",
            provider="gemini",
            translation_mode="text",
            targets=[{"lang": "es", "kind": "translate"}, {"lang": "pt", "kind": "translate"}],
        )
    )
    assert text.targets["en"].kind == "original"
    assert text.targets["en"].via == "audio"
    assert text.targets["es"].via == "text"
    assert text.targets["pt"].via == "text"
    assert text.targets["es"].uses_audio is False
    assert text.targets["es"].uses_text is True

    audio = st.create_session(
        CreateSessionRequest(title="T2", original_language="en", provider="gemini", translation_mode="audio")
    )
    assert audio.targets["es"].via == "audio"
    assert audio.targets["es"].uses_audio is True


def test_healthz(client: TestClient):
    assert client.get("/healthz").json()["ok"] is True


def test_text_translate_provider_starts_lazily_from_original_final():
    """Un traductor por texto no recibe audio: debe arrancar a demanda cuando llega
    el primer final del original, sin perder el texto que venía antes de estar vivo."""
    import asyncio

    st = Store(Settings(provider="gemini", gemini_api_key="x"))
    session = st.create_session(
        CreateSessionRequest(
            title="T",
            original_language="en",
            provider="gemini",
            translation_mode="text",
        )
    )
    es = session.targets["es"]
    assert es.uses_text is True
    assert es.provider is None  # aún no hay texto → no arrancó

    async def run():
        st.push_caption(session.id, "en", "original", "Hello there.")
        await asyncio.sleep(0.2)
        return es

    es = asyncio.run(run())
    assert es.provider is not None  # arrancó de forma diferida
    assert es.state in ("live", "warming")
    assert es.stash == []  # el texto pendiente ya se drenó al provider