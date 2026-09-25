"""Tests del broadcaster headless (scripts/broadcast_cli.py)."""

import importlib.util
import wave
from pathlib import Path

import numpy as np
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "broadcast_cli.py"


@pytest.fixture(scope="module")
def cli():
    spec = importlib.util.spec_from_file_location("broadcast_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wav(path: Path, frames: np.ndarray, rate: int, channels: int) -> Path:
    data = frames.astype("<i2")
    if channels == 1:
        body = data.tobytes()
    else:
        body = np.repeat(data[:, None], channels, axis=1).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(body)
    return path


def test_wav_once_reads_every_frame(tmp_path, cli):
    frames = np.arange(0, 4000, dtype=np.int16)
    path = _wav(tmp_path / "a.wav", frames, 16000, 1)
    src = cli.WavSource(str(path), chunk_sec=0.1, loop=False)
    out = b""
    while True:
        chunk = src.read()
        if chunk is None:
            break
        out += chunk
    src.close()
    assert len(out) == len(frames) * 2
    assert np.frombuffer(out, dtype="<i2").tolist() == frames.tolist()


def test_wav_loop_rewinds(tmp_path, cli):
    frames = np.array([1000, 2000, 3000], dtype=np.int16)
    path = _wav(tmp_path / "b.wav", frames, 16000, 1)
    src = cli.WavSource(str(path), chunk_sec=0.05, loop=True)
    # en modo loop nunca devuelve None: leemos varias pasadas y cada una
    # debe rebobinar y repetir el archivo completo
    for _ in range(4):
        got = b""
        while len(got) < len(frames) * 2:
            chunk = src.read()
            assert chunk is not None
            got += chunk
        assert got == frames.tobytes()
    src.close()


def test_wav_stereo_downmixed_to_mono(tmp_path, cli):
    mono = np.array([1000, -2000], dtype=np.int16)
    path = _wav(tmp_path / "c.wav", mono, 16000, 2)  # ambos canales = mono
    src = cli.WavSource(str(path), chunk_sec=0.05, loop=True)
    out = src.read()
    src.close()
    assert out is not None
    got = np.frombuffer(out, dtype="<i2").reshape(-1, 1).ravel()
    assert got.tolist() == mono.tolist()