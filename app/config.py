"""Configuración del servidor desde variables de entorno (sin dependencias externas)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_env_file(path: str = ".env") -> None:
    """Carga `.env` al entorno si existe (las variables ya seteadas ganan).

    Se prueba el path tal cual está (CWD de uvicorn) y también la raíz del repo
    aunque el servidor se levante desde otro directorio.
    """
    candidates = [path, str(Path(__file__).resolve().parent.parent / ".env")]
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value.strip().strip("\"'")
        except OSError:
            continue
        break  # primer archivo válido que exista


_load_env_file()

AUDIO_RATE = 16_000  # PCM mono 16 kHz, little-endian (formato de Gemini Live).

# Nombres cortos (BCP-47) -> nombre legible para la UI.
LANGUAGES: dict[str, str] = {
    "es": "Español",
    "en": "English",
    "pt": "Português",
    "de": "Deutsch",
    "fr": "Français",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文",
    "ru": "Русский",
    "ar": "العربية",
    "hi": "हिन्दी",
    "other": "Otro / Other",
}

PROVIDERS = ("auto", "gemini", "local", "mock")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"))
    gemini_text_model: str = field(default_factory=lambda: os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.8-flash"))
    gemini_live_model: str = field(default_factory=lambda: os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.5-transcribe-live"))
    stt_window_sec: float = field(default_factory=lambda: float(os.environ.get("STT_WINDOW_SEC", "6.5")))
    stt_step_sec: float = field(default_factory=lambda: float(os.environ.get("STT_STEP_SEC", "5.0")))
    stt_min_energy_db: float = field(default_factory=lambda: float(os.environ.get("STT_MIN_ENERGY_DB", "-60")))
    stt_timeout_sec: float = field(default_factory=lambda: float(os.environ.get("STT_TIMEOUT_SEC", "60")))
    provider: str = field(default_factory=lambda: os.environ.get("PROVIDER", "auto").strip().lower())
    enabled_vendors: str = field(default_factory=lambda: os.environ.get("ENABLED_VENDORS", "").strip())
    translation_mode: str = field(default_factory=lambda: os.environ.get("TRANSLATION_MODE", "auto").strip().lower())
    max_providers: int = field(default_factory=lambda: int(os.environ.get("MAX_PROVIDERS", "80")))
    max_sessions: int = field(default_factory=lambda: int(os.environ.get("MAX_SESSIONS", "64")))
    idle_timeout_sec: float = field(default_factory=lambda: float(os.environ.get("IDLE_TIMEOUT_SEC", "180")))
    obs_out_dir: str = field(default_factory=lambda: os.environ.get("OBS_OUT_DIR", "").strip())
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", "data").strip() or "data")
    whisper_model: str = field(default_factory=lambda: os.environ.get("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: os.environ.get("WHISPER_DEVICE", "auto"))
    ollama_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "gemma3:4b"))
    audio_chunk_sec: float = field(default_factory=lambda: float(os.environ.get("AUDIO_CHUNK_SEC", "0.25")))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", "8000")))

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"PROVIDER debe ser uno de {PROVIDERS}")
        if self.translation_mode not in ("audio", "text", "auto"):
            raise ValueError("TRANSLATION_MODE debe ser audio | text | auto")

    @property
    def effective_provider(self) -> str:
        """'auto': Gemini si hay clave, si no mock (demo sin red / sin costo)."""
        if self.provider != "auto":
            return self.provider
        return "gemini" if self.gemini_api_key else "mock"


def default_targets(original_lang: str) -> list[dict[str, str]]:
    """Idiomas por defecto: siempre español; y si hay speaker en español, también inglés."""
    targets = [{"lang": "es"}]
    if original_lang == "es":
        targets.append({"lang": "en"})
    return targets


def lang_name(lang: str) -> str:
    return LANGUAGES.get(lang, lang)


settings = Settings()