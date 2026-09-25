"""Tests de buffers de subtítulos y exportadores (SRT/VTT/TXT)."""

import time

from app.captions import CaptionBuffer, export_captions


def make_buffer() -> CaptionBuffer:
    buf = CaptionBuffer(lang="es", kind="translate")
    buf.set_partial("Esta es una transcripción")
    assert buf.finalize() is not None
    buf.set_partial("segunda oración de prueba")
    buf.finalize()
    return buf


def test_partial_and_final():
    buf = make_buffer()
    assert len(buf.segments) == 2
    assert buf.segments[0].text == "Esta es una transcripción"
    assert buf.partial == ""
    # finalize sin texto no genera segmentos
    assert buf.finalize("   ") is None
    assert len(buf.segments) == 2


def test_snapshot():
    buf = make_buffer()
    snap = buf.snapshot()
    assert snap["kind"] == "translate"
    assert len(snap["segments"]) == 2
    assert "seq" in snap["segments"][0]


def test_export_txt():
    buf = make_buffer()
    assert export_captions(buf, "txt") == "Esta es una transcripción\nsegunda oración de prueba"


def test_export_srt():
    buf = make_buffer()
    srt = export_captions(buf, "srt")
    assert srt.startswith("1\n00:00:0")
    assert srt.count("\n\n") >= 1
    assert "segunda oración de prueba" in srt


def test_export_vtt():
    buf = make_buffer()
    vtt = export_captions(buf, "vtt")
    assert vtt.startswith("WEBVTT")
    assert "-->" in vtt


def test_full_text_uses_finals_only():
    buf = make_buffer()
    buf.set_partial("no finalizado")
    assert "no finalizado" not in buf.full_text()


def test_time_based_transition():
    buf = CaptionBuffer(lang="es", kind="original")
    t0 = time.time()
    buf.set_partial("hola")
    time.sleep(0.01)
    buf.finalize()
    seg = buf.segments[0]
    assert seg.t0 >= t0
    assert seg.t1 >= seg.t0