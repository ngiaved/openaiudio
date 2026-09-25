# HOWTO: Run the fully-local pipeline (Whisper + LLM)

This guide explains how to run OpenAIudio **completely on your own machine**
(macOS, Linux or Windows) with **no cloud API**: speech-to-text with a local
**Whisper** model (`faster-whisper`) and simultaneous translation with a local
language model via **Ollama** (e.g. `gemma3:4b`).

> Cloud vendors are always optional. With no API key at all, either
> `PROVIDER=auto` (falls back to `mock`) or the `local` routing below let you
> run the whole flow offline for free.

## How the local puzzle fits together

The local path uses two pieces that run on the same (or nearby) machine:

| Stage | Meaning | Component | Route in `app/` |
| --- | --- | --- | --- |
| Original (STT) | Turns the transcribed audio into text | `faster-whisper` (Whisper model, e.g. `small`) | `LocalWhisperProvider` (`app/providers/local.py`) |
| Translation | Translates the original's text per language | Ollama + an LLM (e.g. `gemma3:4b`) | `OllamaTranslateProvider` (`app/providers/local.py`) |

Translations are fed by the **final text** of the original captions (`via:
text`), so no cloud request is ever made.

## 1) Install the backend + the local extra

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[local]"
```

On **Windows** the commands are:

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[local]"
```

The `.[local]` extra installs `faster-whisper` (which pulls `ctranslate2`).

> Windows note: use the 64-bit (amd64) Python 3.11+ install from
> python.org or winget — do not use the Microsoft Store stub.

## 2) Install Ollama (for the translation LLM)

1. Download Ollama for your OS: <https://ollama.com/download>.
2. Make sure the service is running:

   Linux/macOS (also running in the Ollama app menu on macOS):

   ```bash
   ollama serve
   ```

   Windows: the Ollama app starts a background service on its own — verify with
   `ollama list` in a fresh terminal.

3. Pull the translation model (do this once):

   ```bash
   ollama pull gemma3:4b
   ```

   `gemma3:4b` is a good default for a conference laptop. Smaller/faster
   options: `gemma3:1b`; larger/better: `gemma3:12b` (or `llama3.2:3b`
   if you prefer a Llama family model).
4. Optional: it can run on another machine in the same network — just point
   `OLLAMA_URL=http://<host>:11434` at it.

## 3) Configure the environment

Copy the example file and edit:

```bash
cp .env.example .env
```

Then set the local-only block (leave all `*_API_KEY` empty):

```dotenv
# Use the local route instead of cloud vendors (PyPI install of local extra).
PROVIDER=local

# Whisper model: tiny | base | small | medium | large-v3 | distil-large-v3
WHISPER_MODEL=small

# Whisper device:
#   macOS / Apple Silicon  -> auto (Metal where available) or cpu
#   Linux with NVIDIA GPU  -> cuda (optional, see section 4)
#   anywhere else          -> cpu (safe default)
WHISPER_DEVICE=auto

# Ollama (LLM for translations)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
```

`PROVIDER=local` is the classic single-provider routing. The modern equivalent
is to select the **`local` vendor** from the `/vendors` page (or as the
session's vendor in `/broadcast`); the two reach the same code.

> Any language combination works: Whisper transcribes the original's audio and
> Ollama translates its text. Expected latency is ~2–3 s (windowed STT), which
> is fine for conference captions on a local network.

## 4) Optional: GPU acceleration (Linux / Windows, NVIDIA)

Whisper runs happily on the CPU (the model is small: `small` ≈ 460 MB). If you
want CUDA acceleration:

```bash
pip install ctranslate2[cuda]
```

then set `WHISPER_DEVICE=cuda` in `.env` and make sure your driver exposes the
GPU (`nvidia-smi`). If you hit cuDNN/cuBLAS loading errors, follow
[ctranslate2's install notes](https://opennmt.net/CTranslate2/installation.html).
You can always revert to `WHISPER_DEVICE=cpu`.

On **macOS**, Metal is used automatically where supported (ctranslate2 builds
for Apple Silicon); if a model fails to load, fall back to `WHISPER_DEVICE=cpu`.

## 5) Run

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Windows:

```powershell
.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000
```

Then, as usual:

- `http://localhost:8000/broadcast` — create a session and start transmitting.
- `http://localhost:8000/` — audience view (pick a session + language).
- `http://localhost:8000/admin` — see live state; any provider error is shown
  directly under each language row.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `whisper: ...` error in `/admin` | Whisper failed to load. Check `WHISPER_MODEL` spelling and `WHISPER_DEVICE` for your OS (`small`, `cpu` are the safest). |
| `ollama inalcanzable en ...` | The Ollama service is not running or `OLLAMA_URL` is wrong. Start `ollama serve` and `ollama pull gemma3:4b`. |
| No translation captions | The original must first produce text; whisper windows need ≥ 2.5 s of speech (direct energy filter). Check the original's state and `STT_MIN_ENERGY_DB`. |
| Very slow first start | The first transcription downloads the Whisper model once (then cached under `~/.cache`). |
| Windows path issues | Use the amd64 Python and `.\\.venv\\Scripts\\...` binaries; avoid the Microsoft Store stub. |