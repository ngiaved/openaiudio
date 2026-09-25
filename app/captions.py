"""Buffers de subtítulos por (sesión, idioma): parciales, segmentos finales y exportadores."""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field

MAX_SEGMENTS = 500


@dataclass
class Segment:
    seq: int
    text: str
    t0: float  # epoch seconds
    t1: float

    def to_dict(self) -> dict:
        return {"seq": self.seq, "text": self.text, "t0": self.t0, "t1": self.t1}


@dataclass
class CaptionBuffer:
    lang: str
    kind: str  # "original" | "translate"
    started_at: float = field(default_factory=time.time)
    partial: str = ""
    partial_at: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    _seq: int = 0
    errors: int = 0

    def set_partial(self, text: str) -> None:
        self.partial = text.strip()
        self.partial_at = time.time() if text else self.partial_at

    def finalize(self, text: str | None = None) -> Segment | None:
        """Cierra el segmento en curso; si text es None usa self.partial."""
        text = (text if text is not None else self.partial).strip()
        self.partial = ""
        if not text:
            return None
        now = time.time()
        self._seq += 1
        seg = Segment(seq=self._seq, text=text, t0=self.partial_at or now, t1=now)
        self.segments.append(seg)
        if len(self.segments) > MAX_SEGMENTS:
            self.segments = self.segments[-MAX_SEGMENTS:]
        return seg

    def snapshot(self) -> dict:
        return {
            "lang": self.lang,
            "kind": self.kind,
            "partial": self.partial,
            "segments": [s.to_dict() for s in self.segments],
        }

    def full_text(self) -> str:
        return "\n".join(s.text for s in self.segments)


def _fmt_srt(t: float, base: float) -> str:
    s = max(0.0, t - base)
    ms = int((s % 1) * 1000)
    s = int(s)
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_vtt(t: float, base: float) -> str:
    s = max(0.0, t - base)
    ms = int((s % 1) * 1000)
    s = int(s)
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def export_captions(buf: CaptionBuffer, fmt: str) -> str:
    """Genera subtítulos SRT, VTT o TXT a partir de los segmentos finalizados."""
    base = buf.started_at
    if fmt == "txt":
        body = "\n".join(s.text for s in buf.segments)
        return body if body else ""
    if fmt == "vtt":
        if not buf.segments:
            return "WEBVTT\n"
        lines = ["WEBVTT", ""]
        for s in buf.segments:
            lines += [f"{_fmt_vtt(s.t0, base)} --> {_fmt_vtt(s.t1, base)}", s.text, ""]
        return "\n".join(lines)
    if fmt == "srt":
        if not buf.segments:
            return ""
        lines = []
        for i, s in enumerate(buf.segments, start=1):
            lines += [str(i), f"{_fmt_srt(s.t0, base)} --> {_fmt_srt(s.t1, base)}", s.text, ""]
        return "\n".join(lines)
    raise ValueError(f"formato no soportado: {fmt}")


def feed_text(buf: CaptionBuffer, num_final: int = 4) -> str:
    """Muestra en texto plano (para OBS/vMix o verificación): últimos N finales + parcial actual."""
    tail = [f"[{s.t0:.0f}] {html.unescape(s.text)}" for s in buf.segments[-num_final:]]
    if buf.partial:
        tail.append(f"> {buf.partial}")
    return "\n".join(tail) or "… esperando audio …"