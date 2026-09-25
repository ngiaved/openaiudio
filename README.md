# OpenAIudio

Open-source **live transcription + simultaneous translation** for conferences.
Run several sessions in parallel, stream captions to the audience in real time,
and give broadcast/production teams a console to control it all — all in a
single server that also serves its own React web app.

Made for [Nerdearla](https://nerdear.la), Apache-2.0.

## What was built

- **Event pipeline** — each session has an *original* captioner (always fed
  audio) and per-language *translate* captioners (fed by audio or by the
  original's final text, configurable per session: `audio | text | auto`).
- **Hybrid topology** (see [ADR-0001](docs/adr/0001-hybrid-topology.md)):
  - **Original updates:** Gemini STT over sliding audio windows
    (`generate_content` with an inline WAV part) or local `faster-whisper`.
  - **Translations:** Gemini text model (`generate_content`) or Gemma via
    Ollama, both streaming partial→final; Gemini Live (audio) is available as
    an experimental option.
- **Web UIs** — audience (`/`), broadcast console (`/broadcast`) and a
  production/admin panel (`/admin`), built with React/Vite and served by
  FastAPI (see [ADR-0002](docs/adr/0002-frontend-stack.md)).
- **Broadcast integrations** — REST/WS endpoints plus `.live.txt` feeds ready
  for OBS/vMix, and SRT/VTT/TXT export from the caption buffers.
- **Offline demo mode** — with no API key it runs a deterministic `mock`
  provider so demos and CI work anywhere (used by the test suite).
- **Vendors** — primary and fallback models are selectable per session from the
  web UI (`/vendors` page if you want to manage them): Gemini, xAI, OpenAI,
  Anthropic, Groq, Mistral, DeepSeek, Together, OpenRouter, Azure OpenAI
  (OpenAI-compatible), plus fully-local Whisper + Ollama.

## Why these decisions

The short version; full rationale lives in the
[ADR log](docs/adr/0001-hybrid-topology.md).

- **Chunked STT, not Gemini Live, for the original.** We validated the real
  Gemini API (google-genai): the `*-transcribe-live` / `*-live-translate-preview`
  models are preview and flaky (they would hang or abort; the default
  `*-flash-live-preview` does not even support a TEXT response modality).
  Windowed transcription with `generate_content` + inline audio turned out to be
  reliable, cheap and fully streamable — so it is the default for Gemini.
- **Translations stream from text by default.** One extra hop (original final →
  translation) but far cheaper and easier on rate limits than a Live connection
  per language. Set `TRANSLATION_MODE=audio` to opt into the experimental Live
  path (`GEMINI_LIVE_MODEL`).
- **Resilience first.** Free-tier Gemini is rate limited (≈20 requests/day per
  model). STT/translation calls retry with exponential backoff + jitter, each
  request has a hard timeout, and an energy gate (dBFS floor) skips requests on
  silence so you do not burn quota.
- **One process, one binary.** FastAPI serves the built React SPA plus all
  REST/WS endpoints — trivial to deploy behind a reverse proxy.

## Requirements

- Python 3.11+ · Node 20+ (only to build the frontend)
- Optional: a `GEMINI_API_KEY` (Google AI Studio) for cloud providers; `ollama`
  for the fully-local provider.

### Which Gemini model to use (cloud)

For captions to appear with `PROVIDER=gemini`, these two settings must point to
a **text-capable model that exists on your key/account** (set both in `.env`):

- `GEMINI_MODEL=gemini-3.8-flash` — original captions (windowed STT: inline
  audio → text).
- `GEMINI_TEXT_MODEL=gemini-3.8-flash` — translations (text → text). Defaults
  to `GEMINI_MODEL` when unset.

If the model name is wrong or unavailable, every request fails and **no
captions are produced**. `GEMINI_LIVE_MODEL` matters only for the experimental
`TRANSLATION_MODE=audio` path. Note the free tier is rate-limited to ~20
requests/day per model — a billing-enabled key is recommended for a real event
(see [DEPLOYMENT.md](docs/DEPLOYMENT.md)).

## Getting started

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env        # edit it — or leave no key to run in mock mode

cd web && npm install && npm run build && cd ..
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://localhost:8000` — audience view (pick session + language)
- `http://localhost:8000/broadcast` — create a session, pick a cloud or local
  vendor and start ingesting audio
- `http://localhost:8000/vendors` — manage model vendors (keys stay local)
- `http://localhost:8000/admin` — production panel (shows live provider errors)
- `http://localhost:8000/docs` — OpenAPI docs

## How to test

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/        # end-to-end pipeline with the mock provider
```

- **Local automated suite** — 36 tests cover the caption buffers, ingest/audience
  WS protocol, the admin/session/vendor APIs, the primary/fallback switching and
  cooldown logic, and the full e2e flow, all without network.
- **Frontend** — `cd web && npm run dev` runs Vite on :5173 proxying the backend.
- **Live smoke test (real Gemini)** — with a key in `.env` and `PROVIDER=gemini`:
  1. Start the server and create a session from `/broadcast`.
  2. Ingest ~12–16 s of speech audio (any 16 kHz mono PCM16 stream) on
     `/ws/ingest/{id}`.
  3. Connect an audience WS viewer (`/ws/audience/{id}?lang=es`) — you should see
     STT partials/finals and the text translation rolling in.
  Note: free-tier quota is small; if you hit 429/503 the providers retry and the
  event keeps `state: error` visible in `/admin` rather than dying.

## Architecture

- `app/store.py` — orchestrator: vendor resolution (primary/fallback per
  session), provider budgets, states, idle sweeping.
- `app/vendors.py` — the vendor registry loaded from the environment and the
  `/vendors` page (persisted to `data/vendors.json`).
- `app/providers/` — `gemini`, `openai_compat` (OpenAI/Anthropic/Groq/Kimi/
  OpenRouter/…), `xai`, `local` (Whisper + Ollama), `mock`.
- `app/captions.py` — per-language buffers and SRT/VTT/TXT export.
- `app/routers/` — REST + WS for ingest, audience, feeds, vendors and admin.

Deeper walkthroughs: [ARCHITECTURE.md](docs/ARCHITECTURE.md),
[DEPLOYMENT.md](docs/DEPLOYMENT.md), and a
[local-only HOWTO](docs/LOCAL_WHISPER.md) (Whisper + Ollama on macOS/Linux/Windows).

## Configuration

Every option is documented in [.env.example](.env.example): `PROVIDER`,
`GEMINI_MODEL`, `GEMINI_TEXT_MODEL`, `GEMINI_LIVE_MODEL`,
`TRANSLATION_MODE`, `STT_WINDOW_SEC`, `STT_STEP_SEC`, `STT_MIN_ENERGY_DB`,
`MAX_PROVIDERS`, `MAX_SESSIONS`, `IDLE_TIMEOUT_SEC`, `OBS_OUT_DIR`,
`WHISPER_MODEL`, `OLLAMA_URL`, `OLLAMA_MODEL`, `HOST`, `PORT`, …

Secrets live in `.env` (gitignored) and are never committed.

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [CHANGELOG.md](CHANGELOG.md).

## Security

Report vulnerabilities via [SECURITY.md](SECURITY.md). This project is **not**
a multi-tenant internet service — assume a trusted on-site network and put it
behind an HTTPS reverse proxy.

## License

[Apache License 2.0](LICENSE). © 2026 OpenAIudio contributors.