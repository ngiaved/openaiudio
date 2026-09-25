#!/usr/bin/env python3
"""Headless broadcaster for OpenAIudio.

Replicates what the /broadcast web page does, from the command line:
create/reuse a session over REST and stream PCM audio over /ws/ingest.
Useful to run several broadcasters from plain bash (one per computer/sala)
against a shared server, or to rehearse a talk from a local file.

Sources
    --src mic[:<device-index>]   microphone (needs the [cli] extra)
    --src path/to/audio.wav      PCM16 WAV file, played in a loop (--once to stop)

The WAV keeps its native sample rate/channels; the server resamples to
16 kHz mono PCM16 (same contract the browser uses).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import queue
import sys
import wave

import httpx
import websockets

from app.config import AUDIO_RATE

INGEST_PATH = "/ws/ingest/{sid}"


# --------------------------------------------------------------------------- sources
class WavSource:
    """Reads a PCM16 WAV, downmixes to mono, keeps native rate."""

    def __init__(self, path: str, chunk_sec: float, loop: bool) -> None:
        self.path = path
        self.loop = loop
        self.wav = wave.open(path, "rb")
        if self.wav.getsampwidth() != 2:
            raise ValueError(f"{path}: solo se soporta PCM16 (sampwidth={self.wav.getsampwidth()})")
        self.rate = self.wav.getframerate()
        self.channels = self.wav.getnchannels()
        self.chunk = max(1, int(self.rate * chunk_sec))
        self.frames_left = self.wav.getnframes()
        self.is_mic = False

    def read(self) -> bytes | None:
        while True:
            if self.frames_left <= 0:
                if not self.loop:
                    return None
                self.wav.rewind()
                self.frames_left = self.wav.getnframes()
            n = min(self.chunk, self.frames_left)
            data = self.wav.readframes(n)
            self.frames_left -= n
            if not data:
                return None
            if self.channels == 1:
                return data
            import numpy as np

            arr = np.frombuffer(data, dtype="<i2").reshape(-1, self.channels)
            return arr.mean(axis=1).astype("<i2").tobytes()

    def close(self) -> None:
        self.wav.close()


class MicSource:
    """Microphone via sounddevice (pip install -e '.[cli]')."""

    def __init__(self, device: str | None, chunk_sec: float) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            sys.exit("fuente 'mic' requiere el extra [cli]: pip install -e '.[cli]'")
        dev_index = None if not device else int(device)
        self.sd = sd
        self.index = dev_index if dev_index is not None else sd.default.device[0]
        info = sd.query_devices(self.index, "input")
        self.rate = int(info["default_samplerate"])
        self.q: queue.Queue = queue.Queue(maxsize=64)
        self.is_mic = True
        self.stream = sd.InputStream(
            device=self.index,
            channels=1,
            samplerate=self.rate,
            dtype="int16",
            blocksize=int(self.rate * chunk_sec),
            callback=self._cb,
        )

    def _cb(self, indata, _frames, _time, _status) -> None:  # noqa: ANN001
        try:
            self.q.put_nowait(indata.copy())
        except queue.Full:
            pass

    def start(self) -> None:
        self.stream.start()

    def read(self) -> bytes | None:
        try:
            return self.q.get_nowait().tobytes()
        except queue.Empty:
            return None

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


# --------------------------------------------------------------------------- session
def create_session(server: str, args) -> dict:
    payload = {
        "title": args.title,
        "stage": args.stage,
        "original_language": args.original_lang,
        "targets": [{"lang": ln.strip(), "kind": "translate"} for ln in args.langs.split(",") if ln.strip()],
        "provider": None,
        "translation_mode": args.translation_mode,
        "vendor_id": args.vendor or None,
        "fallback_vendor_id": args.fallback or None,
    }
    res = httpx.post(f"{server}/api/sessions", json=payload, timeout=15.0)
    res.raise_for_status()
    return res.json()


# --------------------------------------------------------------------------- stream
def ingest_url(server: str, sid: str) -> str:
    return server.replace("http://", "ws://").replace("https://", "wss://") + INGEST_PATH.format(sid=sid)


async def run_stream(server: str, sid: str, source, rate: int, chunk_sec: float) -> None:
    ws_url = ingest_url(server, sid)
    async with websockets.connect(ws_url, ping_interval=None, max_size=2 ** 22) as ws:
        await ws.send(json.dumps({"engine": "cli", "sampleRate": rate}))
        print(f"\n✓ transmitiendo a {ws_url}")
        print(f"  session: {sid} · sample_rate: {rate} · Ctrl+C para detener\n", flush=True)
        try:
            while True:
                chunk = source.read()
                if chunk is None:  # fin del archivo (--once)
                    print("fin del archivo alcanzado", flush=True)
                    break
                if chunk:
                    await ws.send(chunk)
                    if not getattr(source, "is_mic", False):
                        # pace real-time: durmiendo lo que duró el chunk de audio
                        await asyncio.sleep(max(0.01, len(chunk) / 2 / rate))
                else:
                    await asyncio.sleep(0.01)  # mic sin datos disponibles
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            try:
                await ws.send(json.dumps({"type": "control", "cmd": "stop"}))
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.2)


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="broadcast_cli",
        description="Broadcaster headless: crea una sesión y transmite audio a un servidor openaiudio.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="URL base del servidor")
    parser.add_argument("--title", default="cli", help="Título de la sesión (sluggable -> id)")
    parser.add_argument("--stage", default="", help="Escenario / sala (opcional)")
    parser.add_argument("--original-lang", default="es", help="Idioma original del orador")
    parser.add_argument("--langs", default="es", help="Traducciones, separadas por coma (ej. es,en,pt)")
    parser.add_argument("--vendor", default="", help="Vendor primario (id del registro, ej. gemini)")
    parser.add_argument("--fallback", default="", help="Vendor de respaldo (id)")
    parser.add_argument("--translation-mode", default="text", choices=["audio", "text", "auto"])
    parser.add_argument("--src", default="mic", help="'mic[:<índice>]' o ruta a un WAV PCM16")
    parser.add_argument("--chunk-sec", type=float, default=0.25, help="Tamaño de chunk al enviar (segundos)")
    parser.add_argument("--once", action="store_true", help="Para WAV: reproducir una sola vez (por defecto loop)")
    args = parser.parse_args(argv)

    if args.src == "mic" or args.src.startswith("mic:"):
        source = MicSource(args.src[4:] if args.src != "mic" else None, args.chunk_sec)
        source.start()
    else:
        source = WavSource(args.src, args.chunk_sec, loop=not args.once)
    rate = getattr(source, "rate", AUDIO_RATE)

    try:
        session = create_session(args.server, args)
        langs = ", ".join(l["lang"] for l in session["languages"])
        fb = f" / fallback {session['fallback_vendor_id']}" if session.get("fallback_vendor_id") else ""
        print(
            f"sesión creada: {session['id']} (original={session['original_language']}, "
            f"idiomas={langs}, vendor={session['vendor_id']}{fb})"
        )
        asyncio.run(run_stream(args.server, session["id"], source, rate, args.chunk_sec))
    except httpx.HTTPStatusError as exc:
        print(f"error creando sesión ({exc.response.status_code}): {exc.response.text[:300]}", file=sys.stderr)
        return 1
    except websockets.exceptions.ConnectionClosed as exc:
        print(f"conexión cerrada: {exc}", file=sys.stderr)
        return 1
    finally:
        source.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())