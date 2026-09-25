"""Tests del registry de vendors: feature flags, CRUD de customs, API REST,
wiring de primario/fallback en sesiones y despacho de providers.

El fixture `clean_env` borra las keys del `.env` real (GEMINI/XAI/…) del
proceso para que los tests sean deterministas y no toquen red ni credenciales.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import CreateSessionRequest
from app.store import Store
from app.vendors import BUILTIN_IDS, VendorStore

VENDOR_ENV_KEYS = (
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "TOGETHER_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "ENABLED_VENDORS",
)


@pytest.fixture()
def clean_env(monkeypatch):
    for k in VENDOR_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.fixture()
def st(clean_env, tmp_path):
    def build(**kw):
        return Store(Settings(provider="mock", data_dir=str(tmp_path), **kw))

    return build


@pytest.fixture()
def client(clean_env, tmp_path):
    return TestClient(create_app(Settings(provider="mock", data_dir=str(tmp_path), gemini_api_key="x")))


# ------------------------------------------------------------- vendor store


def test_builtins_defaults(tmp_path):
    vs = VendorStore(tmp_path, env={"GEMINI_API_KEY": "x"})
    v = vs.get("gemini")
    assert v is not None and v.enabled and v.protocol == "gemini"
    assert len(v.api_key_masked) >= 8


def test_builtin_without_key_auto_disabled(tmp_path):
    vs = VendorStore(tmp_path, env={})
    assert vs.enabled("gemini") is None
    assert vs.enabled("mock") is not None  # mock no necesita key
    assert vs.enabled("local") is not None


def test_enabled_vendors_flag_gates_everything(tmp_path):
    vs = VendorStore(tmp_path, env={"XAI_API_KEY": "y", "OPENAI_API_KEY": "z", "ENABLED_VENDORS": "mock,openai"})
    assert vs.enabled("mock") is not None
    assert vs.enabled("openai") is not None
    assert vs.enabled("xai") is None  # fuera del flag, aunque tenga key
    assert vs.enabled("gemini") is None


def test_custom_crud_and_masking(tmp_path):
    vs = VendorStore(tmp_path)
    v = vs.create({"name": "Mi Vendedor", "base_url": "https://api.example/v1", "api_key": "sk-1234567890", "stt_model": "m1"})
    assert v.id == "mi-vendedor"
    public = v.to_public()
    assert public["api_key_masked"].startswith("sk-1")
    assert "api_key" not in public
    assert any(x.id == v.id for x in vs.all())

    # update sin key conserva la existente
    upd = vs.update(v.id, {"stt_model": "m2", "api_key": ""})
    assert upd.stt_model == "m2" and upd.api_key == "sk-1234567890"

    # update con key la reemplaza
    upd2 = vs.update(v.id, {"api_key": "sk-nueva"})
    assert upd2.api_key == "sk-nueva"

    assert vs.delete(v.id) is True
    assert vs.get(v.id) is None


# ------------------------------------------------------------- session wiring


def test_session_uses_requested_vendor_and_fallback(st):
    s = st(gemini_api_key="x").create_session(
        CreateSessionRequest(title="T", original_language="en", vendor_id="gemini", fallback_vendor_id="mock")
    )
    assert s.vendor_id == "gemini"
    assert s.fallback_vendor_id == "mock"
    assert all(t.active_vendor_id == "gemini" for t in s.targets.values())


def test_session_disabled_vendor_resolves_fallback(st):
    s = st().create_session(CreateSessionRequest(title="T", original_language="en", vendor_id="gemini"))
    assert s.vendor_id == "mock"  # sin key → gemini deshabilitado → cae a mock


def test_provider_dispatch_by_vendor(st):
    store = st(gemini_api_key="x")
    s = store.create_session(
        CreateSessionRequest(title="T", original_language="en", vendor_id="gemini", translation_mode="text")
    )
    en = s.targets["en"]
    es = s.targets["es"]
    p_orig = store._make_provider(s, en)
    p_tr = store._make_provider(s, es)
    assert p_orig.__class__.__name__ == "GeminiChunkSttProvider" or p_orig.__class__.__name__ == "GeminiProvider"
    assert p_tr.__class__.__name__ == "GeminiTextTranslateProvider"


def test_openai_compat_vendor_maps_to_openai_provider(st):
    store = st()
    store.vendors.create({"name": "Clon OpenAI", "base_url": "https://api.example/v1", "api_key": "k", "stt_model": "whisper-1"})
    s = store.create_session(
        CreateSessionRequest(title="T", original_language="en", vendor_id="clon-openai", translation_mode="text")
    )
    p = store._make_provider(s, s.targets["es"])
    assert p.__class__.__name__ == "OpenAITextTranslateProvider"


def test_switching_vendors_toggles_active(st):
    store = st(gemini_api_key="x")
    s = store.create_session(
        CreateSessionRequest(title="T", original_language="en", vendor_id="gemini", fallback_vendor_id="mock")
    )
    asyncio.run(store.switch_vendors(s.id))
    assert all(t.active_vendor_id == "mock" for t in s.targets.values())
    asyncio.run(store.switch_vendors(s.id))
    assert all(t.active_vendor_id == "gemini" for t in s.targets.values())


def test_fallback_only_on_fatal_errors(st):
    store = st(gemini_api_key="x")
    s = store.create_session(
        CreateSessionRequest(title="T", original_language="en", vendor_id="gemini", fallback_vendor_id="mock")
    )
    es = s.targets["es"]
    # transitorio → no cambia
    store._try_fallback(s, es, "429 quota agotada, retry en 30s")
    assert es.active_vendor_id == "gemini"
    # fatal → cambia
    store._try_fallback(s, es, "authentication: invalid_api_key")
    assert es.active_vendor_id == "mock"
    assert es.switched_fallback is True
    # no vuelve a cambiar
    store._try_fallback(s, es, "otro error fatal")
    assert es.active_vendor_id == "mock"


# ------------------------------------------------------------- REST API


def test_list_vendors_public(client: TestClient):
    data = client.get("/api/vendors").json()
    ids = {v["id"] for v in data["vendors"]}
    assert BUILTIN_IDS[0] in ids
    assert "api_key" not in data["vendors"][0]


def test_vendor_crud_over_api(client: TestClient):
    res = client.post(
        "/api/vendors",
        json={"name": "Mi Clúster", "base_url": "https://v.example/api/v1", "api_key": "sk-0123456789", "stt_model": "w1"},
    )
    assert res.status_code == 201
    vid = res.json()["id"]
    assert res.json()["api_key_masked"].startswith("sk-0")

    listed = client.get("/api/vendors").json()["vendors"]
    assert any(v["id"] == vid for v in listed)

    upd = client.put(f"/api/vendors/{vid}", json={"stt_model": "w2", "translate_model": "t1"})
    assert upd.status_code == 200 and upd.json()["stt_model"] == "w2"

    assert client.delete(f"/api/vendors/{vid}").status_code == 204
    assert client.get(f"/api/vendors/{vid}").status_code == 404


def test_builtin_update_only_whitelisted_fields(client: TestClient):
    res = client.put("/api/vendors/gemini", json={"stt_model": "my-model", "enabled": False, "protocol": "hacked"})
    assert res.status_code == 200
    v = res.json()
    assert v["stt_model"] == "my-model"
    assert v["enabled"] is False
    assert v["protocol"] == "gemini"  # protocol no se puede sobreescribir


def test_vendor_test_without_key_returns_400(client: TestClient):
    res = client.post("/api/vendors/xai/test")
    assert res.status_code == 400
    assert res.json()["detail"] == "el vendor no tiene api key configurada"


def test_session_with_vendor_over_api(tmp_path, clean_env):
    cs = TestClient(create_app(Settings(provider="mock", data_dir=str(tmp_path), gemini_api_key="x")))
    res = cs.post(
        "/api/sessions",
        json={"title": "T", "original_language": "en", "vendor_id": "gemini", "fallback_vendor_id": "mock"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["vendor_id"] == "gemini"
    assert body["fallback_vendor_id"] == "mock"
    sw = cs.post("/api/sessions/bogus/switch")
    assert sw.status_code == 404