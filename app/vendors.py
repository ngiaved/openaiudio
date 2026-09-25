"""Vendor registry: model providers behind config feature flags.

Every provider ("vendor") that can generate captions or translations is listed
here with capability flags. Operators enable/disable whole vendors through the
single `ENABLED_VENDORS` config flag (a comma-separated list of vendor ids).
Custom vendors (fully configured from the GUI) are persisted to
`data/vendors.json` and participate in the same flag.

Built-in vendors:
  um, gemini, xai, openai, anthropic, groq, mistral, deepseek, together,
  openrouter, azure_openai, local, mock.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("openaiudio.vendors")

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# protocol: gemini | openai | anthropic | azure | local | mock
# stt_mode: windowed | whisper | inline_audio | local | mock | none
BUILTIN_SPECS: list[dict] = [
    {
        "id": "gemini",
        "name": "Gemini (Google)",
        "protocol": "gemini",
        "base_url": "",
        "env_key": "GEMINI_API_KEY",
        "stt_model": "gemini-3.8-flash",
        "translate_model": "gemini-3.8-flash",
        "live_model": "gemini-3.5-transcribe-live",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "windowed",
    },
    {
        "id": "xai",
        "name": "xAI Grok",
        "protocol": "openai",
        "base_url": "https://api.x.ai/v1",
        "env_key": "XAI_API_KEY",
        "stt_model": "",
        "translate_model": "grok-3",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "inline_audio",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "stt_model": "whisper-1",
        "translate_model": "gpt-4o-mini",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "whisper",
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "stt_model": "",
        "translate_model": "claude-3-5-haiku-latest",
        "supports_stt": False,
        "supports_translate": True,
        "stt_mode": "none",
    },
    {
        "id": "groq",
        "name": "Groq",
        "protocol": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "stt_model": "whisper-large-v3-turbo",
        "translate_model": "llama-3.3-70b-versatile",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "whisper",
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "protocol": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY",
        "stt_model": "",
        "translate_model": "mistral-small-latest",
        "supports_stt": False,
        "supports_translate": True,
        "stt_mode": "none",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "stt_model": "",
        "translate_model": "deepseek-chat",
        "supports_stt": False,
        "supports_translate": True,
        "stt_mode": "none",
    },
    {
        "id": "together",
        "name": "Together AI",
        "protocol": "openai",
        "base_url": "https://api.together.xyz/v1",
        "env_key": "TOGETHER_API_KEY",
        "stt_model": "whisper-1",
        "translate_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "whisper",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "stt_model": "",
        "translate_model": "openai/gpt-4o-mini",
        "supports_stt": False,
        "supports_translate": True,
        "stt_mode": "none",
    },
    {
        "id": "azure_openai",
        "name": "Azure OpenAI",
        "protocol": "azure",
        "base_url": "",  # AZURE_OPENAI_ENDPOINT, e.g. https://<res>.openai.azure.com/openai/deployments
        "env_key": "AZURE_OPENAI_API_KEY",
        "stt_model": "whisper",
        "translate_model": "gpt-4o-mini",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "whisper",
    },
    {
        "id": "local",
        "name": "Local (whisper + Ollama)",
        "protocol": "local",
        "base_url": "",
        "env_key": "",
        "stt_model": "small",
        "translate_model": "gemma3:4b",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "local",
    },
    {
        "id": "mock",
        "name": "Mock (demo)",
        "protocol": "mock",
        "base_url": "",
        "env_key": "",
        "stt_model": "mock",
        "translate_model": "mock",
        "supports_stt": True,
        "supports_translate": True,
        "stt_mode": "mock",
    },
]

BUILTIN_IDS = [s["id"] for s in BUILTIN_SPECS]
DEFAULT_ENABLED = ",".join(BUILTIN_IDS)


def enabled_ids_from(env: dict | None = None) -> set[str] | None:
    """Feature flag: 'ENABLED_VENDORS' (comma list). None => everything on."""
    raw = (env if env is not None else os.environ).get("ENABLED_VENDORS", "").strip()
    if not raw:
        return None
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def enabled_ids() -> set[str] | None:
    return enabled_ids_from()


@dataclass
class Vendor:
    id: str
    name: str
    protocol: str  # gemini | openai | anthropic | azure | local | mock
    base_url: str = ""
    api_key: str = ""
    stt_model: str = ""
    translate_model: str = ""
    live_model: str = ""
    supports_stt: bool = True
    supports_translate: bool = True
    stt_mode: str = "none"  # windowed | whisper | inline_audio | local | mock | none
    enabled: bool = True
    builtin: bool = True
    env_key: str = ""
    extra: dict = field(default_factory=dict)  # azure endpoint, etc.

    @property
    def has_api_key(self) -> bool:
        key_req = self.protocol not in ("local", "mock")
        return (not key_req) or bool(self.api_key)

    @property
    def api_key_masked(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "••••••••"
        return self.api_key[:4] + "…" + self.api_key[-4:]

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "builtin": self.builtin,
            "enabled": self.enabled,
            "has_api_key": self.has_api_key,
            "api_key_masked": self.api_key_masked,
            "base_url": self.base_url,
            "stt_model": self.stt_model,
            "translate_model": self.translate_model,
            "live_model": self.live_model,
            "supports_stt": self.supports_stt,
            "supports_translate": self.supports_translate,
            "stt_mode": self.stt_mode,
            "azure_endpoint": self.extra.get("azure_endpoint", ""),
        }


class VendorStore:
    """Built-in vendors (from env) + custom vendors persisted in data/vendors.json."""

    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR, env: dict | None = None) -> None:
        self.data_dir = Path(data_dir)
        self._env = env if env is not None else os.environ
        self._flag = enabled_ids_from(self._env)
        self._lock = threading.Lock()
        self._customs: dict[str, dict] = {}
        self._builtin_overrides: dict[str, dict] = {}
        self._data_file = self.data_dir / "vendors.json"
        self.load()

    # ------------------------------------------------------------- loading
    def load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            with open(self._data_file, encoding="utf-8") as fh:
                payload = json.load(fh)
            self._customs = {str(v["id"]): v for v in payload.get("customs", [])}
            self._builtin_overrides = {str(k): v for k, v in payload.get("builtin_overrides", {}).items()}
        except (OSError, ValueError, KeyError) as exc:
            log.warning("no se pudo leer %s: %s", self._data_file, exc)

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {"customs": list(self._customs.values()), "builtin_overrides": self._builtin_overrides}
        tmp = self._data_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        try:
            tmp.replace(self._data_file)
        except OSError:
            self._data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # -------------------------------------------------------------- build
    def _builtin(self, spec: dict) -> Vendor:
        env_key = spec.get("env_key", "")
        api_key = self._env.get(env_key, "").strip() if env_key else ""
        azure_endpoint = self._env.get("AZURE_OPENAI_ENDPOINT", "").strip()
        ov = self._builtin_overrides.get(spec["id"], {})
        return Vendor(
            id=spec["id"],
            name=spec["name"],
            protocol=spec["protocol"],
            base_url=ov.get("base_url", spec.get("base_url", "")),
            api_key=api_key,
            stt_model=ov.get("stt_model", spec.get("stt_model", "")),
            translate_model=ov.get("translate_model", spec.get("translate_model", "")),
            live_model=ov.get("live_model", spec.get("live_model", "")),
            supports_stt=spec.get("supports_stt", True),
            supports_translate=spec.get("supports_translate", True),
            stt_mode=spec.get("stt_mode", "none"),
            enabled=bool(ov.get("enabled", True)),
            builtin=True,
            env_key=env_key,
            extra={"azure_endpoint": azure_endpoint} if spec["id"] == "azure_openai" else {},
        )

    def _custom(self, raw: dict) -> Vendor | None:
        vid = str(raw.get("id", "")).strip()
        if not vid:
            return None
        return Vendor(
            id=vid,
            name=str(raw.get("name", vid)),
            protocol="openai" if raw.get("protocol") in ("openai", "azure") else str(raw.get("protocol", "openai")),
            base_url=str(raw.get("base_url", "")).strip(),
            api_key=str(raw.get("api_key", "")).strip(),
            stt_model=str(raw.get("stt_model", "")).strip(),
            translate_model=str(raw.get("translate_model", "")).strip(),
            live_model=str(raw.get("live_model", "")).strip(),
            supports_stt=bool(raw.get("supports_stt", True)),
            supports_translate=bool(raw.get("supports_translate", True)),
            stt_mode=str(raw.get("stt_mode", "whisper")),
            enabled=bool(raw.get("enabled", True)),
            builtin=False,
            env_key="",
            extra={"azure_endpoint": str(raw.get("azure_endpoint", "")).strip()},
        )

    # -------------------------------------------------------------- public
    def all(self) -> list[Vendor]:
        allow = self._flag
        out: list[Vendor] = []
        for spec in BUILTIN_SPECS:
            v = self._builtin(spec)
            out.append(v)
        for raw in self._customs.values():
            v = self._custom(raw)
            if v is not None:
                out.append(v)
        for v in out:
            if allow is not None:
                v.enabled = v.id in allow and v.has_api_key
            elif not v.has_api_key:
                v.enabled = False  # sin clave no es usable
        return out

    def get(self, vendor_id: str) -> Vendor | None:
        for v in self.all():
            if v.id == vendor_id:
                return v
        return None

    def enabled(self, vendor_id: str) -> Vendor | None:
        v = self.get(vendor_id)
        return v if v is not None and v.enabled else None

    # -------------------------------------------------------------- custom CRUD
    def create(self, spec: dict) -> Vendor | None:
        vid = str(spec.get("id", "")).strip().lower() or None
        if vid is None:
            base = slugify_vendor(str(spec.get("name", "custom")))
            vid, n = base, 1
            while vid in self._customs or vid in BUILTIN_IDS:
                n += 1
                vid = f"{base}-{n}"
        spec = {"id": vid, **spec, "id": vid}
        with self._lock:
            self._customs[vid] = spec
            self.save()
        return self._custom(self._customs[vid])

    def update(self, vendor_id: str, spec: dict) -> Vendor | None:
        with self._lock:
            if vendor_id not in self._customs:
                return None
            merged = {**self._customs[vendor_id], **spec, "id": vendor_id}
            if spec.get("api_key") in ("", None):
                merged.pop("api_key", None)
                merged.setdefault("api_key", self._customs[vendor_id].get("api_key", ""))
            self._customs[vendor_id] = merged
            self.save()
        return self._custom(self._customs[vendor_id])

    def delete(self, vendor_id: str) -> bool:
        with self._lock:
            removed = self._customs.pop(vendor_id, None) is not None
            if removed:
                self.save()
        return removed

    def persist_builtin_overrides(self, vendor_id: str, overrides: dict) -> None:
        if vendor_id not in BUILTIN_IDS:
            return
        allowed = ("stt_model", "translate_model", "live_model", "enabled", "base_url")
        with self._lock:
            merged = {**self._builtin_overrides.get(vendor_id, {}), **{k: v for k, v in overrides.items() if k in allowed}}
            if merged:
                self._builtin_overrides[vendor_id] = merged
            else:
                self._builtin_overrides.pop(vendor_id, None)
            self.save()


def slugify_vendor(raw: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug[:40] or "custom"