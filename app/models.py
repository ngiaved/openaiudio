"""Modelos de API (Pydantic)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProviderKind = Literal["gemini", "local", "mock"]
TargetKind = Literal["original", "translate"]


def slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug[:48] or "sesion"


class TargetSpec(BaseModel):
    lang: str = Field(min_length=2, max_length=8)
    kind: TargetKind = "translate"
    via: Literal["audio", "text"] | None = None  # cómo se genera la traducción

    @field_validator("lang")
    @classmethod
    def _norm_lang(cls, v: str) -> str:
        return v.strip().lower()


class GlossaryEntry(BaseModel):
    source: str
    target: str | None = None  # si no hay target, solo se respeta el término tal cual
    context: str | None = None


class CreateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    stage: str | None = Field(default=None, max_length=100)
    session_id: str | None = Field(default=None, max_length=48, pattern=r"^[a-z0-9-]+$")
    original_language: str = "en"
    targets: list[TargetSpec] | None = None
    provider: ProviderKind | None = None
    translation_mode: Literal["audio", "text", "auto"] | None = None
    glossary: list[GlossaryEntry] = []
    vendor_id: str | None = Field(default=None, max_length=64, description="Vendor primario (id del registro)")
    fallback_vendor_id: str | None = Field(default=None, max_length=64, description="Vendor de respaldo")
    stt_model: str | None = Field(default=None, max_length=120, description="Override de modelo STT para el vendor primario")
    translate_model: str | None = Field(default=None, max_length=120, description="Override de modelo de traducción (vendor primario)")
    fallback_stt_model: str | None = Field(default=None, max_length=120)
    fallback_translate_model: str | None = Field(default=None, max_length=120)

    @field_validator("original_language")
    @classmethod
    def _norm_orig(cls, v: str) -> str:
        return v.strip().lower()


class VendorSpec(BaseModel):
    """Create/update de un vendor custom (o overrides de un built-in)."""
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(default="", max_length=80)
    protocol: str = "openai"
    base_url: str = Field(default="", max_length=300)
    api_key: str = Field(default="", max_length=400)
    supports_stt: bool = True
    supports_translate: bool = True
    stt_mode: Literal["whisper", "inline_audio", "windowed", "none"] = "whisper"
    stt_model: str = Field(default="", max_length=120)
    translate_model: str = Field(default="", max_length=120)
    live_model: str = Field(default="", max_length=120)
    enabled: bool = True
    azure_endpoint: str = Field(default="", max_length=300)


class SetGlossaryRequest(BaseModel):
    glossary: list[GlossaryEntry]


class ExporterOut(BaseModel):
    session_id: str
    lang: str
    fmt: str
    text: str