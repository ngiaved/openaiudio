# Architecture

> Technical overview of how OpenAIudio works. To run the project in
> production, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Pieces

```
browser (broadcaster) ── gUM + PCM16 16 kHz ──▶  WS /ws/ingest/{id}
browser (audience) ─────────────────────────▶  WS /ws/audience/{id}?lang=
OBS / vMix ──────────────────────────────────▶  GET /feed/{id}/live?lang=
                                                    (and .live.txt files on disk)
command line ───────────────────────────────▶  REST /api/sessions* + /healthz
```

A single **FastAPI** process (`app/`) that:

1. Receives audio from the broadcaster (`app/routers/sessions.py` → `ingest`).
2. Converts it to `float32` mono 16 kHz (`app/audio.py`) and pushes it to the
   orchestrator.
3. `app/store.py` decides, per session, which providers to bring up (original +
   translations) under an **active-provider budget** and feeds them audio or
   text according to each target's pathway.
4. Captions (`app/captions.py`) are assembled into per-(session, language)
   buffers that emit events to the audience and to feeds.
5. The audience receives a `snapshot` on connect, then `caption`
   (partial/final) and `state` events.

## Topology (ADR-0001)

- **Original**: always via audio.
- **Translation**: via audio (Gemini Live) or text (Gemini text / Gemma/Ollama),
  depending on `translation_mode` (`audio | text | auto`) and the provider.

## Providers

| Provider | Original | Translation | Use |
| --- | --- | --- | --- |
| `gemini` | Gemini Live (audio) | Gemini Live (audio) or Gemini text | cloud, quality |
| `local` | faster-whisper | Gemma via Ollama (text) | 100 % offline |
| `mock` | fake (periodic) | fake | demos and CI |

Per-target state machine: `warming → live ↔ idle`, retries with backoff, and
per-language audience counts. If a target has no listeners and exceeds the idle
timeout, the sweeper pauses it to free the budget.

## Public API

- `GET /api/sessions` · `POST /api/sessions` · `GET|DELETE /api/sessions/{id}`
- `POST /api/sessions/{id}/glossary`
- `GET /api/sessions/{id}/export?lang=&fmt=srt|vtt|txt`
- `GET /api/languages`
- `GET /healthz` · admin: `GET /admin/status` (see `app/routers/admin.py`)
- `WS /ws/ingest/{id}` · `WS /ws/audience/{id}?lang=`
- `GET /feed/{id}/live?lang=` (plain text) + OBS output on disk

## Frontend

A React/Vite SPA in `web/` (ADR-0002) served by FastAPI from `web/dist`. It has
three routes: `/` (pick a session), `/broadcast`, `/admin`, and
`/:sid[/:lang]` for the direct audience view.

## Configuration

Everything comes from environment variables (`.env.example`). Values are
resolved in `app/config.py`. `PROVIDER=auto` picks `gemini` when
`GEMINI_API_KEY` is set, otherwise `mock`.